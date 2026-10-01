"""線下核可之請求 / 回應 schema（US16 / #352）。"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.et.course.schemas import MAX_BIGINT

#: 批次核可時「這一筆沒有寫入」的理由。
#:
#: | 值 | 來源 |
#: |---|---|
#: | `NOT_COMPLETED` | `FR-ET-US16-03` 明訂「對名單中未完課者 MUST 跳過並提示」|
#: | `ALREADY_APPROVED` | SA 裁示 2026-09-17 Q2 = A |
#: | `NOT_ENROLLED` | **SD 自決**（見下）|
#:
#: `ALREADY_APPROVED` 的由來：wireframe 的單列 UI 對已有結果者**只給「撤銷」**（刻意
#: 不讓人直接改判），但已通過那列的勾選框並未停用，批次不通過因此能把「已通過」翻成
#: 「未通過」而不留任何原因、繞過 `FR-ET-US16-06` 的原因必填。
#:
#: `NOT_ENROLLED` 的由來：`tracking.completion_counts_by_student` **不濾在籍**——它數
#: 的是 `ET_PROGRESS` 的列，而移除學員走 `IS_REMOVED`、學習歷史刻意保留。所以一位曾
#: 完課、之後被移除的學員，完課判定仍會成立。少了這道閘會替不在班上的人建核可列，
#: 而他在 US17 核可查詢裡看得到。正常 UI 走不到（清單本來就不列已移除者），這是防繞過
#: 與「載入後才被移除」的競態。
#:
#: 對應訊息 `ET-MSG-ET02-310`（2026-09-17 隨本 issue 增列於 `spec_us16.md` §訊息類型）。
SkipReason = Literal["NOT_COMPLETED", "ALREADY_APPROVED", "NOT_ENROLLED"]


class SkippedItem(BaseModel):
    """批次中被跳過的一位學員。

    帶 `reason` 而非只回總數——兩種跳過對教師的**下一步不同**（未完課要等他完課，
    已核可要先撤銷並填原因），壓成同一句「已跳過 N 筆」會讓他不知道該做什麼。
    前端據此分別顯示 `ET-MSG-ET02-303` 與 `ET-MSG-ET02-309`。
    """

    user_id: str
    reason: SkipReason


class ApproveReq(BaseModel):
    """核可請求（單筆即 `user_ids` 長度為 1）。

    ## 為何單筆與批次共用同一支端點

    分兩支會讓「跳過」的回應格式有兩種，而那正是最容易分岔的地方——單筆端點若回
    204，前端就無從得知那一筆其實被跳過了。

    ## 為何不收 `version`

    批次的對象多半是「待核可」的學員，他們**根本還沒有 `ET_APPROVAL` 列**，沒有版本號
    可帶。防並發覆寫改由 repository 的條件式 `WHERE` 承擔（見 `repository` 模組
    docstring 的不對稱說明）。
    """

    # ⚠️ `Field(min_length/max_length)` 在 list 上限的是**陣列長度**，不是元素長度。
    # 元素另外標註 `max_length=20` 對齊 `DP_USER.USER_ID VARCHAR(20)` 與撤銷路徑的
    # `Path(max_length=20)`——沒有它的話，100 個各數 MB 的字串會完整進入記憶體、
    # 被塞進兩支查詢的 IN 清單，並**原樣反射**回 `skipped[].user_id`。
    # （本專案未掛 request body 大小限制的 middleware。）
    user_ids: list[Annotated[str, Field(min_length=1, max_length=20)]] = Field(min_length=1, max_length=100)
    result: Literal["PASS", "FAIL"]
    #: 選填備註（如不通過原因、考核情形）。`FR-ET-US16-04` 明訂 FAIL 得附備註；
    #: PASS 亦允許填寫，spec 未限制。
    result_note: str | None = Field(default=None, max_length=1000)


class RevokeReq(BaseModel):
    """撤銷請求。

    `reason` 的必填由 `rules.ensure_revoke_reason` 檢核而非 Pydantic `min_length=1`
    ——後者放行 `"   "`，且驗證失敗回 `COMMON_422` 不帶欄位名，前端無從把
    `ET-MSG-ET02-305` 掛回那個輸入框。此處只擋長度上限。
    """

    reason: str = Field(max_length=1000)
    #: 操作者在畫面上看到的那一版。不符即 409 `ET_APPROVAL_004`。
    version: int = Field(ge=0)


class ApproveResult(BaseModel):
    """核可（含批次）之結果。

    `approved` 與 `skipped` 相加**不一定等於**請求的人數——理論上不會，但若日後新增
    跳過理由而漏了計數，讓兩者相加對不上比悄悄少一筆好查。
    """

    approved: int
    skipped: list[SkippedItem]


class ApprovalRow(BaseModel):
    """一位學員於一門課程的核可事實——供 `tracking` 併進學員清單。

    ⚠️ **不含綜合狀態**：那個值要由完課狀態 × 本列即時導出
    （`rules.derive_approval_status`），而完課狀態只有 `tracking` 那邊算得出來。
    在這裡多開一個 `status` 欄位，等於邀請呼叫端跳過完課判定直接用它——而那正是
    `FR-ET-US16-02`「MUST NOT 另存狀態欄位」要防的事。
    """

    model_config = {"from_attributes": True}

    user_id: str
    result: str
    result_note: str | None
    is_revoked: bool
    revoke_reason: str | None
    approved_by: str
    approved_at: datetime
    version: int


class _ApprovalCore(BaseModel):
    """`ET_APPROVAL` 的原始欄位——**僅供 `paginate()` 序列化用的中繼型別**。

    `core/pagination.paginate` 以 `schema.model_validate(orm_item)` 序列化，只吃得到
    ORM 實體上有的欄位；課程名稱與三個人名要另以批次查詢補齊（見
    `query_repository` 模組 docstring）。故分頁先產出本型別，service 再補成對外的
    `ApprovalQueryRow`。

    ⚠️ 本型別**不對外**（前綴底線），不要拿它當 `response_model`——它少了姓名，
    而姓名正是 `FR-ET-US17-01` 要求的欄位。
    """

    model_config = {"from_attributes": True}

    course_id: int
    user_id: str
    result: str
    result_note: str | None
    is_revoked: bool
    revoke_reason: str | None
    #: ⚠️ #464 起可為 `None`：完課側（不需核可課程）**事實上沒有核可者**。
    approved_by: str | None
    #: ⚠️ #464 起可為 `None`：完課側取 `ET_ENROLLMENT.COMPLETED_AT`，而**活化之前**就已完課的
    #: 既有資料該欄為空。正式機從頭建不會有這種資料，測試環境會。
    approved_at: datetime | None
    revoked_by: str | None
    revoked_at: datetime | None


class ApprovalQueryRow(BaseModel):
    """教師 / 管理者視角的一列（`FR-ET-US17-01`）。

    含撤銷三件套（原因 / 人 / 時間）——它們是本視角**要求顯示**的欄位，與學員視角
    刻意相反（見 `MyApprovalRow`）。
    """

    user_id: str
    user_name: str
    course_id: int
    course_name: str
    result: str
    result_note: str | None
    #: 通過時間——核可列為 `APPROVED_AT`，完課列為第一次完課的時間（#464）。
    #: ⚠️ 可為 `None`：活化前就已完課的既有資料。前端顯示「—」並排在最後（`NULLS LAST`）。
    approved_at: datetime | None
    #: ⚠️ 可為 `None`：不需核可的課程**事實上沒有核可者**——不是遮蔽、也不是忘了填。
    approved_by_name: str | None
    is_revoked: bool
    revoke_reason: str | None
    revoked_by_name: str | None
    revoked_at: datetime | None


class ApprovalSearchReq(BaseModel):
    """ET04 核可查詢的查詢條件（`FR-ET-US17-01`）。

    ## 🔴 為何走 request body 而不是 query string（#391）

    `keyword` **必定是一個人的姓名或 Email**——這個參數沒有別的用法，而且兩者都是個資。
    而 URL 會被沿路的東西記下來、body 不會：

    | 記錄點 | 狀態 |
    |---|---|
    | EDMS 自家 access log | ✅ 已處理（`$request_uri` 去尾 + uvicorn `--no-access-log`）|
    | **EDMS nginx `error_log`** | ⚠️ 記錄完整 request，見下 |
    | **Cloudflare 請求日誌** | ⚠️ 記錄完整 URI，不在本系統掌控範圍 |

    nginx 的 error log 格式**不可自訂**，壓抑之需把層級提到 `crit`，代價是失去後端
    中斷的可觀測性，故不採（`nginx/log-format.conf` 的既有註記已寫明這兩條殘留）。

    故本查詢用 `POST /approvals/search`。⛔ **不要為了「相容」或「比較 RESTful」補一個
    `Query(...)` 的退路**——那等於把姓名放回網址，而且功能會正常運作、不會有任何東西
    變紅（`test_姓名走query_string不被接受` 是那道紅線）。

    ⚠️ 本端點是**不寫入的 POST**：用 POST 的唯一理由是上述的日誌問題，語意仍是讀取，
    故**刻意不注入** `get_operator`、不寫稽核日誌。

    > 📌 同類問題在其他四支端點仍未處理（`/dp/users` 與 `/dp/users/invites` 的 `q`
    > ——值可能是 Email、`/dp/audit` 的 `operator`、`/dm/library` 的 `author`）。
    > 見 #391 的收尾摘要。
    """

    #: 學員**姓名或 Email**（皆為部分比對，擇一命中即可，#436）。
    #:
    #: **選填**（#439）——原為必填（SA Q2 裁示 A），改為與 `course_id`「至少給一個」。
    #: 兩者皆不給仍回 `ET_APPROVAL_006`，由 `query_rules.normalize_search_criteria`
    #: 判定（全空白等同未填，否則送一個空格就繞過了）。**換的是手段不是目的**，完整
    #: 理由見該函式的 docstring。
    #:
    #: ⚠️ 此處不能再用 `min_length=1`：那會讓「明確送 `keyword: ""`」變成 422
    #: `COMMON_422`（不帶欄位名），而正確答案要看有沒有給課程。長度下限的判定必須與
    #: 課程條件一起做，故整段交給 service 前的純函式。
    #:
    #: ⚠️ 上限 100 而非姓名的 50：`DP_USER.EMAIL` 是 `VARCHAR(255)`，用 50 會讓長一點的
    #: 帳號永遠查不到，而使用者只會看到「查無資料」。100 足以涵蓋實務帳號長度，同時
    #: 仍遠低於 255，不讓它變成可任意灌長度的欄位。
    keyword: Annotated[str | None, Field(default=None, max_length=100)] = None
    #: 課程篩選（#439）；`None` 為不限。
    #:
    #: 🔴 非管理者**只能給自己開設的課程**，否則 403 `ET_APPROVAL_007`
    #: （`query_rules.ensure_course_filter_allowed`）。前端下拉本來就只列得出自己的課，
    #: 那道閘是防繞過——少了它，教師可以不指名地撈出任一門課的全部通過者名單。
    course_id: Annotated[int | None, Field(default=None, ge=1, le=MAX_BIGINT)] = None
    #: `PASS` / `FAIL`；`None` 為不限。
    result: Annotated[Literal["PASS", "FAIL"] | None, Field(default=None)] = None
    page: Annotated[int, Field(default=1, ge=1)] = 1
    limit: Annotated[int, Field(default=20, ge=1, le=100)] = 20


class ApprovalCourseOption(BaseModel):
    """ET04 課程篩選下拉的一個選項（#439）。

    🔴 **只列「已有核可紀錄」的課程**，不是全部課程。三個理由：

    1. **管理者需要已關閉的課程**，而 ET01 清單的 `scope=all` 恰好把它們排除
       （`course/repository.build_list_stmt`：`all` 僅「已發布且期間未過」）。核可紀錄
       絕大多數正落在已結束的課程上——沿用那支清單，管理者會發現最相關的課全部不見，
       而畫面不會說明任何事。
    2. **沒有死選項**：選了就必定有資料可看，不會出現「選了課程卻查無紀錄」的困惑。
    3. **天然有界**：以核可紀錄為母體，不隨課程總數無限成長。

    ⚠️ 只有 `course_id` 與 `course_name` ——這是下拉，不是課程清單。要顯示狀態 /
    期間 / 學員數請走 ET01（`GET /et/courses`），不要往這裡加欄位。
    """

    course_id: int
    course_name: str


class MyApprovalRow(BaseModel):
    """學員自查視角的一列（`FR-ET-US17-03`）。

    🔴 **刻意極簡，而且是「後端不回傳」不是「前端不渲染」**：

    | 不含 | 理由 |
    |---|---|
    | `result` | 本清單恆為已通過，回傳它只是邀請前端拿來做判斷 |
    | `result_note` | 教師寫的考核評語，不是給學員看的 |
    | `is_revoked` / `revoke_reason` / `revoked_*` | 已撤銷者根本不在清單內；回傳欄位等於告知「這裡有東西被藏起來」 |
    | `user_id` / `user_name` | 對象恆為呼叫者自己 |

    靠前端過濾的話，打開 devtools 就看得到。
    """

    course_id: int
    course_name: str
    #: 通過時間（#464 起含不需核可課程的完課時間）；活化前的既有完課可為 `None`。
    approved_at: datetime | None
