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

## 問卷凍結的 TOCTOU 由 `_ensure_survey_not_frozen` 擋下

`survey/service._require_editable` 問的是「**現在**有沒有填答」，而暫存模式把「檢查」與
「寫活表」拉開成兩個時點。SA 裁示 Q2 ②「**仍凍結**」：套用前重問一次。細節與範圍見該
函式 docstring——⛔ 它與 `survey/rules.ensure_editable` 是同一條界線，兩邊要同時改。

## ⚠️ 一項已知限制（2026-10-14 code review 提出，刻意未修）

### 項目的教材 / 測驗被換成新的一份時，舊的那份會變成孤兒

`_DELETED_WITH_ITEM` 讓教材與測驗不單獨刪——前提是「項目型別不可變、一項目恆對一份
教材」，而那個前提由**編輯端**維持，本模組不保證。若有人造出「項目留著、但其教材子節點
換成另一個 `SOURCE_ID`」的暫存樹，舊的教材列不會被任何人刪掉。

後果是一列到不了的活表資料（不影響學員、不影響檢核），而編輯端不可能產生那種樹，故
本 PR 不處理。⚠️ 若日後支援「一個教材被多個項目重用」，刪除策略要整個重想，屆時
`test_刪掉整個項目時教材一起被刪` 會紅——那是該響的警報。
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.catalog.models import EtCourseTag
from app.et.common.html_sanitize import sanitize_material_html
from app.et.course.models import EtCourse
from app.et.course.repository import EtChapterRepository, EtItemRepository
from app.et.course.stage_entities import APPLY_ORDER, LINK_CHILD_FK, LINK_PARENT_FK, SPEC_BY_TYPE, payload_fields
from app.et.course.stage_live_tree import LiveNode, load_live_tree
from app.et.course.stage_rules import (
    ENTITY_CHAPTER,
    ENTITY_COURSE,
    ENTITY_COURSE_TAG,
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
    RETEST_PAYLOAD_KEY,
    StageNode,
)
from app.et.material.repository import EtMaterialRepository
from app.et.progress.repository import EtProgressRepository
from app.et.quiz.models import EtOption
from app.et.quiz.repository import EtQuizRepository
from app.et.survey.models import EtSurveyOption
from app.et.survey.repository import EtSurveyRepository

logger = logging.getLogger(__name__)

#: 隨所屬項目一起刪，不單獨處理（見模組 docstring）。
_DELETED_WITH_ITEM = frozenset({ENTITY_MATERIAL, ENTITY_QUIZ})

#: 🔴 ⛔ **永遠不刪的型別**（#720）。
#:
#: `_delete_removed` 以「活表有、暫存沒有 ⇒ 教師刪了它」判定，而那個推論對**課程本體**
#: 不成立：刪課程是另一條路徑（`service.delete_draft`，草稿專用），不經暫存區。
#:
#: 若課程落進 `_DELETERS`，任何讓課程節點從暫存樹消失的情形——例如「只放棄問卷」那支
#: 寫錯了範圍、或 seed 漏搬——都會把**整門課軟刪**，連帶它底下的一切。而那是不可逆的。
#:
#: ⚠️ 受訓對象**不在**這裡：已關閉課程本來就可以自由增刪配對（#586），它是可刪的。
#: 由 `test_課程本體永遠不可被刪` 與 `test_受訓對象可以被刪` 成對釘住。
_NEVER_DELETED = frozenset({ENTITY_COURSE})


@dataclass(frozen=True)
class ApplyStats:
    """一次套用的結果——供稽核描述與排程 log。

    `removed` 只記**型別與筆數**，不記內容也不記學員識別（`sti-backend-logging` 禁寫清單）。
    """

    #: 各型別被軟刪的活表列數（只列有刪到的）。
    removed: dict[str, int]

    @property
    def removed_total(self) -> int:
        return sum(self.removed.values())


async def apply_stage(
    db: AsyncSession, *, course: EtCourse, nodes: Sequence[StageNode], operator: OperatorInfo
) -> ApplyStats:
    """把暫存樹套用到活表。

    Args:
        db: 交易由呼叫端管理——本函式**不 commit**，失敗時整批回滾（AC 2 的「未通過
            時不得部分生效」靠的就是這件事）。
        course: 目標課程（活表列）。
        nodes: 該課程的整棵暫存樹。
        operator: 稽核欄位用。

    Returns:
        刪除統計，供呼叫端寫進稽核描述。

    Raises:
        AppError: 500 `ET_STAGE_001` 暫存樹結構不合法；409 `ET_LOCK_001` 期間活表被
            其他操作改動。
    """
    # 🔴 **活表樹只載入一次**，驗證與刪除共用。
    #
    # 刪除階段的 cascade 會連帶刪掉教材 / 測驗，中途重讀會看到那些列而重複處理；
    # 而驗證要用它確認「每個 `SOURCE_ID` 真的屬於本課程」——兩者必須看同一份快照。
    live = await load_live_tree(db, course.course_id)
    _validate_tree(nodes, live=live)
    await _ensure_survey_not_frozen(db, nodes=nodes, live=live)

    staged_sources: dict[str, set[int]] = {}
    for node in nodes:
        if node.source_id is not None:
            staged_sources.setdefault(node.entity_type, set()).add(node.source_id)

    stats = await _delete_removed(db, live=live, staged_sources=staged_sources, operator=operator)
    await _park_sort_orders(db, nodes=nodes, operator=operator)
    live_id_by_stage = await _upsert(db, course=course, nodes=nodes, operator=operator)

    # 🔴 **完課戳記只在整批套用完成後蓋一次**（`_DELETERS` 一律帶 `stamp=False`）。
    #
    # 刪除階段蓋章會用中間狀態判定：學員 2/3、教師同一批刪掉未完成的那項**又新增一項**
    # ⇒ 階段 1 結束時是 2/2 被蓋章，階段 3 之後其實是 2/3、沒完課。而 `COMPLETED_AT`
    # 只寫一次、回退不清除，那個時間戳會一直停在一個他沒完課的時點。
    await EtProgressRepository().stamp_completed_at(db, course_id=course.course_id, operator=operator)
    await _require_retest_for_flagged(
        db, course=course, nodes=nodes, live_id_by_stage=live_id_by_stage, operator=operator
    )
    return stats


async def _require_retest_for_flagged(
    db: AsyncSession, *, course: EtCourse, nodes: Sequence[StageNode], live_id_by_stage: dict[int, int], operator
) -> None:
    """把編輯期間勾選的「要求重測」在**此刻**執行（#361 × #631）。

    教師在編輯中勾選時只是**記下意圖**（`RETEST_PAYLOAD_KEY` 寄在 QUIZ 暫存節點上），
    真正把學員退回未通過延到這裡——2026-10-17 使用者裁示。

    🔴 理由：在編輯當下執行的話，學員被退回的那一刻**新題目還沒生效**，他去重考考的是
    剛剛才通過的同一份舊題。副作用必須跟著「學員看得到了」一起發生，與 #303 的通知改到
    「更新」當下寄是同一個道理。

    ⚠️ 排在 `_upsert` **之後**：重測信裡帶測驗名稱，而那個名稱可能正是本次改的。
    ⚠️ 也排在 `stamp_completed_at` 之後：重測會清掉完成旗標，順序顛倒會讓剛蓋的章又被清。
    ⚠️ 新增的測驗（`source_id` 為 None）此刻才有活表 id，故一律由 `live_id_by_stage` 取。

    ## ⚠️ 已知限制：扇出沒有上界，且整批都在同一個交易裡

    （2026-10-18 security review H-2，刻意不在本 PR 修。）

    一次「更新」可能同時觸發 M 個測驗的重測，每個再對 N 位作答過的學員（#709 起不限已通過）寫入重置基準、
    清完成旗標、排一封信 ⇒ **N × M 列寫入**全部落在按下「更新」的那一個請求裡。

    今天的母體擋得住：教師改測驗要逐支勾選，而一門課的在籍學員是以班為單位。但這裡
    沒有任何上界，所以它是「**目前的資料量讓它看不出來**」，不是「設計上不會發生」。

    ⛔ 若要處理，正解是把寄信那一段移出本交易（排程撿 `PENDING`），**不是**在這裡切批次
    ——切批次會讓一半的學員被退回、另一半沒有，而「更新」對教師是一個原子動作。
    """
    flagged = [n for n in nodes if n.entity_type == ENTITY_QUIZ and n.payload.get(RETEST_PAYLOAD_KEY)]
    if not flagged:
        return
    # 延後匯入：`quiz.service` 會回頭匯入 `course.stage_writer`，放在模組層雖然目前
    # 不成環，但這條相依是「套用時才需要」的，留在函式內比較不會被下一個人動壞。
    from app.et.quiz.service import EtQuizService

    service = EtQuizService()
    for node in flagged:
        quiz_id = live_id_by_stage.get(node.stage_id)
        if quiz_id is None:  # pragma: no cover - `_upsert` 必定已填
            continue
        affected = await service.require_retest_now(db, quiz_id=quiz_id, course_id=course.course_id, operator=operator)
        if affected:
            logger.info("ET 更新套用：要求重測 quiz_id=%s 影響 %s 位學員", quiz_id, affected)


def _validate_tree(nodes: Sequence[StageNode], *, live: Sequence[LiveNode]) -> None:
    """套用前的結構守門——**動活表之前就擋下，而不是寫一半**。

    四道不變式，每一道漏掉的後果都是靜默的：

    | # | 不變式 | 漏掉會怎樣 |
    |---|---|---|
    | 1 | `ENTITY_TYPE` 必須在對照表裡 | 該節點被三個階段全部略過 ⇒ 教師編了、按更新沒生效，**連錯誤都沒有** |
    | 2 | `PARENT_STAGE_ID` 指得到 | `KeyError: <某個數字>`，看不出是哪棵樹、哪個節點 |
    | 3 | 父層型別相符、且「該不該有父層」一致 | 🔴 項目若無父層會拿到
      `chapter_id = course_id`——11 張表的 identity **號碼空間重疊**，那個 id 通常真的
      存在，於是項目被靜默塞進**別門課**的章節 |
    | 4 | `SOURCE_ID` 必須屬於**本課程**的活表樹 | 🔴 覆寫他人課程的章節 / 題目，且 `_upsert` 會把它們改掛到本課程底下 |

    ⚠️ 第 3、4 道在本 PR 還不可達（暫存列目前只由 `seed_from_live` 從本課程活表推導），
    它們是**為 PR 2 預留的**——編輯端一旦讓前端指定 `stage_id` / `source_id`，那兩條路
    就活了。⛔ 不要因為「現在還到不了」而拿掉：補在這裡是一道結構守門，補在 12 個編輯
    端點各一次則會漏。

    ⚠️ 本函式**不驗**「每個項目都有教材或測驗子節點」——孤兒項目（教材已軟刪、項目
    還在）在 `load_live_tree` 就會缺那個子節點，而那是今天可容忍的既有狀態
    （`BLOCK_ITEM_NO_TITLE` 會擋住它發布）。驗了會讓既有資料無法更新。
    """
    unknown = sorted({n.entity_type for n in nodes if n.entity_type not in SPEC_BY_TYPE})
    if unknown:
        _reject(f"暫存樹含未知的 ENTITY_TYPE：{unknown}")

    by_id = {n.stage_id: n for n in nodes}
    dangling = [n for n in nodes if n.parent_stage_id is not None and n.parent_stage_id not in by_id]
    if dangling:
        detail = ", ".join(f"STAGE_ID={n.stage_id}->{n.parent_stage_id}" for n in dangling[:5])
        _reject(f"暫存樹的父參照斷鏈（共 {len(dangling)} 筆）：{detail}")

    for node in nodes:
        expected = SPEC_BY_TYPE[node.entity_type].parent_entity
        if (expected is None) != (node.parent_stage_id is None):
            _reject(
                f"STAGE_ID={node.stage_id}（{node.entity_type}）的父層有無與對照表不符：預期 {expected or '掛在課程下'}"
            )
        if node.parent_stage_id is not None:
            actual = by_id[node.parent_stage_id].entity_type
            if actual != expected:
                _reject(f"STAGE_ID={node.stage_id}（{node.entity_type}）的父層型別為 {actual}，預期 {expected}")

    live_ids: dict[str, set[int]] = {}
    for node in live:
        live_ids.setdefault(node.entity_type, set()).add(node.key[1])
    foreign = [n for n in nodes if n.source_id is not None and n.source_id not in live_ids.get(n.entity_type, set())]
    if foreign:
        detail = ", ".join(f"{n.entity_type}#{n.source_id}" for n in foreign[:5])
        _reject(f"暫存列指向不屬於本課程的活表資料（共 {len(foreign)} 筆）：{detail}")


def _structure_sort_key(node: Any) -> tuple:
    """`(sort_order, 有沒有活表 id, 活表 id)`——⚠️ 不可直接寫 `(n[1], n[0])`。

    每一項的第 0 格是 `SOURCE_ID`，而**本次編輯新增的節點那一格是 `None`**。兩筆
    `sort_order` 相同時 `sorted` 才會去比第二格，屆時 `None < int` 直接 `TypeError`
    ⇒ 整支「更新」回 500（2026-10-18 security review L-7）。

    `sort_order` 本該同層唯一，但那由編輯端維持、本模組不保證；而這裡是**凍結守門**，
    它崩潰的後果是教師看到 500 而非 422，既修不了也看不懂。
    """
    return (node[1], node[0] is not None, node[0] or 0)


def _survey_structure(nodes: Sequence[Any], *, survey_key: Any, child_of: Any) -> tuple:
    """問卷的**題目與選項結構**，供兩側比對。

    刻意**不含**問卷名稱與 `IS_ACTIVE`——凍結不涵蓋它們（`ET_SURVEY_003` 的說明：
    AC 21 明訂凍結後教師僅可停用問卷，連停用都擋掉會使凍結後無路可走）。
    """
    questions = sorted(child_of(nodes, survey_key, ENTITY_SURVEY_QUESTION), key=_structure_sort_key)
    return tuple(
        (
            qid,
            sort_order,
            stem,
            qtype,
            tuple(sorted(child_of(nodes, qkey, ENTITY_SURVEY_OPTION), key=_structure_sort_key)),
        )
        for qid, sort_order, stem, qtype, qkey in questions
    )


async def _ensure_survey_not_frozen(db: AsyncSession, *, nodes: Sequence[StageNode], live: Sequence[LiveNode]) -> None:
    """已有填答的問卷，其題目與選項不得被「更新」改掉（#631 SA Q2 ② 裁示「仍凍結」）。

    ## 為何這道守門非補不可

    `survey/service._require_editable` 是題目與選項**所有寫入路徑**的共用入口，它問的是
    「**現在**有沒有填答」。今天那個「現在」等同於寫入當下，因為檢查與寫入在同一個請求裡。

    #631 把兩者拉開了：教師在 T1 編輯（當時沒填答 ⇒ 合法放行、寫進暫存區），學員在 T2
    填答，教師在 T3 按「更新」才真的寫活表。T1 那次檢查**完全合法**，但它授權的寫入延到
    T3 才發生，而那時前提已不成立——`ET_SURVEY_RESPONSE_D.SQ_ID` 會指向一個題幹已被改寫、
    或已被軟刪的題目。這就是 TOCTOU（檢查時點 ≠ 使用時點）。

    ⭐ **測驗沒有這個問題**：它用的是相反的設計——`ET_QUIZ_ATTEMPT_D` 在 `attempt.start`
    當下就把題幹 / 選項 / 配分快照起來，不需要讀 `ET_QUESTION`。問卷只存了一個指標。

    ## 擋住的範圍

    題目與選項的新增 / 修改 / 刪除 / 重排。**不擋**問卷名稱與 `IS_ACTIVE`——與
    `survey/rules.ensure_editable` 同一條界線，兩邊要同時改。

    ## 為何不放進 `evaluate_publish`

    那組規則由發布 / 關閉 / 再開課 / 更新四個動作共用。本條只對「更新」成立：再開課的
    課程可能早有填答，但再開課**不會改動題目**，放進共用規則會把它一併擋死。

    Raises:
        AppError: 422 `ET_SURVEY_003`（與教師在編輯頁看到的同一碼、同一句話）。
    """
    live_survey = next((n for n in live if n.entity_type == ENTITY_SURVEY), None)
    if live_survey is None:
        return
    survey_id = live_survey.key[1]
    if not await EtSurveyRepository().has_responses(db, survey_id):
        return

    def staged_children(_nodes, parent_stage_id, entity_type):
        return [
            (n.source_id, n.sort_order, n.payload.get("stem"), n.payload.get("question_type"), n.stage_id)
            if entity_type == ENTITY_SURVEY_QUESTION
            else (n.source_id, n.sort_order, n.payload.get("option_text"))
            for n in _nodes
            if n.parent_stage_id == parent_stage_id and n.entity_type == entity_type
        ]

    def live_children(_nodes, parent_key, entity_type):
        return [
            (n.key[1], n.sort_order, n.row.stem, n.row.question_type, n.key)
            if entity_type == ENTITY_SURVEY_QUESTION
            else (n.key[1], n.sort_order, n.row.option_text)
            for n in _nodes
            if n.parent_key == parent_key and n.entity_type == entity_type
        ]

    staged_survey = next((n for n in nodes if n.entity_type == ENTITY_SURVEY), None)
    staged = (
        ()
        if staged_survey is None
        else _survey_structure(nodes, survey_key=staged_survey.stage_id, child_of=staged_children)
    )
    current = _survey_structure(live, survey_key=live_survey.key, child_of=live_children)
    if staged != current:
        raise AppError(
            status_code=422,
            detail="已有學員填答，題目與選項不可修改",
            error_code="ET_SURVEY_003",
        )


#: payload 裡需要在寫入活表前重跑消毒的欄位 → 消毒函式。
#:
#: 🔴 **這是一道「不依賴下一個人記得」的防線**（2026-10-16 security review H-2）。
#:
#: 全專案唯一的 HTML 消毒長在 `material/service.update`（`sanitize_material_html`），而
#: `_upsert` 把 payload **直接餵進 model**、完全不經過任何 service 層。今天不可利用：
#: `description_html` 只有兩個入口，一是 `seed_from_live`（抄的是已消毒的活表值），二是
#: `add_item` 的暫存分支寫死 `None`。
#:
#: ⚠️ 但只要有人照 `add_item` 的形狀寫出 `payload={"description_html": req.description_html}`，
#: 未消毒的 HTML 就會一路進 `ET_MATERIAL.DESCRIPTION_HTML`，再由 `ContentPane.tsx` 以
#: `dangerouslySetInnerHTML` 渲染給**每一位在籍學員**——而那行程式碼會長得跟現有的
#: 一模一樣，review 時看不出差別。
#:
#: ⛔ 不要因為「呼叫端已經消毒過了」就拿掉：消毒是冪等的，重跑一次的成本遠低於漏掉一次。
_RESANITIZE: Final[dict[str, Any]] = {"description_html": sanitize_material_html}


def _resanitize(values: dict[str, Any]) -> None:
    """對 payload 中需要消毒的欄位重跑一次消毒（就地改）。見 `_RESANITIZE`。"""
    for field, sanitize in _RESANITIZE.items():
        if values.get(field) is not None:
            values[field] = sanitize(values[field])


def _reject(detail: str) -> None:
    """結構不合法一律 500 `ET_STAGE_001`。

    是 500 不是 4xx：教師沒有做錯任何事，是暫存區的結構壞了。

    🔴 **診斷細節只進 log，回應一律固定文案**。本函式原本的 docstring 寫著
    「`app_error_handler` 不會把 detail 回給前端」——**那是假的**（2026-10-16 security
    review M-2 查出）：`main.py` 的 `app_error_handler` 對**所有**狀態碼（含 500）都把
    `exc.detail` 原樣放進回應的 `error_message`。而這幾處的 detail 帶著 `SOURCE_ID`
    ——那正是使用者送進來的 path 參數，原樣回吐違反 `sti-error-codes`。

    ⚠️ 真正危險的不是這次洩漏的那幾個代理鍵，是**那句假的 docstring**：它會讓下一個人
    放心把更敏感的東西寫進 detail。
    """
    logger.error("ET 暫存樹結構不合法：%s", detail)
    raise AppError(
        status_code=500,
        detail="課程內容暫存資料異常，請重新載入後再試",
        error_code="ET_STAGE_001",
    )


async def _delete_removed(
    db: AsyncSession, *, live: Sequence[LiveNode], staged_sources: dict[str, set[int]], operator: OperatorInfo
) -> ApplyStats:
    """活表有而暫存沒有的 ⇒ 教師刪了它。

    🔴 活表樹由 `apply_stage` **一次載入後傳入，中途不重讀**：
    `EtItemRepository.soft_delete_with_cascade` 會連帶刪掉教材 / 測驗，重讀會看到那些
    被連帶刪掉的列而重複處理。同一份快照也供 `_validate_tree` 判斷歸屬。

    由葉往根刪（`APPLY_ORDER` 的反向），讓每一層的 cascade 都在其子層已處理完之後才跑。
    """
    live_ids: dict[str, list[int]] = {}
    for node in live:
        live_ids.setdefault(node.entity_type, []).append(node.key[1])

    removed: dict[str, int] = {}
    for spec in reversed(APPLY_ORDER):
        if spec.entity_type in _DELETED_WITH_ITEM or spec.entity_type in _NEVER_DELETED:
            continue
        staged = staged_sources.get(spec.entity_type, set())
        gone = [live_id for live_id in live_ids.get(spec.entity_type, []) if live_id not in staged]
        if gone:
            await _DELETERS[spec.entity_type](db, gone, operator)
            removed[spec.entity_type] = len(gone)

    if removed:
        # 🔴 這條路徑會連帶軟刪**學員的進度與作答紀錄**（見 `EtItemRepository` 的 cascade），
        # 而端點本身沒有 request body——事後只能靠這行與稽核描述還原「那一次更新刪了什麼」。
        # 只記型別與筆數，不記內容、不記學員識別（`sti-backend-logging` 禁寫清單）。
        logger.info("ET 更新套用：軟刪 %s", dict(sorted(removed.items())))
    return ApplyStats(removed=removed)


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
    ENTITY_CHAPTER: lambda db, ids, op: EtChapterRepository().soft_delete_with_cascade(db, ids, op, stamp=False),
    ENTITY_ITEM: lambda db, ids, op: EtItemRepository().soft_delete_with_cascade(db, ids, op, stamp=False),
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
    # 受訓對象（#720）。⚠️ 軟刪即可——`ET_COURSE_TAG` 只是課程與標籤的關聯，
    # 沒有任何學員資料掛在它下面（學員掛在 `ET_ENROLLMENT`，不隨配對移除而退出）。
    ENTITY_COURSE_TAG: lambda db, ids, op: _delete_options(
        db, EtCourseTag, SPEC_BY_TYPE[ENTITY_COURSE_TAG].pk, ids, op
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
) -> dict[int, int]:
    """依 `APPLY_ORDER` 逐型別寫入；回填 `STAGE_ID → 活表 id` 供子層與反向連結使用。"""
    now = utcnow()
    live_id_by_stage: dict[int, int] = {}
    # 反向連結（`ET_ITEM.MATERIAL_ID` / `QUIZ_ID`）：父層要用子層的活表 id。
    reverse_child: dict[tuple[int, str], int] = {}

    for spec in APPLY_ORDER:
        for node in [n for n in nodes if n.entity_type == spec.entity_type]:
            # 🔴 **只寫 payload 裡實際存在的 key**，缺的不碰。
            #
            # `payload_fields` 是推導的：日後內容表加欄位會自動納入，但**編輯到一半、
            # 尚未更新的既有暫存列**沒有那個 key。用 `.get()` 會把 `None` 明確寫進去
            # ——NOT NULL 欄位拋 IntegrityError、nullable 欄位（`TIME_LIMIT_MIN`、
            # `DESCRIPTION_HTML` 等）則**靜默清成 NULL**，教師看到的是「我填過的說明
            # 按更新就不見了」。缺 key 的正確語意是「這列產生時還沒有這個欄位」，
            # 保留活表當前值才對。
            #
            # 新增的列缺 key 時維持 model 預設；NOT NULL 且無預設者會當場拋錯，那是
            # 該響的警報——編輯端不可能產生那種列。
            values: dict[str, Any] = {f: node.payload[f] for f in payload_fields(spec) if f in node.payload}
            _resanitize(values)
            if hasattr(spec.model, "sort_order"):
                values["sort_order"] = node.sort_order
            if spec.link == LINK_CHILD_FK and spec.fk != spec.pk:
                # ⚠️ `spec.fk != spec.pk` 排除的是**課程本體**（#720）：它是樹根，所謂的
                # 「父層連結欄位」就是它自己的 `COURSE_ID`。寫進 SET 子句等於
                # `SET COURSE_ID = COURSE_ID`——今天因為 `Identity()` 是
                # `GENERATED BY DEFAULT` 而僥倖允許，改成 `always=True` 就會當場報
                # 「column can only be updated to DEFAULT」。主鍵本來就不該出現在 SET 裡。
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

    # 回傳對照表：套用後才知道新增節點的活表 id，而 `_require_retest_for_flagged`
    # 需要它才找得到「本次新增的測驗」對應到哪一列。
    return live_id_by_stage


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
        result = await db.execute(
            update(spec.model)
            .where(getattr(spec.model, spec.pk) == node.source_id, spec.model.deleted == 0)
            .values(**values, updated_user=operator.user_id, updated_date=now)
        )
        # 🔴 命中 0 列 ＝ 那個活表列已被別的路徑軟刪。不擋的話會**靜默**地把子節點
        # 寫成指向一個已刪除的父層——活表出現到不了的資料，而且沒有任何錯誤。
        if result.rowcount != 1:  # pragma: no cover - 由 `_validate_tree` 的歸屬守門保證不可達
            # 🔴 **這條目前到不了，刻意留著。**
            #
            # `_validate_tree` 已確保每個 `SOURCE_ID` 都在 `apply_stage` 開頭載入的活表樹
            # 裡（當時 `DELETED = 0`），而交易中途唯一的刪除是 `_delete_removed`，它只碰
            # **沒有被暫存**的列。兩者合起來保證此處必定命中 1 列。
            #
            # ⚠️ 留著是因為那個保證**依賴三件事同時成立**（歸屬守門、課程行鎖、單一交易）。
            # 任何一件日後被改掉，少了這道就會靜默地把子節點寫成指向已刪除的父層——
            # 活表出現到不了的資料，而且沒有任何錯誤。
            #
            # 409 而非 500：若真的發生，那是**競態**、教師沒做錯事，`ET_LOCK_001` 的既有
            # 語意（「資料已被其他使用者修改，請重新載入後再試」）正好就是要他做的事。
            #
            # ⚠️ detail 是**固定文案**：它會原樣成為回應的 `error_message`，而前端
            # `applyMut.onError` 會直接 toast 給教師看。代理鍵只進 log。
            logger.error(
                "ET 套用：暫存列指向的活表資料已不存在或已刪除 entity_type=%s source_id=%s rowcount=%s",
                node.entity_type,
                node.source_id,
                result.rowcount,
            )
            raise AppError(
                status_code=409,
                detail="內容已被其他裝置變更，請重新載入後再試",
                error_code="ET_LOCK_001",
            )
        return node.source_id

    row = spec.model(**values, created_user=operator.user_id, created_date=now, deleted=0)
    db.add(row)
    # 子層與反向連結要拿它的 id，而那是 Identity 欄位，不 flush 取不到。
    await db.flush()
    return getattr(row, spec.pk)
