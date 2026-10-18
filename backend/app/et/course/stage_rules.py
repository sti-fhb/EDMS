"""已發布課程「編輯暫存區」的純業務規則（#631）。

**完全不碰 DB**：I/O（讀暫存列、讀課程基本資料與受訓對象數）由 service 做完後，把一串
`StageNode` 餵進來。

## 這個模組存在的唯一理由

「更新」要檢核的是**即將生效的內容**，而那份內容在暫存區、不在活表。只要能把暫存樹
組成與 `publish_repository.snapshot()` 相同的 `CourseSnapshot`，十項 `BLOCK_*` 就能
**一行不改地重用**——`publish_rules.py` 因此未被本 issue 觸及。

⛔ 不得在這裡另寫一份檢核。四個動作（發布／關閉／再開課／更新）共用同一組規則，
各自複製一份必然分岔，而分岔的症狀是「更新擋下了發布會放行的課程」——沒有錯誤訊息。

## 為什麼暫存區存的是「完整的目標內容樹」而不是差異

教師對已發布課程做第一次編輯時，活表的內容樹整棵複製進暫存區；之後所有編輯只動暫存。
好處是**編輯端讀取就是直接讀暫存**，不需要把差異疊加回活表再組出「編輯中的樣子」——
疊加邏輯會散落在 12 個讀取端點，而漏掉一處的症狀是教師看不到自己剛做的編輯。

## 識別碼一律是 `STAGE_ID`

`PublishBlocker.target_id` 是給前端定位到畫面區塊用的。編輯頁讀的是暫存樹，畫面上每個
區塊帶的就是 `stage_id`；若回 `source_id`，新增的內容（還沒有活表 id）無從定位，而既有
內容又會回一個畫面上不存在的號碼。

⚠️ 兩個號碼空間**會重疊**（都是 BIGINT identity），所以回錯了不會爆、只會標錯區塊。
`test_識別碼一律用_stage_id_而非_source_id` 是唯一會發現的地方。
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from app.et.course.publish_rules import ChapterSummary, CourseSnapshot, ItemSummary, QuizSummary

# ── 實體型別（`ET_COURSE_CONTENT_STAGE.ENTITY_TYPE`）────────────────────────────
#
# 11 張內容表各一種。⚠️ 新增型別時 `stage_entities.py` 的對照表要一起補，否則該型別
# 會在 seed 與套用時被靜默略過——那是「教師編了但更新沒生效」，不會有任何錯誤訊息。
ENTITY_CHAPTER: Final = "CHAPTER"
ENTITY_ITEM: Final = "ITEM"
ENTITY_MATERIAL: Final = "MATERIAL"
ENTITY_MATERIAL_VIDEO: Final = "MATERIAL_VIDEO"
ENTITY_MATERIAL_DOC: Final = "MATERIAL_DOC"
ENTITY_QUIZ: Final = "QUIZ"
ENTITY_QUESTION: Final = "QUESTION"
ENTITY_OPTION: Final = "OPTION"
ENTITY_SURVEY: Final = "SURVEY"
ENTITY_SURVEY_QUESTION: Final = "SURVEY_QUESTION"
ENTITY_SURVEY_OPTION: Final = "SURVEY_OPTION"

#: 「本次編輯要求重測」的意圖，寄在 `QUIZ` 暫存節點的 payload 上（#361 × #631）。
#:
#: 🔴 **刻意不是 `ET_QUIZ` 的欄位名**——`stage_apply._upsert` 只寫
#: `payload_fields(spec)` 列出的 key，非欄位的旗標因此會被自動忽略、不會進活表。
#: ⛔ 不要把它改成與欄位同名，那會讓它被當成內容寫進 `ET_QUIZ`。
#:
#: 生命週期與暫存工作階段一致：放棄編輯（`discard`）一起消失、套用完隨 `clear` 清掉。
#: 2026-10-17 使用者裁示「按更新時才生效」——理由見 `quiz/service._stage_require_retest`。
RETEST_PAYLOAD_KEY: Final = "__require_retest"

#: 🔴 旗標與欄位名相撞會讓它被當成內容寫進活表。由 `test_重測旗標不得與_ET_QUIZ_的欄位同名`
#: 在測試裡實際比對 `payload_fields(SPEC_BY_TYPE[ENTITY_QUIZ])`，不靠人記得
#: （2026-10-18 code review 建議）。


@dataclass(frozen=True)
class StageNode:
    """暫存區的一列——某個內容實體在「即將生效的版本」裡的樣子。

    Attributes:
        stage_id: 暫存列 PK。**對外的識別碼一律用它**（見模組 docstring）。
        entity_type: 本模組的 `ENTITY_*` 之一。
        source_id: 對應的活表 PK；`None` ＝ 這是新增的、活表還沒有。
        parent_stage_id: 父層暫存列；章節與問卷掛在課程下，故為 `None`。
        sort_order: 同層排序。
        payload: 該實體的欄位值。
        version: **暫存列自己的**樂觀鎖（#631 PR 2）。與活表列的 `VERSION` 是兩回事
            ——初值 seed 時承接自活表，此後各自遞增。編輯頁回傳給前端的是這一個。
    """

    stage_id: int
    entity_type: str
    source_id: int | None
    parent_stage_id: int | None
    sort_order: int
    payload: Mapping[str, Any]
    version: int = 0


def _children(nodes: Sequence[StageNode], parent_stage_id: int, entity_type: str) -> list[StageNode]:
    """某個節點底下指定型別的子節點，依 `sort_order` 排序。"""
    return sorted(
        (n for n in nodes if n.parent_stage_id == parent_stage_id and n.entity_type == entity_type),
        key=lambda n: (n.sort_order, n.stage_id),
    )


def _roots(nodes: Sequence[StageNode], entity_type: str) -> list[StageNode]:
    """掛在課程下（無父節點）的指定型別節點，依 `sort_order` 排序。"""
    return sorted(
        (n for n in nodes if n.parent_stage_id is None and n.entity_type == entity_type),
        key=lambda n: (n.sort_order, n.stage_id),
    )


def _item_title(nodes: Sequence[StageNode], item: StageNode) -> str:
    """項目的顯示名稱。

    ⚠️ **名稱不在項目本身**——項目不存名稱（避免教材改名後不同步），依型別落在其
    教材子節點的 `material_name` 或測驗子節點的 `quiz_name`。活表那側是以
    `coalesce(教材名, 測驗名, "")` 取得。

    🔴 兩者都沒有時回**空字串而非 `None`**：`evaluate_publish` 會對 `title` 呼叫
    `.strip()`，`None` 會讓檢核 500。這與活表那側 `coalesce` 的第三個參數同理——
    那裡的 docstring 寫明它「不是防禦性冗餘」。
    """
    for entity_type, key in ((ENTITY_MATERIAL, "material_name"), (ENTITY_QUIZ, "quiz_name")):
        children = _children(nodes, item.stage_id, entity_type)
        if children:
            return str(children[0].payload.get(key) or "")
    return ""


def _survey_question_count(nodes: Sequence[StageNode]) -> int | None:
    """問卷題數；**沒有問卷時回 `None` 而非 0**。

    0 是「有問卷但一題都沒有」（要擋），`None` 是「沒有問卷」（選配，AC 23，不擋）。
    兩者共用同一個值會讓每一門沒建問卷的課程都被擋住更新。

    **已停用的問卷視同沒有問卷**（#611）：停用後學員端不顯示入口，有沒有題目都影響不到
    學員。⚠️ 活表那側是以查詢條件 `EtSurvey.is_active.is_(True)` 達成，**規則名在該檔
    零命中**；兩邊要同時改，否則「更新」會擋下「發布」放行的課程。
    """
    active = [s for s in _roots(nodes, ENTITY_SURVEY) if s.payload.get("is_active", True)]
    if not active:
        return None
    return len(_children(nodes, active[0].stage_id, ENTITY_SURVEY_QUESTION))


def to_course_snapshot(
    nodes: Sequence[StageNode],
    *,
    status: str,
    open_start_at: datetime | None,
    open_end_at: datetime | None,
    tag_count: int,
) -> CourseSnapshot:
    """把暫存內容樹組成發布檢核所需的 `CourseSnapshot`。

    Args:
        nodes: 該課程暫存區的全部列（扁平，彼此以 `parent_stage_id` 串接）。
        status: 課程狀態——**取自活表**，不在暫存區（基本資料走「儲存」不走「更新」）。
        open_start_at: 同上。
        open_end_at: 同上。
        tag_count: 受訓對象組數——同樣取自活表（`ET_COURSE_TAG` 不是內容、不版本化）。

    Returns:
        與 `publish_repository.snapshot()` 同形的快照，可直接餵給 `evaluate_publish`。
    """
    chapters = _roots(nodes, ENTITY_CHAPTER)
    chapter_summaries = tuple(
        ChapterSummary(chapter_id=c.stage_id, item_count=len(_children(nodes, c.stage_id, ENTITY_ITEM)))
        for c in chapters
    )
    # 依**章節順序 → 項目順序**展開，使缺漏清單的順序與教師畫面上的一致。
    items = [item for c in chapters for item in _children(nodes, c.stage_id, ENTITY_ITEM)]
    quizzes = [q for item in items for q in _children(nodes, item.stage_id, ENTITY_QUIZ)]
    materials = [m for item in items for m in _children(nodes, item.stage_id, ENTITY_MATERIAL)]

    return CourseSnapshot(
        status=status,
        open_start_at=open_start_at,
        open_end_at=open_end_at,
        tag_count=tag_count,
        chapters=chapter_summaries,
        material_count=len(materials),
        items=tuple(ItemSummary(item_id=i.stage_id, title=_item_title(nodes, i)) for i in items),
        quizzes=tuple(
            QuizSummary(
                quiz_id=q.stage_id,
                question_count=len(_children(nodes, q.stage_id, ENTITY_QUESTION)),
                points_total=sum(
                    int(n.payload.get("points") or 0) for n in _children(nodes, q.stage_id, ENTITY_QUESTION)
                ),
            )
            for q in quizzes
        ),
        doc_ids=frozenset(
            str(d.payload["doc_id"])
            for m in materials
            for d in _children(nodes, m.stage_id, ENTITY_MATERIAL_DOC)
            if d.payload.get("doc_id")
        ),
        survey_question_count=_survey_question_count(nodes),
    )
