"""把編輯暫存區套用到活表（#631）。

這是整個設計裡**唯一會改動已發布課程內容**的地方。呼叫端（`publish_service.update_published`）
必須在檢核通過之後、同一個交易裡呼叫它。

## 三個階段，順序不可調換

| # | 階段 | 為何是這個順序 |
|---|---|---|
| 1 | **刪除**：活表有而暫存沒有的，軟刪 | 先把排序槽讓出來。軟刪後 `DELETED = 1`，
  便退出所有 `WHERE "DELETED" = 0` 的部分唯一索引 |
| 2 | **排序移至負數暫存區** | `UX_ET_ITEM_CHAPTER_ORDER` 等是**非 deferrable** 的部分唯一
  索引、逐列即時檢核，直接對調兩列的順序會在中途撞鍵（比照 `EtItemRepository.apply_order`）|
| 3 | **寫入**：既有列更新欄位、新增列插入 | 此時全部目標槽都是空的 |

⚠️ 把 1 挪到 3 之後，「刪掉第 1 項、第 2 項遞補成第 1」會在第 3 階段撞鍵——而那是最
常見的編輯動作之一。

## 刪除一律委派既有的 cascade

⛔ **不在這裡另寫刪除邏輯。** `EtItemRepository.soft_delete_with_cascade` 除了項目本身，
還處理學員進度、教材 / 測驗本體，以及 `stamp_completed_at`（#464：學員 2/3、教師刪掉
剩下那一項 ⇒ 2/2 即完課，那條路不經過任何 `set_item_completed`）。

⭐ 因此規劃 §9 的「**完課回退只在更新時發生**」是自動成立的，不需要另外寫：回退就發生
在這一刀下去的時候，而這一刀只在「更新」當下落下。

## `MATERIAL` / `QUIZ` 不在刪除階段處理

它們隨所屬項目一起被 `EtItemRepository.soft_delete_with_cascade` 刪掉。項目型別不可變、
一個項目恆對一份教材或一份測驗，所以「教材該刪但項目留著」不存在。
`test_套用不單獨刪除教材與測驗` 釘住這個前提。
"""

import logging
from collections.abc import Sequence
from typing import Any, Final

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.course.models import EtCourse
from app.et.course.repository import EtChapterRepository, EtItemRepository
from app.et.course.stage_entities import APPLY_ORDER, LINK_CHILD_FK, LINK_PARENT_FK, SPEC_BY_TYPE, payload_fields
from app.et.course.stage_live_tree import load_live_tree
from app.et.course.stage_rules import (
    ENTITY_CHAPTER,
    ENTITY_ITEM,
    ENTITY_MATERIAL,
    ENTITY_MATERIAL_DOC,
    ENTITY_MATERIAL_VIDEO,
    ENTITY_OPTION,
    ENTITY_QUESTION,
    ENTITY_QUIZ,
    ENTITY_SURVEY,
    ENTITY_SURVEY_OPTION,
    ENTITY_SURVEY_QUESTION,
    StageNode,
)
from app.et.material.repository import EtMaterialRepository
from app.et.quiz.models import EtOption
from app.et.quiz.repository import EtQuizRepository
from app.et.survey.models import EtSurveyOption
from app.et.survey.repository import EtSurveyRepository

logger = logging.getLogger(__name__)

#: 隨所屬項目一起刪，不單獨處理（見模組 docstring）。
_DELETED_WITH_ITEM = frozenset({ENTITY_MATERIAL, ENTITY_QUIZ})


async def apply_stage(
    db: AsyncSession, *, course: EtCourse, nodes: Sequence[StageNode], operator: OperatorInfo
) -> None:
    """把暫存樹套用到活表。

    Args:
        db: 交易由呼叫端管理——本函式**不 commit**，失敗時整批回滾（AC 2 的「未通過
            時不得部分生效」靠的就是這件事）。
        course: 目標課程（活表列）。
        nodes: 該課程的整棵暫存樹。
        operator: 稽核欄位用。
    """
    _validate_tree(nodes)
    staged_sources: dict[str, set[int]] = {}
    for node in nodes:
        if node.source_id is not None:
            staged_sources.setdefault(node.entity_type, set()).add(node.source_id)

    await _delete_removed(db, course_id=course.course_id, staged_sources=staged_sources, operator=operator)
    await _park_sort_orders(db, nodes=nodes, operator=operator)
    await _upsert(db, course=course, nodes=nodes, operator=operator)


def _validate_tree(nodes: Sequence[StageNode]) -> None:
    """父參照必須指得到——斷鏈時**當場報錯，而不是寫一半**。

    少了這道，斷鏈會在 `_upsert` 解析父層時變成 `KeyError: <某個數字>`，看不出是哪棵樹、
    哪個節點、為什麼。而這種樹編輯端不可能產生，出現就代表有人繞過編輯端直接動暫存表。

    ⚠️ 本函式**不驗**「每個項目都有教材或測驗子節點」——孤兒項目（教材已軟刪、項目
    還在）在 `load_live_tree` 就會缺那個子節點，而那是今天可容忍的既有狀態
    （`BLOCK_ITEM_NO_TITLE` 會擋住它發布）。驗了會讓既有資料無法更新。
    """
    known = {n.stage_id for n in nodes}
    dangling = [n for n in nodes if n.parent_stage_id is not None and n.parent_stage_id not in known]
    if dangling:
        detail = ", ".join(f"STAGE_ID={n.stage_id}->{n.parent_stage_id}" for n in dangling[:5])
        raise ValueError(f"暫存樹的父參照斷鏈（共 {len(dangling)} 筆）：{detail}")


async def _delete_removed(
    db: AsyncSession, *, course_id: int, staged_sources: dict[str, set[int]], operator: OperatorInfo
) -> None:
    """活表有而暫存沒有的 ⇒ 教師刪了它。

    🔴 活表樹**在刪除開始前一次載入**，之後不重讀：`EtItemRepository.soft_delete_with_cascade`
    會連帶刪掉教材 / 測驗，重讀會看到被連帶刪掉的列而重複處理。

    由葉往根刪（`APPLY_ORDER` 的反向），讓每一層的 cascade 都在其子層已處理完之後才跑。
    """
    live = await load_live_tree(db, course_id)
    live_ids: dict[str, list[int]] = {}
    for node in live:
        live_ids.setdefault(node.entity_type, []).append(node.key[1])

    for spec in reversed(APPLY_ORDER):
        if spec.entity_type in _DELETED_WITH_ITEM:
            continue
        staged = staged_sources.get(spec.entity_type, set())
        removed = [live_id for live_id in live_ids.get(spec.entity_type, []) if live_id not in staged]
        if removed:
            await _DELETERS[spec.entity_type](db, removed, operator)


async def _delete_options(db: AsyncSession, model: Any, pk: str, ids: list[int], operator: OperatorInfo) -> None:
    """選項沒有任何學員資料指著它（`SELECTED_OPTIONS` / `OPTIONS_SNAPSHOT` 存的是文字
    快照），故無 cascade 可委派，直接軟刪。"""
    await db.execute(
        update(model)
        .where(getattr(model, pk).in_(ids), model.deleted == 0)
        .values(deleted=1, updated_user=operator.user_id, updated_date=utcnow())
    )
    await db.flush()


async def _delete_each(handler: Any, db: AsyncSession, ids: list[int], operator: OperatorInfo) -> None:
    """包裝只收單一 id 的既有刪除路徑。"""
    for one in ids:
        await handler(db, one, operator)


#: 每一種可刪除的實體 → 它的刪除路徑。
#:
#: ⛔ **一律委派既有實作，不在本模組自己寫軟刪**：那些函式各自處理了學員資料的連帶
#: （進度、作答明細、完課戳記），重寫一份必然漏掉其中一項，而漏掉的那一項不會報錯。
#:
#: `MATERIAL` / `QUIZ` 不在此表——它們隨所屬項目一起被刪（見模組 docstring）。
_DELETERS: Final[dict[str, Any]] = {
    ENTITY_CHAPTER: lambda db, ids, op: EtChapterRepository().soft_delete_with_cascade(db, ids, op),
    ENTITY_ITEM: lambda db, ids, op: EtItemRepository().soft_delete_with_cascade(db, ids, op),
    # 連其選項一起軟刪；**學員的作答明細不動**（`ET_QUIZ_ATTEMPT_D` 自給自足，
    # 見該函式 docstring 的 #279 裁示 Q2 = C）。
    ENTITY_QUESTION: lambda db, ids, op: EtQuizRepository().soft_delete_questions(db, ids, op),
    ENTITY_MATERIAL_VIDEO: lambda db, ids, op: _delete_each(EtMaterialRepository().soft_delete_video, db, ids, op),
    ENTITY_MATERIAL_DOC: lambda db, ids, op: _delete_each(EtMaterialRepository().soft_delete_doc, db, ids, op),
    ENTITY_SURVEY: lambda db, ids, op: _delete_each(EtSurveyRepository().soft_delete_survey, db, ids, op),
    ENTITY_SURVEY_QUESTION: lambda db, ids, op: _delete_each(EtSurveyRepository().soft_delete_question, db, ids, op),
    ENTITY_OPTION: lambda db, ids, op: _delete_options(db, EtOption, SPEC_BY_TYPE[ENTITY_OPTION].pk, ids, op),
    ENTITY_SURVEY_OPTION: lambda db, ids, op: _delete_options(
        db, EtSurveyOption, SPEC_BY_TYPE[ENTITY_SURVEY_OPTION].pk, ids, op
    ),
}


async def _park_sort_orders(db: AsyncSession, *, nodes: Sequence[StageNode], operator: OperatorInfo) -> None:
    """把既有列的排序移到負數暫存區（兩階段寫入的第一階段）。

    🔴 非 deferrable 的部分唯一索引逐列即時檢核：直接把兩列的順序對調會在中途撞鍵。
    比照 `EtItemRepository.apply_order` 的兩階段寫法，只是範圍擴大到整棵樹。

    負值取「全樹序號」而非同層序號——全域唯一就不可能在任何父層底下撞鍵。
    """
    now = utcnow()
    for offset, node in enumerate(nodes, start=1):
        if node.source_id is None:
            continue
        spec = SPEC_BY_TYPE[node.entity_type]
        if not hasattr(spec.model, "sort_order"):
            continue
        await db.execute(
            update(spec.model)
            .where(getattr(spec.model, spec.pk) == node.source_id, spec.model.deleted == 0)
            .values(sort_order=-offset, updated_user=operator.user_id, updated_date=now)
        )
    await db.flush()


async def _upsert(
    db: AsyncSession,
    *,
    course: EtCourse,
    nodes: Sequence[StageNode],
    operator: OperatorInfo,
) -> None:
    """依 `APPLY_ORDER` 逐型別寫入；回填 `STAGE_ID → 活表 id` 供子層與反向連結使用。"""
    now = utcnow()
    live_id_by_stage: dict[int, int] = {}
    # 反向連結（`ET_ITEM.MATERIAL_ID` / `QUIZ_ID`）：父層要用子層的活表 id。
    reverse_child: dict[tuple[int, str], int] = {}

    for spec in APPLY_ORDER:
        for node in [n for n in nodes if n.entity_type == spec.entity_type]:
            values: dict[str, Any] = {f: node.payload.get(f) for f in payload_fields(spec)}
            if hasattr(spec.model, "sort_order"):
                values["sort_order"] = node.sort_order
            if spec.link == LINK_CHILD_FK:
                values[spec.fk] = (
                    course.course_id if node.parent_stage_id is None else live_id_by_stage[node.parent_stage_id]
                )
            if spec.entity_type == ENTITY_ITEM:
                # 反向連結：教材 / 測驗已於本迴圈稍早建好（`APPLY_ORDER` 保證）。
                #
                # 🔴 **沒有子節點時不寫這兩欄**，而不是寫 `None`。孤兒項目（教材已軟刪、
                # 項目還在）在 `load_live_tree` 會缺教材節點，寫 `None` 會讓它違反
                # `CK_ET_ITEM_TYPE_TARGET` ——把今天可容忍的狀態變成崩潰。保留既有連結
                # 等同維持現狀，而那門課本來就會被 `BLOCK_ITEM_NO_TITLE` 擋住發布。
                #
                # 新增的項目若少了子節點，這兩欄維持預設 `NULL`，同一條 CHECK 會當場
                # 擋下——那是該響的警報，因為編輯端不可能產生那種樹。
                for child_type, attr in ((ENTITY_MATERIAL, "material_id"), (ENTITY_QUIZ, "quiz_id")):
                    child_live_id = reverse_child.get((node.stage_id, child_type))
                    if child_live_id is not None:
                        values[attr] = child_live_id

            live_id = await _write(db, spec, node, values, operator=operator, now=now)
            live_id_by_stage[node.stage_id] = live_id
            if spec.link == LINK_PARENT_FK and node.parent_stage_id is not None:
                reverse_child[(node.parent_stage_id, spec.entity_type)] = live_id


async def _write(
    db: AsyncSession,
    spec: Any,
    node: StageNode,
    values: dict[str, Any],
    *,
    operator: OperatorInfo,
    now: Any,
) -> int:
    """更新既有列或插入新列，回傳活表 id。"""
    if node.source_id is not None:
        await db.execute(
            update(spec.model)
            .where(getattr(spec.model, spec.pk) == node.source_id, spec.model.deleted == 0)
            .values(**values, updated_user=operator.user_id, updated_date=now)
        )
        return node.source_id

    row = spec.model(**values, created_user=operator.user_id, created_date=now, deleted=0)
    db.add(row)
    # 子層與反向連結要拿它的 id，而那是 Identity 欄位，不 flush 取不到。
    await db.flush()
    return getattr(row, spec.pk)
