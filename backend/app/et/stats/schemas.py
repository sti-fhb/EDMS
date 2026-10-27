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
    ET03 頁面與本卡顯示同一組數字，各算一次的話兩邊會在課程剛開放 / 剛關閉的瞬間
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
    """教師卡「我的課程提醒」。

    對齊每週寄給教師的 `WEEKLY_REPORT`——那封信是「系統認定教師該知道什麼」的定案，
    本卡是它的**隨時可看版本**，不另立一套指標。

    ⛔ 刻意不含「我班級完成率」這種跨課程的單一平均值：教師要知道的是**哪一門**落後，
    而那已在 `ending_soon` 的逐課列表裡。平均值不可行動。

    📌 #818 移除了 `draft_count`（自己建立但尚未發布的課程數）。本卡由「待辦」更名為
    「提醒」之後，草稿數是唯一一項性質為「卡在我這」的東西，與區塊名稱對不上，前端
    已不顯示；草稿本來就在 ET01 課程列表看得到。前端的 `hasTeacherData` 亦同步改為
    只看 `ending_soon`——否則只有草稿的教師會收到一張空卡。
    """

    ending_soon: list[TeacherCourseLine]


class CourseRate(BaseModel):
    """管理者卡之一列：一門課程的完成狀況（#475）。

    2026-10-01 由「各受訓單位達成率」改為「各課程完成率」。前者依賴受訓單位標籤
    維護得好，而手測資料每單位僅 1～2 人、分母太小使比率跳動；後者只依賴課程本身，
    且落後時找得到可行動的對象（該課程的開課教師）。
    """

    #: ⚠️ **必須有**：分組鍵是 `(course_id, course_name)`，同名課程刻意不合併（不同年度
    #: 的年度訓練）。只給名稱的話，那兩列在前端無法區分——以名稱當 React key 會撞號，
    #: 症狀是改動一列時另一列跟著變，且不會有任何錯誤訊息。
    course_id: int
    course_name: str
    enrolled: int
    completed: int
    completion_rate: Decimal


class AdminCard(BaseModel):
    """管理者卡「全體訓練概況」。

    Attributes:
        completion_rate: 全體完成率。不可行動，保留的理由是「上面會問這個數字」
            （評鑑、報告），故前端放小字、不當主角。
        open_course_count: **截斷前**的母體大小——開放中且已有學員的課程門數。
            前端用它寫出「完成率最低的 N 門，開放中共 M 門」。⛔ 不可改回
            `len(by_course)`：那會寫成「最低的 5 門，共 5 門」，一句自相矛盾卻
            看不出是錯的話。
        by_course: 最需要關注的前幾門（上限見 `service._TOP_LAGGING_COURSES`）。
            排序規則見 `rules.rank_lagging_courses`——⚠️ 其中兩層只在「全站都是 0%」
            時才生效，而那正是上線當天的狀態。

    📌 #818 移除了 `overdue_incomplete`（課程已過訖止、學員仍未完課的人次）。母體
    排除已關閉之後，「逾期」的課程正好全被排除，該欄會結構性恆為 0；它自 2026-10-02
    起前端就不顯示，`hasAdminData` 也只看 `by_course`，移除不影響任何畫面。
    """

    completion_rate: Decimal
    open_course_count: int
    by_course: list[CourseRate]


class EtDashboard(BaseModel):
    """`GET /api/et/dashboard` 之回應。"""

    student: StudentCard | None
    teacher: TeacherCard | None
    admin: AdminCard | None
