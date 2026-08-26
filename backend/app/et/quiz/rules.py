"""ET 測驗題目之純業務規則（#203）。

不需 DB、可獨立以 unit test 驗證（比照 `app/et/course/rules.py`）。

## 哪些規則**不在**這裡

`data-model.md` §ET_QUIZ / §ET_QUESTION 另有兩條規則屬**發布時**檢核（#204），
不在儲存題目時套用：

| 規則 | 為何不在儲存時擋 |
|------|-----------------|
| 同測驗各題配分總和 = 100 | 教師是逐題新增的——第 1 題存檔時總和必然不是 100，
  擋下等於無法建題。改由測驗詳細回傳 `points_total` 讓 UI 常駐顯示「90 / 100」，
  發布時才阻擋（FR-ET-US3-11） |
| 每測驗至少 1 題 | 新增測驗項目時會先建空殼（0 題），同理不能在建立時擋 |

數值範圍（及格分數 0–100、重考上限 0–999、時間限制 ≥ 1）由 schema 之 `Field`
約束處理，不重複寫在這裡——pydantic 已於請求解析階段擋下，走到 service 時必然合法。
"""

from app.core.exceptions import AppError
from app.et.constants import QUESTION_MULTIPLE, QUESTION_SINGLE

#: 每題選項數之上下限（`data-model.md` §ET_OPTION）。
MIN_OPTIONS = 2
MAX_OPTIONS = 6


def ensure_option_count_valid(count: int) -> None:
    """每題選項數須介於 2 至 6 個。

    下限 2：只有一個選項的題目沒有選擇可言。
    上限 6：來自 data-model，屬 UI 可讀性的取捨。

    Raises:
        AppError: 422 `ET_QUESTION_003`。
    """
    if not MIN_OPTIONS <= count <= MAX_OPTIONS:
        raise AppError(
            status_code=422,
            detail=f"每題選項數須介於 {MIN_OPTIONS} 至 {MAX_OPTIONS} 個",
            error_code="ET_QUESTION_003",
        )


def ensure_correct_options_valid(question_type: str, *, correct_count: int) -> None:
    """正確選項數須符合題型。

    | 題型 | 要求 | 理由 |
    |------|------|------|
    | `SINGLE` | **恰好 1 個** | 單選題有兩個正確答案時，計分無從定義 |
    | `MULTIPLE` | **至少 1 個** | 0 個會讓部分計分公式的分母為零（data-model 明訂） |

    ## 單選題那條是 SD 補上的

    `data-model.md` 只明訂多選題「至少 1 個正確選項」，未提單選題。但單選題若 0 個
    正確選項，評分同樣爆掉；若 2 個以上，「正確答案」失去意義。前端單選用 radio
    天然只能選一個，這裡要擋的是**繞過 UI 直接打 API** 的請求。

    Raises:
        AppError: 422 `ET_QUESTION_002`。
    """
    if question_type == QUESTION_SINGLE:
        ok = correct_count == 1
        detail = "單選題須恰好指定 1 個正確選項"
    elif question_type == QUESTION_MULTIPLE:
        ok = correct_count >= 1
        detail = "多選題須至少指定 1 個正確選項"
    else:  # pragma: no cover - schema 之 Literal 已擋下未知題型
        ok = False
        detail = "正確選項之設定不符題型規定"
    if not ok:
        raise AppError(status_code=422, detail=detail, error_code="ET_QUESTION_002")


def ensure_question_reorder_complete(*, current_ids: set[int], requested: list[int]) -> None:
    """題目重排：清單須涵蓋且僅涵蓋該測驗之現有題目。

    與章節（`ET_CHAPTER_002`）/ 項目（`ET_ITEM_002`）同一判定、**不同錯誤碼**——
    前端需靠 `error_code` 分辨是哪一層的重排失敗，共用單一代碼會使三層在 UI 上
    無從區隔。

    長度與集合都要檢查：`[1, 1, 2]` 之集合等同 `{1, 2}`，僅比對集合會漏掉重複；
    集合比對則擋下缺漏與夾帶他人測驗題目 ID 的越權嘗試。

    Raises:
        AppError: 422 `ET_QUESTION_004`。
    """
    if len(requested) != len(set(requested)) or set(requested) != current_ids:
        raise AppError(status_code=422, detail="重排清單與測驗題目不一致", error_code="ET_QUESTION_004")


def resequence_questions(ordered_ids: list[int]) -> dict[int, int]:
    """把完整順序陣列轉為 `{question_id: SORT_ORDER}`，自 1 起連續編號。

    > 這是**教師端**的排序。學員作答時的題目順序由系統洗牌決定並凍結於 attempt
    > 快照（`data-model.md` §ET_QUESTION：「學員端洗牌不依此」），屬 #6。
    """
    return {question_id: index for index, question_id in enumerate(ordered_ids, start=1)}
