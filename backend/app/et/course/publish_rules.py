"""ET 課程發布檢核之純業務規則（US3 / #204）。

**完全不碰 DB**：I/O（查課程結構、向 DM 問廢止狀態）由 service 做完後，把一份
`CourseSnapshot` 與 `obsolete_doc_ids` 餵進來。六項檢核的所有組合因此都能以 unit
test 涵蓋，不必為每種缺漏情境建一份真資料。

## 為何回缺漏清單而非布林

AC 26 要求「提示**具體缺漏項目**」。回布林就只能說「發布失敗」，教師得自己猜是哪裡
不合格；回單一原因則會讓他修一次、再被擋一次。故一次回**全部**缺漏。

## 六項檢核——其中一項不在 spec AC 24 內

AC 24 明列五項：至少 1 章節 + 1 教材、至少 1 個受訓單位標籤、起訖時間已填、
各測驗配分總和 = 100、無引用之廢止 DM 文件。

第六項「**每個測驗至少 1 題**」來自 `data-model.md` §ET_QUESTION 之業務規則
（「同 QUIZ_ID 下至少 1 題」），經 **SA 裁示（#204 Q3 → A）** 加入。

⚠️ **不要因為對照 AC 24 找不到就把它刪掉**。它的來源是 #203 的延後決策：教師是逐題
新增的，空殼測驗與第一題存檔之間必然存在 0 題的狀態，擋在儲存時等於無法建題，因此
延到發布時檢核。若移除這一項，那條業務規則將**沒有任何執行點**，一個 0 題的測驗會
隨課程發布出去，而該測驗仍是章節的解鎖條件之一（`ET-5`），學員會卡在一份空考卷前。

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
BLOCK_NO_MATERIAL: Final = "NO_MATERIAL"
BLOCK_NO_TAG: Final = "NO_TAG"
BLOCK_NO_SCHEDULE: Final = "NO_SCHEDULE"
BLOCK_QUIZ_POINTS: Final = "QUIZ_POINTS"
BLOCK_QUIZ_NO_QUESTION: Final = "QUIZ_NO_QUESTION"
BLOCK_OBSOLETE_DOC: Final = "OBSOLETE_DOC"

#: 各測驗配分總和之目標值（`data-model.md` §ET_QUIZ）。
REQUIRED_POINTS_TOTAL: Final = 100


@dataclass(frozen=True)
class QuizSummary:
    """發布檢核所需之單一測驗摘要。"""

    quiz_id: int
    question_count: int
    points_total: int


@dataclass(frozen=True)
class CourseSnapshot:
    """發布檢核所需之課程結構快照。

    **刻意不含問卷欄位**——AC 23 明訂問卷為選配、未建立不得阻擋發布。沒有欄位就不會
    有人不小心把它加進檢核。
    """

    status: str
    open_start_at: datetime | None
    open_end_at: datetime | None
    tag_count: int
    chapter_count: int
    material_count: int
    quizzes: tuple[QuizSummary, ...]
    doc_ids: frozenset[str]


@dataclass(frozen=True)
class PublishBlocker:
    """一條發布缺漏。

    Attributes:
        code: 供前端定位到對應區塊之代碼（見本模組 `BLOCK_*`）。
        message: **靜態**說明文案，不內插使用者輸入。
        target_id: 出問題的對象 ID（目前僅測驗用），無對應者為 `None`。
    """

    code: str
    message: str
    target_id: int | None = None


def evaluate_publish(snapshot: CourseSnapshot, *, obsolete_doc_ids: frozenset[str]) -> tuple[PublishBlocker, ...]:
    """跑完六項檢核，回傳全部缺漏（無缺漏則為空 tuple）。

    Args:
        snapshot: 課程結構快照。
        obsolete_doc_ids: 課程引用之 DM 文件中**已廢止**者之 `DOC_ID` 集合，
            由 service 經 `DmDocumentService.get_current_by_doc_id` 查妥後傳入。

    Returns:
        缺漏清單，順序固定為「課程層 → 測驗層 → 文件層」，使前端呈現順序穩定。
    """
    blockers: list[PublishBlocker] = []

    if snapshot.chapter_count < 1:
        blockers.append(PublishBlocker(BLOCK_NO_CHAPTER, "課程至少須有 1 個章節"))
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
