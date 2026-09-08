"""ET05 課後問卷填寫之純業務規則（US13 / #284）——學員端。

**完全不碰 DB**：入口四態導出、送出前守門、逐題作答驗證、明細列組裝四件事都能以純
函式表達，故全部以 unit test 涵蓋；integration 只驗接線、唯一約束與實際寫了幾列。

## 本模組與 `survey/rules.py` 是相反的兩個問題

`survey/` 是**教師端**，授權問「擁有權」、規則管的是題目怎麼建；本模組是**學員端**，
授權問「在籍」、規則管的是作答怎麼收。混在同一處遲早有人把 dependency 掛錯層，而
那種錯誤的表現是「學員能改問卷」或「學員不能填」——兩者都不會在寫測試時自然浮現
（測試會用有權限的帳號）。同一個理由見 #255 分開 `learning/` 與 `material/`、
#279 分開 `attempt/` 與 `quiz/`。

## 判定順序不可調換

`已填？` → `SUBMITTED`（**優先於課程狀態與問卷啟用狀態**）→ `無問卷 / 停用 / 未完課？`
→ `HIDDEN` → `課程非 PUBLISHED？` → `COURSE_CLOSED` → 否則 `FILLABLE`。

`SUBMITTED` 必須排第一：AC 11 要求課程關閉後已填者仍可回看，而 `spec.md`
Clarifications 亦明訂問卷停用只影響「尚未填寫者」。若課程狀態先判，關閉後學員會看不
到自己填過的內容——資料還在，只是消失在他眼前。
"""

from dataclasses import dataclass
from typing import Final

from app.core.exceptions import AppError
from app.et.constants import COURSE_CLOSED, COURSE_PUBLISHED, SURVEY_QUESTION_SINGLE

#: 文字答案上限（`ET_SURVEY_RESPONSE_D.ANSWER_TEXT` 為 `VARCHAR(150)`；FR-ET-US13-02
#: 明訂「至多 150 字，超過時 MUST 阻擋」）。
ANSWER_TEXT_MAX_LEN: Final = 150

# ── 入口四態 ──────────────────────────────────────────────────────────────────
#
# 以**單一狀態值**表達，不用多個布林旗標的組合。旗標組合會產生不可能的狀態
# （如「已送出且未完課且問卷已停用」該顯示什麼？），而前端得為每種組合各寫一條分支。
ENTRY_HIDDEN: Final = "HIDDEN"
ENTRY_FILLABLE: Final = "FILLABLE"
ENTRY_SUBMITTED: Final = "SUBMITTED"
ENTRY_COURSE_CLOSED: Final = "COURSE_CLOSED"

ALL_ENTRY_STATES: Final = frozenset({ENTRY_HIDDEN, ENTRY_FILLABLE, ENTRY_SUBMITTED, ENTRY_COURSE_CLOSED})


@dataclass(frozen=True)
class QuestionSpec:
    """驗證作答所需之單題規格（題型 + 該題的合法選項集合）。

    `option_ids` 是**該題自己的**選項——必須逐題比對，否則學員可送出別題的選項 id，
    讓 US9 的統計出現不屬於該題的選項（而那份統計沒有任何地方會察覺）。
    """

    sq_id: int
    question_type: str
    option_ids: frozenset[int]


@dataclass(frozen=True)
class AnswerDraft:
    """學員送出的單題作答（尚未驗證）。"""

    sq_id: int
    so_id: int | None = None
    answer_text: str | None = None


@dataclass(frozen=True)
class DetailRow:
    """待寫入 `ET_SURVEY_RESPONSE_D` 的一列。"""

    sq_id: int
    so_id: int | None
    answer_text: str | None


def derive_entry_state(*, survey_active: bool, completed: bool, already_submitted: bool, course_status: str) -> str:
    """側欄「填寫課後問卷」入口之狀態（AC 1 / AC 2 / AC 10 / AC 11）。

    Args:
        survey_active: 該課程有未刪除且 `IS_ACTIVE=true` 的問卷。**沒有問卷**與
            **問卷停用**在此合為 `False`——兩者對學員的結果相同（入口不出現），
            分開只會讓呼叫端多一個沒人用得上的區別。
        completed: 該學員已完課（所有未刪除項目皆完成）。
        already_submitted: 該學員已送出過填答。
        course_status: 課程當前狀態（`ET_COURSE_STATUS`）。

    Returns:
        `ENTRY_*` 四者之一。
    """
    if already_submitted:
        return ENTRY_SUBMITTED
    if not survey_active or not completed:
        return ENTRY_HIDDEN
    if course_status == COURSE_CLOSED:
        return ENTRY_COURSE_CLOSED
    if course_status != COURSE_PUBLISHED:
        # 草稿課程沒有學員（邀請碼發布時才產生），走到這裡只可能是資料異常。回
        # `HIDDEN` 而非 `COURSE_CLOSED`——後者的訊息是「等再開課」，對一門從未發布的
        # 課程是錯的指引。
        return ENTRY_HIDDEN
    return ENTRY_FILLABLE


def ensure_fillable(entry_state: str) -> None:
    """送出前的狀態守門。

    前端在 `FILLABLE` 以外的狀態都不會顯示送出鈕，故走到這裡的是**直接打 API 的人**
    或**多分頁**——後者是真實情境（開兩個分頁各按一次送出），第二次收到 409
    `ET_SURVEY_013` 是正確結果而非失敗，前端據此改為重載表單轉唯讀。

    Raises:
        AppError: 409 `ET_SURVEY_013` 已填寫過；409 `ET_SURVEY_014` 課程已關閉；
            403 `ET_SURVEY_012` 尚未完課（或問卷未啟用）。
    """
    if entry_state == ENTRY_FILLABLE:
        return
    if entry_state == ENTRY_SUBMITTED:
        raise AppError(status_code=409, detail="您已填寫過此問卷", error_code="ET_SURVEY_013")
    if entry_state == ENTRY_COURSE_CLOSED:
        raise AppError(status_code=409, detail="課程已關閉，無法填寫問卷", error_code="ET_SURVEY_014")
    # `HIDDEN` 涵蓋「未完課」與「問卷未啟用」兩種。不分兩碼——對學員而言下一步都是
    # 「先把課上完」，而問卷有沒有被停用是教師端的事，告知他反而只會讓他去問教師一件
    # 他無法處理的事。
    raise AppError(status_code=403, detail="尚未完課，無法填寫問卷", error_code="ET_SURVEY_012")


def validate_answers(*, questions: list[QuestionSpec], answers: list[AnswerDraft]) -> None:
    """逐題驗證作答（AC 3 / FR-ET-US13-02 / FR-ET-US13-03）。

    | 題型 | `so_id` | `answer_text` | 未填 |
    |------|---------|---------------|------|
    | `SINGLE` | **必填**，且須屬該題 | MUST 為空 | 擋（`ET_SURVEY_015`）|
    | `TEXT` | MUST 為空 | 選填，≤ 150 字 | **放行**（FR-03）|

    ## 為何問答題留空不擋

    FR-ET-US13-03（2026-08-28 裁示）：「問卷是回饋工具而非考試，強制作答只會換來
    『.』『無意見』之類的內容，反而讓教師誤判回收品質；空白本身是誠實的訊號」。

    ⚠️ **issue body 驗收條件 3 寫「全部題目作答後方可送出」**——那是 #238 加入問答題
    之前的敘述，已與 FR-03 相牴觸。以 spec 為準。

    Raises:
        AppError: 422 `ET_SURVEY_015` 尚有題目未作答（`extra.unanswered_sq_ids` 供前端
            逐題標示）；422 `ET_SURVEY_016` 文字答案超過上限；422 `ET_SURVEY_017`
            作答內容與問卷題目不符。
    """
    by_id = {q.sq_id: q for q in questions}
    seen: set[int] = set()
    for answer in answers:
        question = by_id.get(answer.sq_id)
        if question is None or answer.sq_id in seen:
            # 題目不存在（填答期間被刪除、或前端送錯）與同一題送兩次共用一碼：兩者都是
            # 我們自己的 UI 產不出來的畸形請求，使用者的下一步一律是「重新整理表單」。
            #
            # 同一題送兩次必須在此擋下而非讓它掉進 INSERT——那會撞
            # `UQ_ET_SURVEY_RESPONSE_D_RESPONSE_Q` 變成 500。
            raise _MALFORMED
        seen.add(answer.sq_id)
        if question.question_type == SURVEY_QUESTION_SINGLE:
            _validate_single(question, answer)
        else:
            _validate_text(answer)

    unanswered = [q.sq_id for q in questions if q.question_type == SURVEY_QUESTION_SINGLE and q.sq_id not in seen]
    if unanswered:
        raise AppError(
            status_code=422,
            detail="尚有題目未作答",
            error_code="ET_SURVEY_015",
            extra={"unanswered_sq_ids": unanswered},
        )


def build_detail_rows(*, questions: list[QuestionSpec], answers: list[AnswerDraft]) -> list[DetailRow]:
    """組出待寫入 `ET_SURVEY_RESPONSE_D` 的明細列（SA Q1 裁示 A）。

    ## 留空的問答題不寫列

    迴圈依據是「**該題是否有值**」而非題目清單，故 `_D` 只有實際有作答的題目——
    使「表裡有列 ⇔ 學員答了這題」成立。US9 之「問答題僅計已答人數」因此可直接
    `COUNT(*)`，不依賴任何過濾條件。

    反面（寫一列、兩欄皆 `NULL` 或空字串）會讓 US9 及後續所有統計都必須記得帶
    `WHERE ANSWER_TEXT IS NOT NULL`——漏一處就把「沒意見的人」算成「有回饋的人」，
    而且不會報錯，只會靜默算錯。

    ⚠️ `data-model.md` §ET_SURVEY_RESPONSE_D 的原文寫「每題一筆作答」與
    「`ANSWER_TEXT` 問答題必填」，兩處字面待 SA 同步為「每題**至多**一筆」與
    「有填時寫入」。唯一約束 `UQ_ET_SURVEY_RESPONSE_D_RESPONSE_Q` 不需變更——
    「唯一」本來就容許某題沒有列。

    順序依**題目順序**而非送出順序：明細列的順序決定 US9 明細檢視的呈現順序，
    在此排好那一頁就不必再排。

    Returns:
        僅含有作答內容之列；`answer_text` 已 `strip()`（只打空白視為未填）。
    """
    by_sq = {a.sq_id: a for a in answers}
    rows: list[DetailRow] = []
    for question in questions:
        answer = by_sq.get(question.sq_id)
        if answer is None:
            continue
        if question.question_type == SURVEY_QUESTION_SINGLE:
            rows.append(DetailRow(sq_id=question.sq_id, so_id=answer.so_id, answer_text=None))
            continue
        text = (answer.answer_text or "").strip()
        if not text:
            continue
        rows.append(DetailRow(sq_id=question.sq_id, so_id=None, answer_text=text))
    return rows


# ── 內部 ──────────────────────────────────────────────────────────────────────

#: 畸形請求之統一回應。訊息寫「請重新整理後再試」——前端的處置就是重載表單。
_MALFORMED: Final = AppError(
    status_code=422, detail="作答內容與問卷題目不符，請重新整理後再試", error_code="ET_SURVEY_017"
)


def _validate_single(question: QuestionSpec, answer: AnswerDraft) -> None:
    if answer.answer_text is not None:
        # 兩欄互斥（`data-model` 明示由應用層把關、不設 CHECK constraint）。
        raise _MALFORMED
    if answer.so_id is None or answer.so_id not in question.option_ids:
        raise _MALFORMED


def _validate_text(answer: AnswerDraft) -> None:
    if answer.so_id is not None:
        raise _MALFORMED
    if len(answer.answer_text or "") > ANSWER_TEXT_MAX_LEN:
        raise AppError(
            status_code=422,
            detail=f"文字答案至多 {ANSWER_TEXT_MAX_LEN} 字",
            error_code="ET_SURVEY_016",
        )
