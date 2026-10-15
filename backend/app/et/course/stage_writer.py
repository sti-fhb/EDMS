"""已發布課程的編輯寫入暫存區（#631 PR 2）。

## 這支的介面**刻意**與既有 repository 不同

| | 既有 repository（如 `EtChapterRepository`）| 本 writer |
|---|---|---|
| 寬度 | 8 支，**型別專屬** | 4 支，**泛型於實體型別** |
| `soft_delete_with_cascade` | 連帶刪學員進度、作答明細、完課戳記 | **沒有對應物**——cascade 是
  「更新」套用時才做（`stage_apply._DELETERS`）|
| `resequence_remaining` | 刪除後補順序 | 同上，套用時由 `_park_sort_orders` 處理 |
| `bump_version` | 活表列的樂觀鎖 | 暫存列**自己的** `VERSION`，兩者計數獨立 |

⛔ **不要為了「統一介面」把兩者塞進同一個抽象。** 兩種模式做的事本來就不同，逼它們
一樣只會製造一個名字底下兩種語意——而那正是日後有人改錯邊的地方。

service 的結構因此是「決策點共用、分支不共用」：

```python
course = await self._require_owned(db, course_id, operator.user_id)   # 既有，不動
if is_staged(course):
    await self._stage_writer.append(...)
    return
# 以下草稿路徑：既有 repository，一行不動
```

🔴 **「漏改一支」這個風險本模組擋不住**——它只能靠
`tests/integration/et/test_et_staged_write_paths.py` 的逐端點列舉。新增內容編輯端點時
必須同時補那張清單。
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.constants import COURSE_DRAFT
from app.et.course.models import EtCourseContentStage
from app.et.course.stage_repository import EtCourseStageRepository


def is_staged(course: Any) -> bool:
    """這門課的內容編輯要不要走暫存區。

    **草稿以外都要**（已發布、已關閉）。判準是「有沒有學員看得到的版本」：

    - 草稿沒有學員、沒有人開得了章節 ⇒ 不需版本化，編輯直接生效
    - 已關閉的課程學員仍可唯讀回看（`is_effectively_closed` 對 `CLOSED` 回 `True`，
      但學員端照樣讀得到內容）⇒ **也有「學員看得到的版本」**，故同樣走暫存

    ⚠️ 用 `!= COURSE_DRAFT` 而非列舉 `{PUBLISHED, CLOSED}`：日後若新增狀態，預設落在
    「要暫存」這一邊——那是 fail-safe 的方向（內容不會意外立即生效）。
    """
    return course.status != COURSE_DRAFT


@dataclass(frozen=True)
class StageRef:
    """一個暫存節點的位置。"""

    stage_id: int
    course_id: int


def exposed_id(*, source_id: int | None, stage_id: int) -> int:
    """暫存節點對外（前端 / API）呈現的 id。

    🔴 **正負號把兩個號碼空間徹底隔開。**

    `ET_CHAPTER` 等活表與 `ET_COURSE_CONTENT_STAGE` 是各自獨立的 identity 序列，**號碼
    重疊是必然**。若兩種 id 都用正數，`PUT /chapters/{id}` 這種沒有課程上下文的端點就
    分不出收到的是哪一種——而「先查暫存、查不到再查活表」會在同一位教師同時有草稿課與
    已發布課時解析到**錯的那一筆**，且不會報錯，只會改錯東西。

    | 節點 | 對外 id | 為何 |
    |---|---|---|
    | 既有內容（有 `SOURCE_ID`）| **活表 id**（正數）| 與今天完全相同，前端無感 |
    | 本次編輯新增的（無 `SOURCE_ID`）| **`-STAGE_ID`**（負數）| 它還不存在於活表，負號正好表達這件事 |

    ⚠️ 連帶代價：編輯端點的 `Path(ge=1)` 要放寬為允許負數。漏改一處的症狀是 422
    ——**看得見**，不是靜默走錯路。
    """
    return source_id if source_id is not None else -stage_id


class EtCourseStageWriter:
    """暫存區的編輯操作。

    ⚠️ 每一支都會先 `ensure_seeded`——教師的第一次編輯必須先把活表的內容樹整棵複製
    進來，否則暫存區只有那一筆新編輯，「更新」時會把其餘內容全部當成「教師刪了它」。
    """

    def __init__(self, stage: EtCourseStageRepository | None = None) -> None:
        self._stage = stage or EtCourseStageRepository()

    async def ensure_seeded(self, db: AsyncSession, course_id: int, operator: OperatorInfo) -> None:
        """暫存區是空的就先從活表種一棵樹。"""
        if not await self._stage.has_stage(db, course_id):
            await self._stage.seed_from_live(db, course_id, operator)

    async def append(
        self,
        db: AsyncSession,
        course_id: int,
        entity_type: str,
        *,
        parent_stage_id: int | None,
        payload: Mapping[str, Any],
        operator: OperatorInfo,
    ) -> int:
        """在同層末尾新增一個節點，回傳其 `STAGE_ID`。

        `SOURCE_ID` 為 `None`——活表還沒有這一列，要到「更新」套用時才建立。
        """
        await self.ensure_seeded(db, course_id, operator)
        now = utcnow()
        last = await db.scalar(
            select(func.max(EtCourseContentStage.sort_order)).where(
                EtCourseContentStage.course_id == course_id,
                EtCourseContentStage.entity_type == entity_type,
                EtCourseContentStage.parent_stage_id.is_(parent_stage_id)
                if parent_stage_id is None
                else EtCourseContentStage.parent_stage_id == parent_stage_id,
                EtCourseContentStage.deleted == 0,
            )
        )
        row = EtCourseContentStage(
            course_id=course_id,
            entity_type=entity_type,
            source_id=None,
            parent_stage_id=parent_stage_id,
            sort_order=(last or 0) + 1,
            payload=json.dumps(dict(payload), ensure_ascii=False),
            version=0,
            created_user=operator.user_id,
            created_date=now,
        )
        db.add(row)
        await db.flush()
        return row.stage_id

    async def update_payload(
        self,
        db: AsyncSession,
        stage_id: int,
        *,
        version: int,
        payload: Mapping[str, Any],
        operator: OperatorInfo,
    ) -> int:
        """改一個節點的欄位值，**帶暫存列自己的樂觀鎖**。

        Returns:
            命中列數——呼叫端以 `ensure_version_matched` 判定衝突，與草稿路徑同一形狀。
        """
        result = await db.execute(
            update(EtCourseContentStage)
            .where(
                EtCourseContentStage.stage_id == stage_id,
                EtCourseContentStage.version == version,
                EtCourseContentStage.deleted == 0,
            )
            .values(
                payload=json.dumps(dict(payload), ensure_ascii=False),
                version=EtCourseContentStage.version + 1,
                updated_user=operator.user_id,
                updated_date=utcnow(),
            )
        )
        await db.flush()
        return result.rowcount

    async def bump_version(self, db: AsyncSession, stage_id: int, version: int, operator: OperatorInfo) -> int:
        """只遞增暫存列的 `VERSION`，不動 payload——供「重排」這種改動下層順序的操作。

        與草稿路徑同一形狀：重排改的是**下一層**的順序，所以用上一層的版本當併發令牌，
        而不遞增下層各列的版本（否則正在編輯該教材的另一裝置會無故衝突，
        違反 `FR-ET-US3-15`）。

        Returns:
            命中列數——呼叫端以 `ensure_version_matched` 判定衝突。
        """
        result = await db.execute(
            update(EtCourseContentStage)
            .where(
                EtCourseContentStage.stage_id == stage_id,
                EtCourseContentStage.version == version,
                EtCourseContentStage.deleted == 0,
            )
            .values(
                version=EtCourseContentStage.version + 1,
                updated_user=operator.user_id,
                updated_date=utcnow(),
            )
        )
        await db.flush()
        return result.rowcount

    async def children_of(
        self, db: AsyncSession, course_id: int, entity_type: str, parent_stage_id: int | None
    ) -> list[EtCourseContentStage]:
        """某節點底下指定型別的子節點，依 `SORT_ORDER` 排序。"""
        stmt = select(EtCourseContentStage).where(
            EtCourseContentStage.course_id == course_id,
            EtCourseContentStage.entity_type == entity_type,
            EtCourseContentStage.deleted == 0,
        )
        stmt = stmt.where(
            EtCourseContentStage.parent_stage_id.is_(None)
            if parent_stage_id is None
            else EtCourseContentStage.parent_stage_id == parent_stage_id
        )
        rows = await db.scalars(stmt.order_by(EtCourseContentStage.sort_order, EtCourseContentStage.stage_id))
        return list(rows.all())

    async def apply_order(self, db: AsyncSession, stage_ids: Sequence[int], operator: OperatorInfo) -> None:
        """依給定順序重設 `SORT_ORDER`（1 起算）。

        ⚠️ **不需要草稿路徑那種兩階段寫入**：暫存表沒有 `(父, SORT_ORDER)` 的唯一索引
        （PR 1 只對 `(COURSE_ID, ENTITY_TYPE, SOURCE_ID)` 設唯一），所以中途重複不會撞鍵。
        撞鍵的風險在「更新」套用時才出現，由 `stage_apply._park_sort_orders` 處理。
        """
        now = utcnow()
        for order, stage_id in enumerate(stage_ids, start=1):
            await db.execute(
                update(EtCourseContentStage)
                .where(EtCourseContentStage.stage_id == stage_id, EtCourseContentStage.deleted == 0)
                .values(sort_order=order, updated_user=operator.user_id, updated_date=now)
            )
        await db.flush()

    async def delete_subtree(self, db: AsyncSession, stage_id: int, operator: OperatorInfo) -> None:
        """移除一個節點與其整棵子樹。

        🔴 **必須連子樹一起移除**：只刪中間一層會讓子節點的 `PARENT_STAGE_ID` 落空，
        而那種樹會被 `stage_apply._validate_tree` 當場擋下（500 `ET_STAGE_001`）——
        教師看到的是「按更新就壞掉」，而壞的其實是刪除那一步。

        ⛔ 軟刪除（`DELETED = 1`），遵專案禁硬刪規範。
        """
        nodes = await self._stage.load_tree(db, await self._course_of(db, stage_id))
        subtree = {stage_id}
        # 巢狀最深 5 層（章節→項目→測驗→題目→選項），逐層往下收。
        for _ in range(5):
            subtree |= {n.stage_id for n in nodes if n.parent_stage_id in subtree}
        await db.execute(
            update(EtCourseContentStage)
            .where(EtCourseContentStage.stage_id.in_(subtree), EtCourseContentStage.deleted == 0)
            .values(deleted=1, updated_user=operator.user_id, updated_date=utcnow())
        )
        await db.flush()

    async def resolve_new(self, db: AsyncSession, exposed: int) -> StageRef | None:
        """負數 id ⇒ 本次編輯新增的暫存節點。正數回 `None`（呼叫端走活表解析）。"""
        if exposed >= 0:
            return None
        row = await db.scalar(
            select(EtCourseContentStage).where(
                EtCourseContentStage.stage_id == -exposed, EtCourseContentStage.deleted == 0
            )
        )
        return None if row is None else StageRef(stage_id=row.stage_id, course_id=row.course_id)

    async def ref_for_source(
        self, db: AsyncSession, course_id: int, entity_type: str, source_id: int, operator: OperatorInfo
    ) -> StageRef:
        """既有內容（活表 id）在暫存區的對應節點；暫存區還沒種就先種。"""
        await self.ensure_seeded(db, course_id, operator)
        stage_id = await db.scalar(
            select(EtCourseContentStage.stage_id).where(
                EtCourseContentStage.course_id == course_id,
                EtCourseContentStage.entity_type == entity_type,
                EtCourseContentStage.source_id == source_id,
                EtCourseContentStage.deleted == 0,
            )
        )
        if stage_id is None:
            # 活表有、暫存沒有 ⇒ seed 漏搬了那一種實體。靜默略過會讓教師「編了沒生效」，
            # 故當場拋錯；`test_種出的樹涵蓋十一種實體` 是它的上游守門。
            raise AppError(
                status_code=500,
                detail=f"暫存區缺少對應節點：{entity_type} SOURCE_ID={source_id}",
                error_code="ET_STAGE_001",
            )
        return StageRef(stage_id=stage_id, course_id=course_id)

    @staticmethod
    async def _course_of(db: AsyncSession, stage_id: int) -> int:
        return await db.scalar(select(EtCourseContentStage.course_id).where(EtCourseContentStage.stage_id == stage_id))
