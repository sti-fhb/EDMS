"""個人專區（US9）資料存取：草稿匣（三類）+ 我的文件動態（衍生查詢，無新表）。"""

from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, aliased

from app.dm.document.models import DmDocument, DmDocVersion
from app.dm.review.models import DmReview
from app.dp.users.models import DpUser  # 唯讀 join（報表/查詢例外，同 dm/review、dm/detail）

_DRAFT = "DRAFT"
_PENDING = "PENDING"


def _within_window_or_pending(since: datetime):
    """動態清單的時間條件：近 N 天內有動作，**或**仍在 `PENDING`（#395 D-1）。

    ## 為何 `PENDING` 不受窗口限制

    窗口的語意是「近期**歷程**」，而 `PENDING` 是**當前狀態**不是歷程。一筆卡住的送審
    `complete_date` 為 `NULL`、`submit_date` 又早於窗口，兩個條件都不成立——那一列
    **根本不會從資料庫回來**，於是撰寫者連撤回的入口都沒有（撤回按鈕渲染在每一列事件上）。

    ⚠️ 判準刻意是 **`PENDING` 本身**，不是「逾催辦門檻」：後者得把 `DM_REMIND_THRESHOLD`
    傳進查詢層，使「這筆案件存不存在於畫面上」取決於一個**催辦設定**。兩件事不該綁在一起。

    ⛔ 豁免只給 `PENDING`：已結案者仍受窗口限制，否則動態會無限成長——那正是窗口存在的理由。
    """
    return or_(DmReview.submit_date >= since, DmReview.complete_date >= since, DmReview.status == _PENDING)


class PersonalRepository:
    """草稿匣 / 我的文件動態查詢。"""

    async def list_user_drafts(self, db: AsyncSession, user_id: str) -> list[Row]:
        """該使用者之 DRAFT 版本 + 該版本最近一次送審狀態（供三類分類）+ 父文件狀態（供前端判可否續編）。

        DRAFT 版本只會是：從未送審 / 被退回回草稿（REJECTED）/ 已撤回回草稿（WITHDRAWN）——
        PENDING 中之版本為 PENDING_REVIEW、不在此列。以相關子查詢取最近一次 DM_REVIEW.status。
        不依父文件狀態過濾（含已廢止 / 廢止待簽核之孤兒草稿皆列出，與「他人送審中文件之草稿不隱藏」一致）；
        父文件已廢止（OBSOLETE）者前端灰掉「繼續編輯」、由使用者自行刪除（doc_status 供判斷）。
        """
        # tie-break review_id：同版本兩筆 review 之 submit_date 相同時（快速連續 utcnow）取用穩定
        latest_status = (
            select(DmReview.status)
            .where(DmReview.version_id == DmDocVersion.version_id)
            .order_by(DmReview.submit_date.desc(), DmReview.review_id.desc())
            .limit(1)
            .correlate(DmDocVersion)
            .scalar_subquery()
        )
        stmt = (
            select(
                DmDocVersion.version_id,
                DmDocVersion.doc_id,
                DmDocVersion.version_no,
                DmDocVersion.change_summary,
                # 最後編輯時間：未編輯過（updated_date NULL）之首存草稿退回 created_date（存草稿時間），避免顯示空白
                func.coalesce(DmDocVersion.updated_date, DmDocVersion.created_date).label("updated_date"),
                DmDocument.doc_name,
                DmDocument.category_code,
                DmDocument.status.label("doc_status"),
                latest_status.label("latest_review_status"),
            )
            .join(DmDocument, (DmDocVersion.doc_id == DmDocument.doc_id) & (DmDocument.deleted == 0))
            .where(
                DmDocVersion.created_user == user_id,
                DmDocVersion.status == _DRAFT,
                DmDocVersion.deleted == 0,
            )
            # 排序鍵以「最後異動」為準，未編輯過（updated_date NULL）之新草稿退回 created_date，避免排最後
            .order_by(
                func.coalesce(DmDocVersion.updated_date, DmDocVersion.created_date).desc(),
                DmDocVersion.version_id.desc(),
            )
        )
        return list((await db.execute(stmt)).all())

    async def get_version(self, db: AsyncSession, version_id: int, *, for_update: bool = False) -> DmDocVersion | None:
        """取未刪除版本（草稿刪除授權 / 狀態檢核用）；for_update=True 時上鎖（刪除路徑防 TOCTOU）。"""
        stmt = select(DmDocVersion).where(DmDocVersion.version_id == version_id, DmDocVersion.deleted == 0)
        if for_update:
            stmt = stmt.with_for_update()
        return await db.scalar(stmt)

    def _activity_select(self, *, party_col: InstrumentedAttribute[str]) -> Select[Any]:
        """組 activity 基礎查詢：送審週期各欄 + 對造人姓名（party_col 對應之 DP_USER.USER_NAME）。

        最終呈現順序由 service 依展開後之事件時間重排（見 PersonalService._build_events），此處不加 order_by。
        """
        party_user = aliased(DpUser)
        return (
            select(
                DmReview.review_id,
                DmReview.doc_id,
                DmReview.review_type,
                DmReview.status,
                DmReview.submit_date,
                DmReview.complete_date,
                DmDocument.doc_name,
                party_user.user_name.label("party_name"),
                # 對造人帳號狀態（#395 D-2）。**不在查詢層判定**——`STATUS` 值域屬 DP 語意，
                # 由 service 經 `dp.users.account_status.is_account_disabled()` 解讀。
                #
                # ⚠️ `party_user` 是 `outerjoin`，查無使用者時兩欄皆為 `None`；那是「查無帳號」
                # 而非「已停用」，兩者補救動作不同（修資料 vs 換審核者），呼叫端須分開判讀。
                party_user.status.label("party_status"),
                party_user.deleted.label("party_deleted"),
            )
            .join(DmDocument, (DmReview.doc_id == DmDocument.doc_id) & (DmDocument.deleted == 0))
            .outerjoin(party_user, party_col == party_user.user_id)
        )

    async def list_author_activity(self, db: AsyncSession, user_id: str, since: datetime) -> list[Row]:
        """撰寫者視角近 30 天狀態變動事件——僅本人送出之送審（created_user＝我；含本人自行發起之廢止）。

        本人「未發起」但被他人廢止之文件不進動態（避免看起來像自己發起廢止）——該情形改由草稿匣孤兒草稿
        之灰化續編呈現（list_user_drafts 帶 doc_status）。對造人 party_name＝指定審核者姓名。
        """
        stmt = self._activity_select(party_col=DmReview.assigned_reviewer).where(
            DmReview.created_user == user_id,
            _within_window_or_pending(since),
        )
        return list((await db.execute(stmt)).all())

    async def list_reviewer_activity(self, db: AsyncSession, user_id: str, since: datetime) -> list[Row]:
        """審核者視角近 30 天狀態變動事件（assigned_reviewer＝我）；對造人 party_name＝送審者姓名。"""
        stmt = self._activity_select(party_col=DmReview.created_user).where(
            DmReview.assigned_reviewer == user_id,
            _within_window_or_pending(since),
        )
        return list((await db.execute(stmt)).all())
