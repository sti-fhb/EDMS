"""ET 課程發布檢核之純業務規則（US3 / #204）。

**完全不碰 DB**：I/O（查課程結構、向 DM 問廢止狀態）由 service 做完後，把一份
`CourseSnapshot` 與 `obsolete_doc_ids` 餵進來。所有檢核的組合因此都能以 unit
test 涵蓋，不必為每種缺漏情境建一份真資料。

## 為何回缺漏清單而非布林

AC 26 要求「提示**具體缺漏項目**」。回布林就只能說「發布失敗」，教師得自己猜是哪裡
不合格；回單一原因則會讓他修一次、再被擋一次。故一次回**全部**缺漏。

## 九項檢核——其中四項不在 spec AC 24 內

AC 24 明列五項：至少 1 章節 + 1 教材、至少 1 個受訓單位標籤、起訖時間已填、
各測驗配分總和 = 100、無引用之廢止 DM 文件。

第六項「**每個測驗至少 1 題**」來自 `data-model.md` §ET_QUESTION 之業務規則
（「同 QUIZ_ID 下至少 1 題」），經 **SA 裁示（#204 Q3 → A）** 加入。其來源是 #203 的
延後決策：教師是逐題新增的，空殼測驗與第一題存檔之間必然存在 0 題的狀態，擋在儲存時
等於無法建題，因此延到發布時檢核。若移除這一項，那條業務規則將**沒有任何執行點**，
一個 0 題的測驗會隨課程發布出去，而該測驗仍是章節的解鎖條件之一（`ET-5`），學員會
卡在一份空考卷前。

第七項「**有問卷則至少 1 題**」為 2026-08-28 實機測試回饋新增。它與 AC 23
「未建立問卷不阻擋發布」**不衝突**——是「有才檢查」。一份 0 題的問卷對學員而言是個
打不開的空殼，與 0 題測驗同型。

第八項「**每個章節至少 1 份教材或測驗**」為 #358 第 3 項（2026-09-17 手測回饋）新增。

第九項「**教材與測驗須填寫名稱**」為 #384 新增。它補的是**建立**那一側——`ItemCreateReq`
允許名稱留空（刻意設計），而它自稱的防線「儲存時仍必填」擋不住「不按儲存」。

⚠️ **這四項都不在 AC 24 裡，而是實機測試才發現的——對照 AC 找不到是正常的，不要
因此刪掉。** 每一項的來源都寫在上面；它們共同的形狀是「AC 假設了某件事不會發生，
而實機上它會」。

## 訊息為何不內插測驗名稱

`PublishBlocker.message` 一律靜態，出問題的對象以 `target_id` 表達。測驗名稱是使用者
輸入，內插等於把它原樣吐回前端（對齊 `sti-error-codes`）；且教師端要顯示名稱時，
前端本來就有課程詳細可對照，不需後端再送一次。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from app.et.constants import COURSE_PUBLISHED

# ── 缺漏代碼（供前端定位到對應區塊）────────────────────────────────────────────
BLOCK_NO_CHAPTER: Final = "NO_CHAPTER"
BLOCK_CHAPTER_EMPTY: Final = "CHAPTER_EMPTY"
BLOCK_ITEM_NO_TITLE: Final = "ITEM_NO_TITLE"
BLOCK_NO_MATERIAL: Final = "NO_MATERIAL"
BLOCK_NO_TAG: Final = "NO_TAG"
BLOCK_NO_SCHEDULE: Final = "NO_SCHEDULE"
BLOCK_QUIZ_POINTS: Final = "QUIZ_POINTS"
BLOCK_QUIZ_NO_QUESTION: Final = "QUIZ_NO_QUESTION"
BLOCK_SURVEY_NO_QUESTION: Final = "SURVEY_NO_QUESTION"
BLOCK_OBSOLETE_DOC: Final = "OBSOLETE_DOC"

#: 各測驗配分總和之目標值（`data-model.md` §ET_QUIZ）。
REQUIRED_POINTS_TOTAL: Final = 100


@dataclass(frozen=True)
class ChapterSummary:
    """發布檢核所需之單一章節摘要（#358 第 3 項）。"""

    chapter_id: int
    #: 該章節底下未刪除的項目數（教材與測驗合計）。
    item_count: int


@dataclass(frozen=True)
class ItemSummary:
    """發布檢核所需之單一章節項目摘要（#384）。

    ⚠️ **名稱不存在 `ET_ITEM` 上**——`ITEM_TYPE` 決定它落在 `ET_MATERIAL.MATERIAL_NAME`
    還是 `ET_QUIZ.QUIZ_NAME`（項目本身不存名稱，避免教材改名後不同步）。快照由
    `publish_repository` 以 outer join + `coalesce` 取出，此處只收結果。

    此處刻意**不帶 `item_type`**：兩種型別的缺漏文案與處理方式相同（都是「去填名稱」），
    帶了也沒有呼叫端會用。
    """

    item_id: int
    #: 顯示名稱；空字串代表教師建立後從未填寫（`ItemCreateReq.title` 允許留空）。
    title: str


@dataclass(frozen=True)
class QuizSummary:
    """發布檢核所需之單一測驗摘要。"""

    quiz_id: int
    question_count: int
    points_total: int


@dataclass(frozen=True)
class CourseSnapshot:
    """發布檢核所需之課程結構快照。"""

    status: str
    open_start_at: datetime | None
    open_end_at: datetime | None
    tag_count: int
    #: 逐章節摘要。**章節數由本欄位導出**（見 `chapter_count`），不另存計數——
    #: 兩個欄位並存時遲早會出現「`chapter_count=3` 但 `chapters` 只有 1 筆」的組合，
    #: 而那種不一致在測試裡建得出來、在正式環境卻不會發生，等於讓測試驗了假資料。
    chapters: tuple[ChapterSummary, ...]
    material_count: int
    #: 逐項目摘要（#384），依教師畫面上的順序（章節 `SORT_ORDER` → 項目 `SORT_ORDER`）。
    #:
    #: ⚠️ **與 `chapters[].item_count` / `material_count` 是同一批項目的三個平行視圖**，
    #: 而上面 `chapters` 的註解正好警告過這種並存遲早會不一致。本次刻意維持最小變更：
    #: 三者同一交易內由同一批查詢組成，今天不會分歧。若日後要收斂，做法是讓本欄位帶
    #: `chapter_id` + `item_type`，另外兩個都改成由它導出（比照 `chapter_count`）。
    items: tuple[ItemSummary, ...]
    quizzes: tuple[QuizSummary, ...]
    doc_ids: frozenset[str]
    #: 問卷題數。**`None` = 沒有問卷**（選配，AC 23）；整數 = 有問卷且其題數。
    #:
    #: ⚠️ 「沒有問卷」不可寫成 `0`——0 是「有問卷但一題都沒有」，那要擋。兩者共用
    #: 同一個值會讓 AC 23 失效：每一門沒建問卷的課程都會被擋住發布。
    survey_question_count: int | None = None

    @property
    def chapter_count(self) -> int:
        """章節數——由 `chapters` 導出。"""
        return len(self.chapters)


@dataclass(frozen=True)
class PublishBlocker:
    """一條發布缺漏。

    Attributes:
        code: 供前端定位到對應區塊之代碼（見本模組 `BLOCK_*`）。
        message: **靜態**說明文案，不內插使用者輸入。
        target_id: 出問題的對象 ID，**語意依 `code` 而定**——測驗為 `QUIZ_ID`、空章節為
            `CHAPTER_ID`、未命名項目為 `ITEM_ID`；無對應者為 `None`。前端以
            `BLOCKER_TARGET_KIND`（`surveySchemas.ts`）對照，未登記的代碼一律不標名稱。
    """

    code: str
    message: str
    target_id: int | None = None


def evaluate_publish(snapshot: CourseSnapshot, *, obsolete_doc_ids: frozenset[str]) -> tuple[PublishBlocker, ...]:
    """跑完九項檢核，回傳全部缺漏（無缺漏則為空 tuple）。

    Args:
        snapshot: 課程結構快照。
        obsolete_doc_ids: 課程引用之 DM 文件中**已廢止**者之 `DOC_ID` 集合，
            由 service 經 `DmDocumentService.get_current_by_doc_id` 查妥後傳入。

    Returns:
        缺漏清單，順序固定為「課程層 → 章節層 → 項目層 → 測驗層 → 文件層」，
        使前端呈現順序穩定。
    """
    blockers: list[PublishBlocker] = []

    if snapshot.chapter_count < 1:
        blockers.append(PublishBlocker(BLOCK_NO_CHAPTER, "課程至少須有 1 個章節"))
    # 第八項（#358 第 3 項）：**逐章節**檢核，與上一行的全課程層是兩件事。
    #
    # `material_count` 是全課程的教材總數，只要任一章節有教材就通過——其餘章節可以
    # completely 空著。空章節對學員是一個點進去什麼都沒有的段落。
    #
    # ⚠️ 空章節**不會**讓學員卡住：`progress/rules.locked_item_ids` 明文把沒有項目的
    # 章節視為已完成（`all([])` 為 `True`），否則整門課的後半段會永久鎖死。完課率也
    # 不受影響（分子分母都以 `ET_ITEM` 計，空章節各貢獻 0）。所以這是「不該發布出去」
    # 而非「已發布的會出事」。
    for chapter in snapshot.chapters:
        if chapter.item_count < 1:
            blockers.append(PublishBlocker(BLOCK_CHAPTER_EMPTY, "章節至少須有 1 份教材或測驗", chapter.chapter_id))
    # 項目層（#384）：未命名的教材／測驗不得發布出去。
    #
    # 建立時名稱可留空是刻意設計（`ItemCreateReq` 之 docstring，2026-08-27 依實測回饋），
    # 而它自己指的防線「儲存時仍必填」**擋不住「不按儲存」**——教師新增項目時空殼已經
    # 在 DB 裡，直接關掉視窗就留下了。`unsavedNewItemId` 只在同一次視窗互動內有效。
    #
    # 🔴 判空用 `strip()` 而非 `not title`：今天三條寫入路徑都 strip 過（`ItemCreateReq`
    # `_strip_title`、`QuizUpdateReq._strip_required`、`MaterialUpdateReq._name_not_blank`），
    # 所以 DB 裡只可能是 `""`。但發布是最後一道防線，它的正確性不該依賴上游三個 schema
    # 永遠維持嚴格——任一個放寬，這裡是唯一還站著的那道。
    for item in snapshot.items:
        if not item.title.strip():
            blockers.append(PublishBlocker(BLOCK_ITEM_NO_TITLE, "教材與測驗須填寫名稱", item.item_id))
    if snapshot.material_count < 1:
        blockers.append(PublishBlocker(BLOCK_NO_MATERIAL, "課程至少須有 1 份教材"))
    if snapshot.tag_count < 1:
        blockers.append(PublishBlocker(BLOCK_NO_TAG, "課程至少須掛 1 個受訓單位標籤"))
    if snapshot.open_start_at is None or snapshot.open_end_at is None:
        # 起、訖任一未填只回一條——教師要補的是「閱課期間」這件事，拆成兩條會讓
        # 缺漏清單看起來比實際嚴重。
        blockers.append(PublishBlocker(BLOCK_NO_SCHEDULE, "課程起訖時間須填寫完整"))

    for quiz in snapshot.quizzes:
        if quiz.question_count < 1:
            # 0 題的測驗總分必然是 0，不再另報「配分不等於 100」——那只是噪音，
            # 教師要做的是先加題目，加完配分自然要重算。
            blockers.append(PublishBlocker(BLOCK_QUIZ_NO_QUESTION, "測驗至少須有 1 題", quiz.quiz_id))
        elif quiz.points_total != REQUIRED_POINTS_TOTAL:
            blockers.append(
                PublishBlocker(BLOCK_QUIZ_POINTS, f"測驗各題配分總和須等於 {REQUIRED_POINTS_TOTAL}", quiz.quiz_id)
            )

    # 有問卷才檢查——與 AC 23「未建立問卷不阻擋發布」不衝突。一份 0 題的問卷對學員
    # 而言是個打不開的空殼，與 0 題測驗同型。不需要 `target_id`：一門課程至多 1 份問卷。
    if snapshot.survey_question_count is not None and snapshot.survey_question_count < 1:
        blockers.append(PublishBlocker(BLOCK_SURVEY_NO_QUESTION, "課後問卷至少須有 1 題，或請停用該問卷"))

    if snapshot.doc_ids & obsolete_doc_ids:
        blockers.append(PublishBlocker(BLOCK_OBSOLETE_DOC, "請先移除已廢止文件之引用"))

    return tuple(blockers)


def is_visible_to_student(*, status: str, open_start_at: datetime | None, now: datetime) -> bool:
    """課程於學員端是否可見（AC 27 / FR-ET-US3-13）。

    條件為 `STATUS = PUBLISHED` 且 `now >= OPEN_START_AT`（`data-model.md` §ET_COURSE）。
    起始時間前對學員完全不顯示、不可進入；教師端不受此限（正常可見可編輯）。

    `open_start_at` 為 `None` 時視為**不可見**——已發布課程理論上必有起始時間（發布
    檢核擋掉了），但該欄位於 DB 為 NULLable，判定不假設上游一定對，空值取較安全的
    那一側。

    > 學員端課程清單本身屬 `ET-4`；本 issue 只交付判定函式，使兩處不會長出兩套規則。
    """
    if status != COURSE_PUBLISHED or open_start_at is None:
        return False
    return now >= open_start_at
