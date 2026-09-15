"""週報明細下載連結（T164 / US14 / #325）。

## 為何指向**前端**路由而非後端端點

信件中的連結是瀏覽器導覽，**帶不了 `Authorization` header**——直接指向後端端點只會拿到
401。故連結指向前端的一個中繼路由，由它帶 JWT 呼叫後端；未登入時沿用既有的登入 overlay，
登入後回到原路由（FR-ET-US14-11 之「未登入 MUST 導向登入頁」）。

## 為何連結不帶 `course_id`

`WEEKLY_REPORT` 範本的 `{REPORT_CSV_URL}` 是**單一**佔位，而一份週報涵蓋多門課程。
故週報用的連結不指定課程，由後端依**收件人自己的角色**決定範圍（教師為自己擁有的
開放中課程、管理者為全域），與該收件人在信中看到的摘要範圍一致。

端點另接受選填的 `course_id` 以取單一課程之明細（供日後由課程頁直接下載），該路徑
會檢核擁有權——FR-ET-US14-11 (2) 的「越權存取 MUST 回應無權限」即針對它。
"""

from typing import Final

from app.core.config import settings

#: 前端中繼路由（見 `frontend/src/et/reports/`）。
_ROUTE: Final = "/et/reports/weekly"


def weekly_report_link(course_id: int | None = None) -> str:
    """週報明細下載之前端連結；`course_id` 省略時為收件人權限範圍內的全部課程。"""
    base = f"{settings.FRONTEND_BASE_URL.rstrip('/')}{_ROUTE}"
    return base if course_id is None else f"{base}?courseId={course_id}"
