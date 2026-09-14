"""ET03 學員學習狀況追蹤之請求 / 回應 schema（US9 / #322）。"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class EnrollmentRow(BaseModel):
    """`paginate()` 與 `StudentRow` 之間的中介——**只含 `ET_ENROLLMENT` 自身的欄位**。

    `paginate()` 以 `result.scalars()` 取結果（只拿第一欄）且必須給 schema 序列化，故
    清單查詢只能選 `EtEnrollment`；聚合值由 service 批次補齊後才組成 `StudentRow`。

    刻意**不讓 `StudentRow` 的聚合欄位帶預設值**——那樣雖能一步到位，但漏補時會靜默送出
    0（而「0 分」與「未作答」意義相反）。多一個中介型別換「少一個欄位就是 TypeError」。

    ⚠️ **不含 `completion_status`**：那個欄位是死的（只在加入時寫入 `NOT_STARTED`），
    放進來遲早有人直接用它。要的是即時計算的值，見 `StudentRow`。
    """

    model_config = {"from_attributes": True}

    user_id: str
    joined_at: datetime
    last_activity_at: datetime | None


class StudentRow(BaseModel):
    """區塊 1 的一列學員（`FR-ET-US9-02`）。

    ## `completion_status` / `progress_pct` 為**即時計算**，不讀 `ET_ENROLLMENT` 的欄位

    `ET_ENROLLMENT.COMPLETION_STATUS` 只在加入課程時寫入 `NOT_STARTED`，**沒有任何路徑
    推進它**；`COMPLETED_AT` 則全無寫入點。讀它們會讓每位學員永遠顯示「未開始」，而
    畫面上看不出資料是死的。ET04「我的課程」於 #284 踩過同一個坑並已改為即時導出
    （`enrollment/service.my_courses` 有對應註解），本頁沿用該做法。
    """

    user_id: str
    #: 取自 `DP_USER.USER_NAME`；查無（帳號已刪）時為 `None`。
    user_name: str | None
    joined_at: datetime
    #: `NOT_STARTED` / `IN_PROGRESS` / `COMPLETED`——由完成項目數即時導出。
    completion_status: str
    #: 0~100 之整數百分比（四捨五入）。完課判定**不**看這個值，見 `is_course_completed`。
    progress_pct: int
    #: 已作答測驗之最高分平均；**完全未作答時為 `None`**（前端顯示「—」）。
    #: 回 `None` 而非 0——0 分與未作答意義相反，混為一談會讓教師誤判需要輔導的對象。
    avg_score: Decimal | None
    #: 最近一次學習動作**或測驗提交**時間（取兩者較晚者，見 service）。
    last_activity_at: datetime | None
