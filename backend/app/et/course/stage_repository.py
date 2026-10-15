"""已發布課程編輯暫存區的存取（#631）。

職責只有三件：**從活表種出整棵暫存樹**、**把暫存樹讀回來**、**清空**。
套用（暫存 → 活表）在 `stage_apply.py`；業務規則在 `stage_rules.py`（純函式）。

## 為何 seed 是「整棵複製」而不是「用到才複製」

暫存區存的是**完整的目標內容樹**，所以編輯端讀取就是直接讀它，不必把差異疊加回活表。
疊加邏輯會散落在 12 個讀取端點，而漏掉一處的症狀是**教師看不到自己剛做的編輯**。

代價是第一次編輯時多一次整棵複製。課程內容樹的量級是「章節 × 項目 × 題目」，
實務上數十到數百列，一次性成本可忽略。

## 活表遍歷不在這裡

在 `stage_live_tree.load_live_tree`，**與套用端的刪除偵測共用**——兩邊對「哪些列算
課程內容」必須給出完全相同的答案，理由見該模組 docstring。
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.course.models import EtCourse, EtCourseContentStage
from app.et.course.stage_entities import SPEC_BY_TYPE, EntitySpec, payload_fields
from app.et.course.stage_live_tree import LiveKey, load_live_tree
from app.et.course.stage_rules import StageNode


@dataclass(frozen=True)
class _SeedCtx:
    """一次 seed 期間共用的不變值。

    ⛔ 不放在 repository 實例上——本專案的 repository 一律無狀態，帶了狀態的那一份
    在同一請求內被重用時會用到上一次的操作者與時間戳。
    """

    course_id: int
    operator: OperatorInfo
    now: datetime


def to_payload(spec: EntitySpec, row: object) -> str:
    """把活表列的內容欄位序列化成 `PAYLOAD`。

    🔴 `json.dumps` 在遇到不可序列化的型別時會 `TypeError`——**那是刻意不接住的**。
    內容表若日後加了 `datetime` 之類的欄位，推導會自動把它納入 payload，而這裡會
    當場爆出來；靜默塞個字串進去才是真正的問題（套用時寫回活表會變成錯的型別）。
    """
    return json.dumps({f: getattr(row, f) for f in payload_fields(spec)}, ensure_ascii=False)


class EtCourseStageRepository:
    """暫存區的讀寫。"""

    async def has_stage(self, db: AsyncSession, course_id: int) -> bool:
        """該課程是否已有暫存區（＝教師已經開始編輯但還沒按「更新」）。"""
        found = await db.scalar(
            select(EtCourseContentStage.stage_id)
            .where(EtCourseContentStage.course_id == course_id, EtCourseContentStage.deleted == 0)
            .limit(1)
        )
        return found is not None

    async def load_tree(self, db: AsyncSession, course_id: int) -> tuple[StageNode, ...]:
        """讀回整棵暫存樹（扁平，彼此以 `parent_stage_id` 串接）。"""
        rows = await db.scalars(
            select(EtCourseContentStage)
            .where(EtCourseContentStage.course_id == course_id, EtCourseContentStage.deleted == 0)
            .order_by(EtCourseContentStage.stage_id)
        )

        def _payload(raw: str) -> dict:
            """⚠️ `PAYLOAD` 不是 JSON object 時**明確報錯**。

            非 dict 的話，下游 `f in node.payload` 會退化成子字串 / 成員測試、
            `payload[f]` 拋 TypeError——兩種都是難讀的 500。目前只有伺服端寫入故不可達，
            但這張表是 PR 2 的編輯端要寫的，守門放在讀取這一側才涵蓋得到全部寫入者。
            """
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise AppError(
                    status_code=500,
                    detail=f"暫存列的 PAYLOAD 不是 JSON object：{type(parsed).__name__}",
                    error_code="ET_STAGE_001",
                )
            return parsed

        return tuple(
            StageNode(
                stage_id=r.stage_id,
                entity_type=r.entity_type,
                source_id=r.source_id,
                parent_stage_id=r.parent_stage_id,
                sort_order=r.sort_order,
                payload=_payload(r.payload),
            )
            for r in rows.all()
        )

    async def lock_course(self, db: AsyncSession, course_id: int) -> None:
        """對課程列取**行鎖**，序列化同一門課的「更新」。

        🔴 沒有這把鎖，`load_tree → apply_stage → clear` 不是原子的。預設隔離等級是
        READ COMMITTED，兩個並發請求（教師雙擊、或兩個分頁同時按）會**各自讀到完整
        的暫存樹**，兩邊都跑新增 ⇒ `SOURCE_ID` 為 `None` 的節點被插入兩次，活表出現
        重複的章節 / 項目 / 題目。唯一索引擋不住——重複的那幾列排序各自獨立。

        ⚠️ 「第二次會看到空的暫存區而成為 no-op」只在兩次請求**先後**執行時成立。
        2026-10-14 的 code review 推翻了那個判斷。

        ⭐ 是悲觀鎖不是樂觀鎖：要序列化的是整段流程，不是偵測單一列的版本衝突。
        """
        await db.execute(select(EtCourse.course_id).where(EtCourse.course_id == course_id).with_for_update())

    async def clear(
        self, db: AsyncSession, course_id: int, operator: OperatorInfo, *, stage_ids: Sequence[int]
    ) -> None:
        """清空暫存區——**只清指定的那批 `STAGE_ID`**。

        ⛔ **不可改回 `WHERE COURSE_ID = ?`**：那會連「`load_tree` 之後才寫進來的編輯」
        一起清掉，而那筆編輯從來沒有被套用過——教師的輸入靜默消失，沒有任何錯誤訊息。
        呼叫端一律傳入自己實際載入並套用的那批 id。

        ⛔ 軟刪除（`DELETED = 1`），遵專案禁硬刪規範。唯一索引的條件帶 `DELETED = 0`，
        所以清空後再次編輯不會撞鍵。
        """
        if not stage_ids:
            return
        await db.execute(
            update(EtCourseContentStage)
            .where(
                EtCourseContentStage.course_id == course_id,
                EtCourseContentStage.stage_id.in_(list(stage_ids)),
                EtCourseContentStage.deleted == 0,
            )
            .values(deleted=1, updated_user=operator.user_id, updated_date=utcnow())
        )
        await db.flush()

    async def seed_from_live(self, db: AsyncSession, course_id: int, operator: OperatorInfo) -> None:
        """把活表的內容樹整棵複製進暫存區。

        遍歷用 `stage_live_tree.load_live_tree`——**與套用端的刪除偵測共用同一支**。
        各寫一份的話，只有 seed 漏搬某一種時，刪除偵測會把它判成「教師刪了它」而在按下
        「更新」時連帶軟刪（見該模組 docstring）。

        ⚠️ 呼叫端須先確認暫存區是空的——重複 seed 會被唯一索引
        `(COURSE_ID, ENTITY_TYPE, SOURCE_ID)` 擋下。那是正確的 fail-closed，但訊息不好讀。
        """
        ctx = _SeedCtx(course_id=course_id, operator=operator, now=utcnow())
        stage_id_by_key: dict[LiveKey, int] = {}

        # `load_live_tree` 保證父節點排在子節點之前，所以查父層的 `STAGE_ID` 必定查得到。
        for node in await load_live_tree(db, course_id):
            parent_stage_id = None if node.parent_key is None else stage_id_by_key[node.parent_key]
            stage_id_by_key[node.key] = await self._add(
                db, ctx, node.entity_type, node.row, parent=parent_stage_id, sort_order=node.sort_order
            )
        await db.flush()

    async def _add(
        self, db: AsyncSession, ctx: _SeedCtx, entity_type: str, row: object, *, parent: int | None, sort_order: int
    ) -> int:
        """新增一列暫存並回傳其 `STAGE_ID`（供子層當 `PARENT_STAGE_ID`）。"""
        spec = SPEC_BY_TYPE[entity_type]
        stage = EtCourseContentStage(
            course_id=ctx.course_id,
            entity_type=entity_type,
            source_id=getattr(row, spec.pk),
            parent_stage_id=parent,
            sort_order=sort_order,
            payload=to_payload(spec, row),
            created_user=ctx.operator.user_id,
            created_date=ctx.now,
        )
        db.add(stage)
        # 🔴 **必須當場 flush**：子層要拿它的 `STAGE_ID` 當父參照，而那是 Identity 欄位，
        # 不 flush 取不到。
        await db.flush()
        return stage.stage_id


def nodes_by_type(nodes: Sequence[StageNode], entity_type: str) -> list[StageNode]:
    """測試與套用端共用的小工具。"""
    return [n for n in nodes if n.entity_type == entity_type]
