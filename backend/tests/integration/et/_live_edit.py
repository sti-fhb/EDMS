"""測試捷徑：在已發布 / 已關閉課程上**直接編輯活表內容**（#631）。

## 為什麼需要它

#631 之後，已發布課程的內容編輯先寫進編輯暫存區，按「更新」才整批寫活表；而「更新」
會重跑**十項發布檢核**（至少 1 章節 + 1 教材、至少 1 組受訓對象、起訖時間已填、各測驗
配分總和 = 100 且每測驗至少 1 題、無引用之廢止文件…）。

ET 多數整合測試的課程**刻意不備妥那些**——它們直接 `update(EtCourse).values(status=...)`
把課程改成已發布。理由寫在各檔的 `_course` docstring 裡，且各檔寫法一致：那些檔要驗的
是加入 / 學習 / 問卷填寫，不是發布檢核；綁上去的話 #204 的規則一改，這裡就整片紅。

本工具讓那個前提繼續成立：把課程**暫時退回草稿** → 在草稿路徑上編輯（直接寫活表）→
還原原狀態。等價於「教師編完並按了更新」的**結果**，但不經過檢核。

## ⛔ 不可用來測暫存區本身

用本工具寫出來的測試對「編輯 → 暫存 → 更新」這條路徑**沒有任何覆蓋**，而且看起來很像
有——它造出的活表內容與真的按過更新一模一樣。暫存路徑的行為另由這兩個檔守著，它們走
真正的流程：

- `test_et_course_stage.py`——套用、刪除連帶、問卷凍結、樂觀鎖
- `test_et_staged_write_paths.py`——每個內容寫入端點**是否真的改走暫存區**（列舉式守門）

⚠️ 因此也不要用它來「讓紅的測試變綠」而不看那條測試在驗什麼：若某條測試驗的正是
「教師改了東西之後學員看到什麼」，那它現在該驗的是**按下更新之後**，不是用本工具繞過。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.et.constants import COURSE_DRAFT
from app.et.course.models import EtCourse


async def _set_status(db: AsyncSession, course_id: int, status: str) -> None:
    await db.execute(update(EtCourse).where(EtCourse.course_id == course_id).values(status=status))
    await db.flush()


@asynccontextmanager
async def editing_live(db: AsyncSession, course_id: int) -> AsyncIterator[None]:
    """區塊內對該課程的內容編輯直接寫活表（暫時退回草稿）。

    用法：

        async with editing_live(db, course_id):
            chapter_id = await _chapter(client, teacher, course_id)
            item_id = await _item(client, teacher, chapter_id)

    還原放在 `finally`：區塊內的斷言失敗時，課程狀態仍會回到原值——否則失敗訊息會變成
    下一個斷言的「課程是草稿」，掩蓋真正的原因。

    原狀態本來就是草稿時整段是 no-op（不必在呼叫端先判斷）。
    """
    original = await db.scalar(select(EtCourse.status).where(EtCourse.course_id == course_id))
    assert original is not None, f"課程 {course_id} 不存在"
    await _set_status(db, course_id, COURSE_DRAFT)
    try:
        yield
    finally:
        await _set_status(db, course_id, original)
