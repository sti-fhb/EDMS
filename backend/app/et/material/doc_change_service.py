"""引用之 DM 文件改版 / 廢止時通知課程擁有者（#231，排程第 4 批）。

## 為何是排程而非 DM 發布當下通知（掛鉤機制 B′ vs A）

A 需要一套跨模組事件登記，而本專案既有的 `module_assign_registry` 已踩過它的失效
模式：找不到 provider 時 fallback 是 no-op，**不報錯、不留紀錄**。本功能存在的目的正是
消除無聲的漂移，若通知機制自己會無聲失效，教師會把「沒收到信」讀成「沒事」。排程失敗
則進 `DP_SCHEDULE_LOG`、DP06 排程總覽看得見。#231 裁示 B′。

⚠️ **延遲只在通知，不在內容**：學員端恆取當前發布版（`FR-ET-US3-05`），DM 一發布新版
下一位開啟章節的學員立刻看到新內容。本模組不改變取版行為。

## 簿記的寫入時機

**寄送成功（`queued_count > 0`）才前進簿記。** 順序相反會在寄信失敗時永久漏掉該次變動。
範本被管理者停用時 `queued_count` 亦為 0，故簿記同樣不前進——「沒有告訴他」就不該記成
「已告訴他」。代價是停用期間每輪都會重算（成本極低），好處是重新啟用後收件人會收到
反映**當前狀態**的那一封。
"""

import logging
from dataclasses import dataclass
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.utils import utcnow
from app.et.common.dm_client import get_dm_document_client
from app.et.constants import COURSE_DRAFT
from app.et.material.doc_change_repository import DocReferenceRow, list_doc_references, load_notify_state
from app.et.material.doc_change_rules import DOC_OBSOLETE, DocChangeEvent, classify_doc_change
from app.et.material.models import EtMaterialDocNotify
from app.et.notify.doc_changed import DocChangedMailer

logger = logging.getLogger(__name__)

_SYSTEM_USER: Final = "SYSTEM"


@dataclass(frozen=True)
class DocChangeNotifyResult:
    """一輪掃描的結果——供排程 log 與測試斷言。"""

    scanned_docs: int
    notified: int
    skipped_docs: int


class EtDocChangeNotifyService:
    """掃描引用之 DM 文件，對有變動者通知課程擁有者。"""

    def __init__(self, mailer: DocChangedMailer | None = None) -> None:
        self._mailer = mailer or DocChangedMailer()

    async def run(self, db: AsyncSession) -> DocChangeNotifyResult:
        """執行一輪掃描。

        Args:
            db: 資料庫 session（交易邊界由呼叫端管理）。

        Returns:
            本輪統計。
        """
        refs = await list_doc_references(db)
        if not refs:
            return DocChangeNotifyResult(scanned_docs=0, notified=0, skipped_docs=0)

        doc_ids = {r.doc_id for r in refs}
        state = await load_notify_state(db, doc_ids=doc_ids)
        client = get_dm_document_client()

        notified = 0
        skipped = 0
        for doc_id in sorted(doc_ids):
            try:
                current = await client.get_current_by_doc_id(db, doc_id)
            except AppError as exc:
                # 單一文件異常（尚無發布版 `DM_DOC_013`、非可引用分類 / 不存在 404）
                # **不得中斷整批**——否則一份壞掉的引用會讓所有教師都收不到通知。
                # ⛔ 不記 doc 內容，只記代碼與編號（編號非個資）。
                logger.warning("ET 文件變動掃描跳過 doc_id=%s error_code=%s", doc_id, exc.error_code)
                skipped += 1
                continue

            notified += await self._notify_owners_of(
                db,
                doc_id=doc_id,
                doc_name=current.doc_name,
                version_no=current.version_no,
                current_version_id=current.current_version_id,
                current_status=current.status,
                refs=[r for r in refs if r.doc_id == doc_id],
                state=state,
            )

        return DocChangeNotifyResult(scanned_docs=len(doc_ids), notified=notified, skipped_docs=skipped)

    async def _notify_owners_of(
        self,
        db: AsyncSession,
        *,
        doc_id: str,
        doc_name: str,
        version_no: str,
        current_version_id: int,
        current_status: str,
        refs: list[DocReferenceRow],
        state: dict[tuple[str, str], EtMaterialDocNotify],
    ) -> int:
        """對引用本文件的每位擁有者各判斷一次；回傳實際寄出的封數。"""
        # 🔴 **改版與廢止的課程範圍不同**（#231 裁示 Q2 = C）。
        #
        # 判準是「信的內容對那個狀態成不成立」，不是為了分類而分類：
        #
        # | 觸發 | 內文 | 對草稿 |
        # |---|---|---|
        # | 改版 | 「學員開啟章節時即會看到新內容」| **假的**——草稿沒有學員 |
        # | 廢止 | 「發布或再開課時會被擋下」| **成立**，且教師可能要到按下發布被擋才發現 |
        #
        # ⛔ 改版時草稿課程**連列都不列**——把一門沒有學員的草稿列在那句話底下，
        # 那句話對它就是假的。濾在這裡（service）而非查詢層：母體一旦在 SQL 被縮小，
        # 日後改裁示時沒有任何跡象提醒這裡曾經濾過。
        is_obsoleted = current_status == DOC_OBSOLETE
        by_owner: dict[str, list[str]] = {}
        for ref in refs:
            if not is_obsoleted and ref.course_status == COURSE_DRAFT:
                continue
            by_owner.setdefault(ref.owner_id, []).append(ref.course_name)

        sent = 0
        for owner_id, course_names in sorted(by_owner.items()):
            row = state.get((doc_id, owner_id))
            event = classify_doc_change(
                last_notified_version_id=row.last_notified_version_id if row else None,
                last_notified_status=row.last_notified_status if row else None,
                current_version_id=current_version_id,
                current_status=current_status,
            )
            if event is None:
                continue

            if event is DocChangeEvent.OBSOLETED:
                queued = await self._mailer.send_obsoleted(
                    db, owner_id=owner_id, doc_id=doc_id, doc_name=doc_name, course_names=course_names
                )
            else:
                queued = await self._mailer.send_version_changed(
                    db,
                    owner_id=owner_id,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    version_no=version_no,
                    course_names=course_names,
                )

            # 🔴 寄出才前進簿記（見模組 docstring）。
            if queued <= 0:
                continue
            self._upsert_state(
                db,
                row=row,
                doc_id=doc_id,
                owner_id=owner_id,
                version_id=current_version_id,
                status=current_status,
            )
            sent += 1
        return sent

    @staticmethod
    def _upsert_state(
        db: AsyncSession,
        *,
        row: EtMaterialDocNotify | None,
        doc_id: str,
        owner_id: str,
        version_id: int,
        status: str,
    ) -> None:
        now = utcnow()
        if row is None:
            db.add(
                EtMaterialDocNotify(
                    doc_id=doc_id,
                    owner_id=owner_id,
                    last_notified_version_id=version_id,
                    last_notified_status=status,
                    created_user=_SYSTEM_USER,
                    created_date=now,
                )
            )
            return
        row.last_notified_version_id = version_id
        row.last_notified_status = status
        row.updated_user = _SYSTEM_USER
        row.updated_date = now
