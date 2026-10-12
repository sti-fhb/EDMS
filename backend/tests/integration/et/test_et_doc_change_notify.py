"""引用之 DM 文件變動通知的反查查詢（#231）。

從 `ET_MATERIAL_DOC` 反查到課程擁有者，五層皆須排除軟刪除：
`ET_MATERIAL_DOC` → `ET_MATERIAL` → `ET_ITEM` → `ET_CHAPTER` → `ET_COURSE`。
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import update

from app.et.constants import COURSE_DRAFT, COURSE_PUBLISHED, ITEM_MATERIAL
from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.material.doc_change_repository import list_doc_references
from app.et.material.models import EtMaterial, EtMaterialDoc

pytestmark = pytest.mark.integration

_DOC = "DM-TRAINING-000007"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _audit(**kw) -> dict:
    return {"created_user": "ZT_SEED", "created_date": _now(), **kw}


async def _make_chain(
    db,
    *,
    owner: str,
    course_name: str,
    doc_id: str = _DOC,
    status: str = COURSE_PUBLISHED,
) -> dict:
    """建一條完整的「課程 → 章節 → 項目 → 教材 → 文件引用」鏈，回傳各層 id。"""
    course = EtCourse(
        **_audit(
            course_name=course_name,
            status=status,
            owner_id=owner,
            urgent_remind_sent=False,
            version=0,
            require_approval=False,
        )
    )
    db.add(course)
    await db.flush()

    chapter = EtChapter(**_audit(course_id=course.course_id, chapter_name="第一章", sort_order=1, version=0))
    material = EtMaterial(**_audit(material_name="教材A", version=0))
    db.add(chapter)
    db.add(material)
    await db.flush()

    mat_doc = EtMaterialDoc(**_audit(material_id=material.material_id, doc_id=doc_id, sort_order=1))
    item = EtItem(
        **_audit(
            chapter_id=chapter.chapter_id,
            item_type=ITEM_MATERIAL,
            sort_order=1,
            material_id=material.material_id,
            version=0,
        )
    )
    db.add(mat_doc)
    db.add(item)
    await db.flush()

    return {
        "course_id": course.course_id,
        "chapter_id": chapter.chapter_id,
        "item_id": item.item_id,
        "material_id": material.material_id,
        "mat_doc_id": mat_doc.mat_doc_id,
    }


class TestListDocReferences:
    async def test_反查得到擁有者與課程名稱(self, db) -> None:
        await _make_chain(db, owner="ZT_T1", course_name="採血作業訓練")

        rows = [r for r in await list_doc_references(db) if r.doc_id == _DOC and r.owner_id == "ZT_T1"]

        assert len(rows) == 1
        assert rows[0].course_name == "採血作業訓練"

    async def test_同一擁有者兩門課引用同一文件_各回一列供彙整(self, db) -> None:
        """AC：同一次改版對同一位擁有者只發一次（多門課程彙整為一封）。

        彙整在 service 層做，查詢層要把兩門課都給出來——少了任一門，信裡就會漏列。
        """
        await _make_chain(db, owner="ZT_T2", course_name="課程甲")
        await _make_chain(db, owner="ZT_T2", course_name="課程乙")

        rows = [r for r in await list_doc_references(db) if r.doc_id == _DOC and r.owner_id == "ZT_T2"]

        assert {r.course_name for r in rows} == {"課程甲", "課程乙"}

    async def test_不同擁有者各自成列(self, db) -> None:
        await _make_chain(db, owner="ZT_T3", course_name="課程丙")
        await _make_chain(db, owner="ZT_T4", course_name="課程丁")

        rows = [r for r in await list_doc_references(db) if r.doc_id == _DOC and r.owner_id in {"ZT_T3", "ZT_T4"}]

        assert {(r.owner_id, r.course_name) for r in rows} == {("ZT_T3", "課程丙"), ("ZT_T4", "課程丁")}

    @pytest.mark.parametrize(
        ("model", "id_field", "key"),
        [
            (EtMaterialDoc, "mat_doc_id", "mat_doc_id"),
            (EtMaterial, "material_id", "material_id"),
            (EtItem, "item_id", "item_id"),
            (EtChapter, "chapter_id", "chapter_id"),
            (EtCourse, "course_id", "course_id"),
        ],
    )
    async def test_五層任一層軟刪除皆不列入(self, db, model, id_field, key) -> None:
        """AC：已軟刪除之教材 / 章節 / 課程不觸發通知。

        五層分開驗——漏掉任一層的 `DELETED = 0` 條件，都會讓教師收到「一門他已經刪掉的
        課程」的通知，而那門課在他的畫面上根本不存在，無從處理。
        """
        ids = await _make_chain(db, owner="ZT_T5", course_name="待刪課程")
        await db.execute(
            update(model).where(getattr(model, id_field) == ids[key]).values(deleted=1, updated_date=_now())
        )
        await db.flush()

        rows = [r for r in await list_doc_references(db) if r.doc_id == _DOC and r.owner_id == "ZT_T5"]

        assert rows == []

    async def test_回傳課程狀態供上層依裁示篩選(self, db) -> None:
        """Q2（草稿課程是否通知）未裁示前，查詢層**不預設過濾**、把狀態交出去。

        ⚠️ 刻意不在查詢層濾掉草稿：母體一旦在 SQL 被縮小，日後改裁示時沒有任何跡象
        提醒這裡曾經濾過。狀態交由 service 依裁示處理，過濾與否都看得見。
        """
        await _make_chain(db, owner="ZT_T6", course_name="草稿課", status=COURSE_DRAFT)

        rows = [r for r in await list_doc_references(db) if r.doc_id == _DOC and r.owner_id == "ZT_T6"]

        assert [r.course_status for r in rows] == [COURSE_DRAFT]
