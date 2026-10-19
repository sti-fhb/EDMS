"""稽核對象的課程名稱取得（#717）。

DP05 的「對象」欄對 ET 課程類原本只顯示課程 ID（`12`、`12:使用者ID`），使用者看不出
是哪一門課。裁示（2026-10-19）是**課程名取當時值、人名取現值**：

- **課程名**由寫入端存進稽核列的 `after_value.course_name`——本檔負責取得那個值。
  存當時值的理由是**課程改名不應改寫歷史**：稽核在記錄「當時發生了什麼」，
  當時那門課就叫那個名字。
- **人名**則相反，由查詢端查 `DP_USER` 活表取現值（`dp/audit/target_resolver`）。
  人改名後仍是同一個人；更關鍵的是**姓名是個資，不複製進稽核列**
  （見 `et/tracking/service.py` 的 `_log_export` docstring）。

⛔ **不要把課程名也改成查詢時查活表**，那會讓舊紀錄跟著課程改名而變動。
⛔ **不要把學員姓名加進稽核列**，那會把個資複製到第二個地方。
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.et.course.models import EtCourse


async def course_audit_name(db: AsyncSession, course_id: int) -> str | None:
    """取課程名稱供稽核列留存；查無回 `None`（呼叫端據此略過該鍵）。

    ⚠️ 取的是**呼叫當下**的名稱。若本次操作本身會改課程名，請在改名**之前**呼叫，
    否則記到的是改名後的值——稽核要記的是「當時那門課叫什麼」。

    Args:
        db:        資料庫 session。
        course_id: 課程 ID。

    Returns:
        課程名稱；查無該課程時為 `None`。
    """
    return await db.scalar(select(EtCourse.course_name).where(EtCourse.course_id == course_id))


async def course_audit_payload(db: AsyncSession, course_id: int) -> dict[str, str]:
    """組稽核用的課程欄位；查無課程時回空 dict（可安全展開）。

    用法：`after_value={**await course_audit_payload(db, course_id), ...}`
    """
    name = await course_audit_name(db, course_id)
    return {"course_name": name} if name else {}
