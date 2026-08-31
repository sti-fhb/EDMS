"""ET 課後問卷之純業務規則（#204）。

不需 DB、可獨立以 unit test 驗證（比照 `app/et/course/rules.py`、`app/et/quiz/rules.py`）。
Service 負責取資料與寫入，判斷交給本模組。

## 與測驗題目規則的三處差異（不可照抄 `quiz/rules.py`）

| 項目 | 測驗題目 | 問卷題目 |
|------|---------|---------|
| 題型 | `SINGLE` / `MULTIPLE` | `SINGLE` / `TEXT`（**不共用值域**，見 `constants.py`）|
| 選項數 | 2–6（`ET_QUESTION_003`）| 單選至少 2、**無上限**；問答**必須 0 個** |
| 正確選項 | 有（依題型判定）| **無此概念**——問卷是收集意見，沒有對錯 |
| 凍結 | 無 | **有填答即凍結**（`ET_SURVEY_003`）|

## 問卷可刪除（#238 推翻 #204 之裁示 Q1）

#204 當時裁示「問卷只能停用」，本模組因而沒有刪除規則。#238 依實測回饋改為
**未發布（`DRAFT`）課程可刪除、已發布僅可停用**，故新增 `ensure_survey_deletable`。

⚠️ 該變更連帶要求 `UQ_ET_SURVEY_COURSE` 改為部分唯一索引（migration `8713c6177f6f`）
——否則軟刪的問卷會永久佔住該課程。

錯誤訊息一律不嵌入動態值（問卷名稱、題幹等），對齊 `sti-error-codes`。
"""

from typing import Final

from app.core.exceptions import AppError
from app.et.constants import COURSE_DRAFT, SURVEY_QUESTION_TEXT

#: 每題選項數下限（`data-model.md` §ET_SURVEY_OPTION：「同 SQ_ID 下至少 2 個選項」）。
#:
#: **刻意沒有上限常數**——data-model 未訂上限，與測驗題目之 2–6 不同。請求大小的
#: 防護由 schema 之 `max_length` 負責，那是防濫用、不是業務規則，兩者不應混為一談。
MIN_OPTIONS: Final = 2


def ensure_survey_absent(*, exists: bool) -> None:
    """一門課程 0～1 份課後問卷（AC 22 / FR-ET-US3-09）。

    Args:
        exists: 該課程是否已有未刪除之問卷。

    Raises:
        AppError: 409 `ET_SURVEY_002`（ET-MSG-ET02-010）。
    """
    if exists:
        raise AppError(status_code=409, detail="一門課程僅可建立 1 份課後問卷", error_code="ET_SURVEY_002")


def ensure_option_count_valid(count: int) -> None:
    """每題選項數須達下限 2（AC 19）。

    只有一個選項的題目沒有選擇可言；0 個則連題目都不成立。

    Raises:
        AppError: 422 `ET_SURVEY_004`（ET-MSG-ET02-008）。
    """
    if count < MIN_OPTIONS:
        raise AppError(status_code=422, detail=f"每題至少需 {MIN_OPTIONS} 個選項", error_code="ET_SURVEY_004")


def ensure_editable(*, has_responses: bool) -> None:
    """題目與選項之編修須於**尚無任何填答**時（AC 20 / 21，FR-ET-US3-10）。

    判定是「**是否存在**任何未刪除之填答」而非筆數——一個人填了，題目就不能再改，
    否則他填的答案會對應到已不存在或已改寫的題目，統計出來的東西沒有意義。

    ## 凍結的範圍

    擋：題目與選項之新增 / 修改 / 刪除、題目重排。
    **不擋**：問卷名稱與 `IS_ACTIVE`——凍結後教師唯一能做的就是停用問卷（AC 21），
    把停用也擋掉等於整張卡片變成死的。

    Raises:
        AppError: 422 `ET_SURVEY_003`（ET-MSG-ET02-009）。
    """
    if has_responses:
        raise AppError(status_code=422, detail="已有學員填答，題目與選項不可修改", error_code="ET_SURVEY_003")


def ensure_question_reorder_complete(*, current_ids: set[int], requested: list[int]) -> None:
    """題目重排：清單須涵蓋且僅涵蓋該問卷之現有題目。

    與章節（`ET_CHAPTER_002`）/ 項目（`ET_ITEM_002`）/ 測驗題目（`ET_QUESTION_004`）
    同一判定、**不同錯誤碼**——前端需靠 `error_code` 分辨是哪一層的重排失敗。

    長度與集合都要檢查：`[1, 1, 2]` 之集合等同 `{1, 2}`，僅比對集合會漏掉重複；
    集合比對則擋下缺漏與夾帶他人問卷題目 ID 的越權嘗試。

    > 這是本專案第四處相同判定（章節 / 項目 / 測驗題目 / 問卷題目）。維持各自實作是
    > 沿用 `quiz/rules.py` 的既有作法；若要收斂，宜一次搬到 `app/et/common/`，
    > 而非只讓其中一處去 import 另一處的私有函式。

    Raises:
        AppError: 422 `ET_SURVEY_006`。
    """
    if len(requested) != len(set(requested)) or set(requested) != current_ids:
        raise AppError(status_code=422, detail="重排清單與問卷題目不一致", error_code="ET_SURVEY_006")


def resequence_questions(ordered_ids: list[int]) -> dict[int, int]:
    """把完整順序陣列轉為 `{sq_id: SORT_ORDER}`，自 1 起連續編號。

    > 問卷題目**保留教師排序**（SA 裁示）——與測驗題目不同，問卷不洗牌。測驗洗牌是
    > 為了防作弊，問卷則是教師刻意安排的敘事順序（例如由總體滿意度問到細項）。
    """
    return {sq_id: index for index, sq_id in enumerate(ordered_ids, start=1)}


def ensure_options_match_type(question_type: str, *, option_count: int) -> None:
    """選項數須符合題型（#238）。

    | 題型 | 要求 | 錯誤碼 |
    |------|------|--------|
    | `SINGLE` | 至少 2 個（無上限）| `ET_SURVEY_004` |
    | `TEXT` | **必須 0 個** | `ET_SURVEY_008` |

    ## 問答題為何是「必須 0 個」而不是「忽略選項」

    教師把單選題改成問答題時，原本填的選項若被靜默丟棄，他會以為那些選項還在——
    直到學員端呈現時才發現不對。明確擋下並提示，前端才有立場告訴他「切換題型會清空
    選項」。

    ## 兩種違規為何用不同錯誤碼

    前端要據此決定提示什麼：`ET_SURVEY_004` 是「請再加一個選項」、`ET_SURVEY_008` 是
    「問答題不能有選項」。共用一個代碼會讓兩種相反的修正方向擠在同一句訊息裡。

    Raises:
        AppError: 422 `ET_SURVEY_004`（單選題選項不足）或 `ET_SURVEY_008`（問答題帶選項）。
    """
    if question_type == SURVEY_QUESTION_TEXT:
        if option_count:
            raise AppError(status_code=422, detail="問答題不可設定選項", error_code="ET_SURVEY_008")
        return
    # `SINGLE`——schema 之 Literal 已擋下未知題型，走到這裡必為單選
    ensure_option_count_valid(option_count)


def ensure_survey_deletable(course_status: str) -> None:
    """僅**草稿**課程之問卷可刪除（#238）。

    已發布 / 已關閉一律只能停用（`IS_ACTIVE=false`）。

    ## 為何以課程狀態判定，而非「有無填答」

    未發布課程學員看不到，不可能有填答，兩者實務上等價。選課程狀態是因為它與
    「已發布僅可停用」對稱，教師的心智模型單純——**發布前隨便改，發布後只能停用**
    ——不必去想「有沒有人填過」。

    ## 「已關閉」為何也擋

    關閉可逆（`ET-11` 再開課）。若允許在關閉期間刪問卷，再開課後學員的填答入口就
    無故消失了。

    Raises:
        AppError: 422 `ET_SURVEY_007`。
    """
    if course_status != COURSE_DRAFT:
        raise AppError(
            status_code=422,
            detail="僅草稿課程之問卷可刪除，已發布課程請改用停用",
            error_code="ET_SURVEY_007",
        )
