"""引用之 DM 文件變動通知的查詢（#231）。

反查「哪些課程引用了哪些 DM 文件、擁有者是誰」，以及通知簿記表的讀寫。
比對規則在 `doc_change_rules.py`，兩者刻意分開——規則是純函式、可單獨變異驗證。
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.material.models import EtMaterial, EtMaterialDoc, EtMaterialDocNotify


@dataclass(frozen=True)
class DocReferenceRow:
    """一筆「某課程引用了某份文件」。同一位擁有者可能有多列（多門課）。"""

    doc_id: str
    owner_id: str
    course_id: int
    course_name: str
    #: 課程狀態（`DRAFT` / `PUBLISHED` / `CLOSED`）——**查詢層不據此過濾**，見下。
    course_status: str


async def list_doc_references(db: AsyncSession) -> list[DocReferenceRow]:
    """列出所有未軟刪除的「文件引用 → 課程擁有者」。

    五層皆須 `DELETED = 0`：`ET_MATERIAL_DOC` → `ET_MATERIAL` → `ET_ITEM` →
    `ET_CHAPTER` → `ET_COURSE`。漏掉任一層，教師會收到「一門他已經刪掉的課程」的
    通知——那門課在他畫面上根本不存在，無從處理。

    ⚠️ **刻意不在此過濾課程狀態。** 草稿課程是否通知為 #231 的 SA Q2、尚未裁示；
    母體一旦在 SQL 被縮小，日後改裁示時沒有任何跡象提醒這裡曾經濾過。故把
    `course_status` 交出去，由 service 依裁示處理——過濾與否都看得見
    （同 `stale-recipient-list` 類問題的處理原則：會讓問題隱形的過濾放 service）。

    Args:
        db: 資料庫 session。

    Returns:
        每筆為一組 `(文件, 擁有者, 課程)`；同一位擁有者的多門課程為多列。
    """
    stmt = (
        select(
            EtMaterialDoc.doc_id,
            EtCourse.owner_id,
            EtCourse.course_id,
            EtCourse.course_name,
            EtCourse.status,
        )
        .join(EtMaterial, EtMaterial.material_id == EtMaterialDoc.material_id)
        .join(EtItem, EtItem.material_id == EtMaterial.material_id)
        .join(EtChapter, EtChapter.chapter_id == EtItem.chapter_id)
        .join(EtCourse, EtCourse.course_id == EtChapter.course_id)
        .where(
            EtMaterialDoc.deleted == 0,
            EtMaterial.deleted == 0,
            EtItem.deleted == 0,
            EtChapter.deleted == 0,
            EtCourse.deleted == 0,
        )
        .distinct()
    )
    rows = await db.execute(stmt)
    return [
        DocReferenceRow(doc_id=r[0], owner_id=r[1], course_id=r[2], course_name=r[3], course_status=r[4])
        for r in rows.all()
    ]


async def load_notify_state(db: AsyncSession, *, doc_ids: set[str]) -> dict[tuple[str, str], EtMaterialDocNotify]:
    """取簿記表上這些文件的所有 `(DOC_ID, OWNER_ID)` 列，供比對。

    一次取回而非逐筆查：排程一輪要比對的組合數 ＝ 文件數 × 擁有者數，逐筆查會變成
    N+1。本表列數受限於「被引用的文件 × 擁有者」，整批取回無壓力。
    """
    if not doc_ids:
        return {}
    rows = await db.execute(select(EtMaterialDocNotify).where(EtMaterialDocNotify.doc_id.in_(doc_ids)))
    return {(r.doc_id, r.owner_id): r for r in rows.scalars().all()}
