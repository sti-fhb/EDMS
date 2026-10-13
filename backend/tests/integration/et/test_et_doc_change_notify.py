"""引用之 DM 文件變動通知的反查查詢（#231）。

從 `ET_MATERIAL_DOC` 反查到課程擁有者，五層皆須排除軟刪除：
`ET_MATERIAL_DOC` → `ET_MATERIAL` → `ET_ITEM` → `ET_CHAPTER` → `ET_COURSE`。
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import update

from sqlalchemy import select

from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dm.catalog.models import DmCategory  # noqa: F401
from app.dm.document.file_paths import storage_root
from app.dm.document.models import DmDocument, DmDocVersion
from app.dp.notify.models import DpEmailLog
from app.dp.users.models import DpUser
from app.et.common.dm_client import TRAINING_CATEGORY
from app.et.constants import COURSE_DRAFT, COURSE_PUBLISHED, ITEM_MATERIAL, ROLE_TEACHER
from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.material.doc_change_repository import list_doc_references
from app.et.material.doc_change_service import EtDocChangeNotifyService
from app.et.material.models import EtMaterial, EtMaterialDoc, EtMaterialDocNotify
from app.et.roles.models import EtUserRole

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


# ── 端到端：掃描 → 比對 → 寄信 → 寫簿記 ────────────────────────────────────────


async def _user(db, user_id: str, *, status: str = "ACTIVE") -> str:
    now = _now()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@edms.local",
            pwd_hash=hash_password("Abcd1234"),
            user_name=f"測試{user_id}",
            status=status,
            login_fail_count=0,
            pwd_changed_date=now,
            must_change_pwd=False,
            created_user="admin01",
            created_date=now,
        )
    )
    db.add(
        EtUserRole(
            user_id=user_id, role=ROLE_TEACHER, is_active=True, created_user="SYSTEM", created_date=now, deleted=0
        )
    )
    await db.flush()
    return user_id


async def _published_doc(db, doc_id: str, *, name="訓練教材", version_no="v1.0", obsolete=False) -> int:
    """建一份已發布（或已廢止）之訓練教材。廢止保留 `current_version_id`，比照 DM 行為。"""
    import os

    now = utcnow()
    db.add(
        DmDocument(
            doc_id=doc_id,
            doc_name=name,
            category_code=TRAINING_CATEGORY,
            func_code=None,
            current_version_id=None,
            status="OBSOLETE" if obsolete else "PUBLISHED",
            created_user="ed",
            created_date=now,
        )
    )
    await db.flush()
    ver = DmDocVersion(
        doc_id=doc_id,
        version_no=version_no,
        change_summary="摘要",
        file_name="a.pdf",
        file_path=os.path.join(storage_root(), doc_id, f"{version_no}.pdf"),
        file_size=100,
        file_mime="application/pdf",
        status="PUBLISHED",
        published_date=now,
        created_user="ed",
        created_date=now,
    )
    db.add(ver)
    await db.flush()
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == doc_id))
    doc.current_version_id = ver.version_id
    await db.flush()
    return ver.version_id


async def _pending_mails(db, template_code: str) -> list[DpEmailLog]:
    """⚠️ 必須篩 `STATUS='PENDING'`。

    範本 params key 打錯時平台會寫一列 `STATUS='FAILED'` 的空信且**不拋例外**，
    只數列數的斷言會把那種靜默失敗當成成功。
    """
    rows = await db.scalars(
        select(DpEmailLog).where(DpEmailLog.template_code == template_code, DpEmailLog.status == "PENDING")
    )
    return list(rows.all())


async def _notify_state(db, doc_id: str, owner_id: str) -> EtMaterialDocNotify | None:
    return await db.scalar(
        select(EtMaterialDocNotify).where(
            EtMaterialDocNotify.doc_id == doc_id, EtMaterialDocNotify.owner_id == owner_id
        )
    )


class TestDocChangeNotifyEndToEnd:
    async def test_首次掃描到引用即通知改版並寫簿記(self, db) -> None:
        """裁示 Q1 = C：查無簿記列即視為有變動。"""
        doc = "DM-TRAINING-910001"
        owner = await _user(db, "ZT_O1")
        ver_id = await _published_doc(db, doc, name="採血手冊", version_no="v2.0")
        await _make_chain(db, owner=owner, course_name="採血訓練", doc_id=doc)

        result = await EtDocChangeNotifyService().run(db)
        await db.flush()

        assert result.notified == 1
        mails = [m for m in await _pending_mails(db, "DOC_VERSION_CHANGED") if owner in (m.recipient or "")]
        assert len(mails) == 1, "params key 對不上時平台會寫 FAILED 空信，本斷言已篩 PENDING"
        state = await _notify_state(db, doc, owner)
        assert state is not None
        assert state.last_notified_version_id == ver_id
        assert state.last_notified_status == "PUBLISHED"

    async def test_廢止寄的是另一個範本(self, db) -> None:
        """兩種觸發的**處置不同**，故範本不共用——這條釘住它們沒有被合併。"""
        doc = "DM-TRAINING-910002"
        owner = await _user(db, "ZT_O2")
        await _published_doc(db, doc, obsolete=True)
        await _make_chain(db, owner=owner, course_name="已廢止引用課", doc_id=doc)

        await EtDocChangeNotifyService().run(db)
        await db.flush()

        obsoleted = [m for m in await _pending_mails(db, "DOC_OBSOLETED") if owner in (m.recipient or "")]
        changed = [m for m in await _pending_mails(db, "DOC_VERSION_CHANGED") if owner in (m.recipient or "")]
        assert len(obsoleted) == 1
        assert changed == [], "廢止不得同時寄出改版通知"

    async def test_同一擁有者兩門課彙整成一封(self, db) -> None:
        """AC：同一次改版對同一位擁有者只發一次（多門課程彙整為一封）。"""
        doc = "DM-TRAINING-910003"
        owner = await _user(db, "ZT_O3")
        await _published_doc(db, doc)
        await _make_chain(db, owner=owner, course_name="課程甲", doc_id=doc)
        await _make_chain(db, owner=owner, course_name="課程乙", doc_id=doc)

        result = await EtDocChangeNotifyService().run(db)
        await db.flush()

        assert result.notified == 1, "兩門課必須彙整為一封，不逐課發送"
        mails = [m for m in await _pending_mails(db, "DOC_VERSION_CHANGED") if owner in (m.recipient or "")]
        assert len(mails) == 1
        assert "課程甲" in mails[0].body and "課程乙" in mails[0].body, "彙整的那封要列出全部受影響課程"

    async def test_第二次掃描無變動則不重寄(self, db) -> None:
        """少了這條，每天都會對同一份沒變的文件寄一封。"""
        doc = "DM-TRAINING-910004"
        owner = await _user(db, "ZT_O4")
        await _published_doc(db, doc)
        await _make_chain(db, owner=owner, course_name="穩定課程", doc_id=doc)

        await EtDocChangeNotifyService().run(db)
        await db.flush()
        second = await EtDocChangeNotifyService().run(db)
        await db.flush()

        assert second.notified == 0
        mails = [m for m in await _pending_mails(db, "DOC_VERSION_CHANGED") if owner in (m.recipient or "")]
        assert len(mails) == 1, "第二輪不得再寄"

    async def test_單一文件查不到不中斷整批(self, db) -> None:
        """一份壞掉的引用不得讓其他教師都收不到通知。"""
        good, bad = "DM-TRAINING-910005", "DM-TRAINING-999999"
        owner = await _user(db, "ZT_O5")
        await _published_doc(db, good)
        # `bad` 刻意不建 DmDocument —— SRVDM001 會回 404
        await _make_chain(db, owner=owner, course_name="正常課", doc_id=good)
        await _make_chain(db, owner=owner, course_name="壞引用課", doc_id=bad)

        result = await EtDocChangeNotifyService().run(db)
        await db.flush()

        assert result.skipped_docs == 1
        assert result.notified == 1, "好的那份仍須通知"

    async def test_擁有者已停用則不寄且簿記不前進(self, db) -> None:
        """🔴 「沒有告訴他」不該記成「已告訴他」。

        簿記若在寄不出去時仍前進，該帳號日後恢復時會**永遠錯過**這次變動。
        收件人用 `active_recipients`（週期性信件須濾帳號狀態，見其 docstring）。
        """
        doc = "DM-TRAINING-910006"
        owner = await _user(db, "ZT_O6", status="DISABLED")
        await _published_doc(db, doc)
        await _make_chain(db, owner=owner, course_name="停用擁有者的課", doc_id=doc)

        result = await EtDocChangeNotifyService().run(db)
        await db.flush()

        assert result.notified == 0
        assert await _notify_state(db, doc, owner) is None, "沒寄出就不得寫簿記"
