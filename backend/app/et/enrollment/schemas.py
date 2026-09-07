"""ET04 我的課程與加入新課程（US4 / #247）schema。

## 學員端與教師端不共用 schema

教師端的課程回應含 `version` / `invitation_code` / 發布檢核結果等編輯用欄位；學員端
只需要卡片要顯示的東西。共用會讓邀請碼隨著「我的課程」發給每一位學員——那是一個
只該由教師看見的值。
"""

from datetime import datetime

from pydantic import BaseModel, Field

#: 邀請碼輸入之**請求大小防護**（非業務規則）。
#:
#: 業務判定在 `rules.normalize_invitation_code`（8 碼純數字，回 `None` 表格式不符）。
#: 這裡放寬到 32 只是不讓單一請求塞進超長字串；兩者職責不同，界限也不同。
INVITATION_CODE_INPUT_MAX_LEN = 32


class JoinByCodeReq(BaseModel):
    """以邀請碼預覽 / 加入課程之請求（AC 5）。"""

    invitation_code: str = Field(min_length=1, max_length=INVITATION_CODE_INPUT_MAX_LEN)


class JoinPreview(BaseModel):
    """邀請碼驗證通過後之課程資訊（AC 6 / AC 8）。

    Attributes:
        already_joined: 學員已在此課程。**刻意不以 4xx 表達**——那是正常導航
            （ET-MSG-ET04-003 為「提示」類型），用錯誤路徑做正常導航會讓前端得從
            `catch` 裡呼叫 `navigate`。
        open_start_at: 課程開放學習之時間。**未到時仍允許加入**（#247 SA Q2 裁示 A），
            前端據此顯示「本課程將於 {時間} 開放學習」。不告知的話學員會加入成功卻
            在清單看不到課程（AC 4），以為加入失敗而反覆重試。
    """

    course_id: int
    course_name: str
    owner_name: str | None
    chapter_count: int
    already_joined: bool
    open_start_at: datetime | None


class JoinResult(BaseModel):
    """加入課程之結果（AC 7 / ET-MSG-ET04-004）。"""

    course_id: int
    completion_status: str
    #: 加入當下課程尚未開放（`open_start_at` 未到）——前端據此把成功提示換成
    #: 「已加入，課程開放後將出現於清單」。
    pending_open: bool


class MyCourseRow(BaseModel):
    """我的課程卡片（AC 3）。

    Attributes:
        progress_pct: 當前學習進度百分比＝**完成項目數 ÷ 總項目數**（#274 填實，
            原為恆 0 的接點）。與 ET05 側欄的課程進度條同一定義——同一門課在兩個
            畫面顯示不同的數字，使用者只會當成其中一個壞了。
    """

    course_id: int
    course_name: str
    status: str
    completion_status: str
    tags: list[str]
    chapter_count: int
    open_start_at: datetime | None
    open_end_at: datetime | None
    progress_pct: int


class MyCoursesSummary(BaseModel):
    """清單上方之統計（AC 2）。

    `joined` 為總數（wireframe 有此卡），其餘三項為 AC 2 明列之三種學習狀態。
    wireframe 的三張卡缺「未開始」，以 AC 為準並保留總數卡，故為四項。
    """

    joined: int
    in_progress: int
    not_started: int
    completed: int


class MyCoursesResult(BaseModel):
    """ET04 頁面之完整資料。

    統計與清單**同一個端點**：兩者必須來自同一次查詢，否則卡片有 3 門而統計寫 2 門
    這種不一致會在課程剛被關閉 / 剛到開放時間的瞬間出現。
    """

    summary: MyCoursesSummary
    courses: list[MyCourseRow]
