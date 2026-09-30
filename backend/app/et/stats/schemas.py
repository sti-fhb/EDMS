"""首頁教育訓練儀表板之回應形狀（#453 / #89 的 P3）。

## 三張卡各自為 `None` 或有內容，由**角色**決定

`None` = 使用者沒有該角色，該卡不適用。**有角色但沒有資料時回空內容而非 `None`**
——兩者在前端的處理相同（都不渲染），但語意不同：前者是「這個人不是教師」，後者是
「他是教師但目前沒有要處理的課」。混為一談會讓日後想加「目前沒有待辦」的正向訊息
時無從分辨。

⚠️ **渲染與否由前端依「有無資料」判定，不是依角色**——#89 明訂：

> spec 定義「人人具 ET 學員預設角色」，若嚴格「有 ET 角色就顯示我的課程」→ 主管也會
> 看到空的「我的課程」。故規則為**卡片無資料就不渲染**。
"""

from decimal import Decimal

from pydantic import BaseModel


class StudentCard(BaseModel):
    """學員卡「我的學習概況」。

    四個數字**取自 `EtEnrollmentService.my_courses()` 的 `summary`**，不另算一份：
    ET04 頁面與本卡顯示同一組數字，各算一次的話兩邊會在課程剛開放 / 剛關閉的瞬間
    分歧，而兩個數字都看起來合理。
    """

    joined: int
    in_progress: int
    not_started: int
    completed: int
    pending_open: int


class TeacherCourseLine(BaseModel):
    """教師卡之一列：一門即將截止且仍有人未完課的課程。"""

    course_id: int
    course_name: str
    #: 距訖止天數（0 = 今天到期）。
    days_left: int
    #: 該課程尚未完課的在籍人數。
    not_completed: int


class TeacherCard(BaseModel):
    """教師卡「我的課程待辦」。

    對齊每週寄給教師的 `WEEKLY_REPORT`——那封信是「系統認定教師該知道什麼」的定案，
    本卡是它的**隨時可看版本**，不另立一套指標。

    ⛔ 刻意不含「我班級完成率」這種跨課程的單一平均值：教師要知道的是**哪一門**落後，
    而那已在 `ending_soon` 的逐課列表裡。平均值不可行動。
    """

    ending_soon: list[TeacherCourseLine]
    #: 自己建立但尚未發布的課程數——「東西卡在我這」的訊號（學員根本看不到）。
    draft_count: int


class UnitRate(BaseModel):
    """管理者卡之一列：一個受訓單位的達成狀況。"""

    tag_name: str
    enrolled: int
    completed: int
    completion_rate: Decimal


class AdminCard(BaseModel):
    """管理者卡「全體訓練概況」。

    Attributes:
        overdue_incomplete: 課程已過訖止、學員仍未完課的人次。**最可行動的一項**
            ——看到就要處理（催辦 / 延期 / 認列）。
        completion_rate: 全體完成率。不可行動，保留的理由是「上面會問這個數字」
            （評鑑、報告），故前端放小字、不當主角。
        by_unit: 各受訓單位達成率，**達成率由低到高**——要找的是落後的那一個。
    """

    overdue_incomplete: int
    completion_rate: Decimal
    by_unit: list[UnitRate]


class EtDashboard(BaseModel):
    """`GET /api/et/dashboard` 之回應。"""

    student: StudentCard | None
    teacher: TeacherCard | None
    admin: AdminCard | None
