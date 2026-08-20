"""跨模組教材引用（US12 / SRVDM001 · SRVDM002 · 取檔）整合測試（真實 DB）。

驗證：SRVDM001 取當前發布版 / 廢止仍回最後版 / 無發布版擋；SRVDM002 分類清單過濾（含
PENDING_OBSOLETE、排除 OBSOLETE / 草稿 / 送審）+ keyword + func_code + 發布時間 DESC + 分類無效擋；
取檔不掛角色閘、只給目前版、不寫 DM_DOC_READ、OBSOLETE 仍可取；門面自 app/services 匯出。
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.exceptions import AppError
from app.core.utils import utcnow
from app.dm.catalog.models import DmFunc
from app.dm.document.models import DmDocRead, DmDocument, DmDocVersion
from app.dm.integration.service import DmDocumentService

pytestmark = pytest.mark.integration

_svc = DmDocumentService()


async def _version(db, doc_id, version_no, *, status="PUBLISHED", has_file=True, published=None, author="ed"):
    now = utcnow()
    v = DmDocVersion(
        doc_id=doc_id,
        version_no=version_no,
        change_summary="摘要",
        file_name=f"{version_no}.pdf" if has_file else None,
        file_path=f"/x/{doc_id}-{version_no}.pdf" if has_file else None,
        file_size=100 if has_file else None,
        file_mime="application/pdf" if has_file else None,
        status=status,
        published_date=published or now,
        created_user=author,
        created_date=now,
    )
    db.add(v)
    await db.flush()
    return v.version_id


async def _doc(
    db,
    doc_id,
    *,
    category="TRAINING",
    status="PUBLISHED",
    current_version_id=None,
    func_code=None,
    name="教材",
    author="ed",
):
    now = utcnow()
    db.add(
        DmDocument(
            doc_id=doc_id,
            doc_name=name,
            category_code=category,
            func_code=func_code,
            current_version_id=current_version_id,
            status=status,
            created_user=author,
            created_date=now,
        )
    )
    await db.flush()


async def _published_doc(
    db,
    doc_id,
    *,
    category="TRAINING",
    version_no="v1.0",
    status="PUBLISHED",
    func_code=None,
    name="教材",
    published=None,
    has_file=True,
):
    """建已發布文件（doc + PUBLISHED 版本 + current_version_id 指向該版）。"""
    await _doc(db, doc_id, category=category, status=status, func_code=func_code, name=name)
    vid = await _version(db, doc_id, version_no, status="PUBLISHED", published=published, has_file=has_file)
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == doc_id))
    doc.current_version_id = vid
    await db.flush()
    return vid


# ── SRVDM001：get_current_by_doc_id ──────────────────


async def test_current_published(db):
    await _published_doc(db, "DM-TRAINING-000001", version_no="v2.0")
    r = await _svc.get_current_by_doc_id(db, "DM-TRAINING-000001")
    assert r.version_no == "v2.0" and r.status == "PUBLISHED" and r.obsolete is False
    assert r.category_code == "TRAINING" and r.file_name == "v2.0.pdf"


async def test_current_obsolete_still_returns_last_version(db):
    """廢止（文件層 OBSOLETE、版本仍 PUBLISHED）→ obsolete=true 且仍回最後發布版。"""
    vid = await _published_doc(db, "DM-TRAINING-000002", version_no="v1.5", status="OBSOLETE")
    r = await _svc.get_current_by_doc_id(db, "DM-TRAINING-000002")
    assert r.obsolete is True and r.status == "OBSOLETE"
    assert r.current_version_id == vid and r.version_no == "v1.5"


async def test_current_no_published_version_blocked(db):
    """草稿（尚無 current_version_id）→ DM_DOC_013。"""
    await _doc(db, "DM-TRAINING-000003", status="DRAFT", current_version_id=None)
    with pytest.raises(AppError) as e:
        await _svc.get_current_by_doc_id(db, "DM-TRAINING-000003")
    assert e.value.error_code == "DM_DOC_013" and e.value.status_code == 409


async def test_current_not_found(db):
    with pytest.raises(AppError) as e:
        await _svc.get_current_by_doc_id(db, "DM-TRAINING-999999")
    assert e.value.error_code == "DM_DOC_001" and e.value.status_code == 404


async def test_current_returns_latest_after_new_publish(db):
    """發布新版（current_version_id 改指新版）→ 下次取得最新版（無快取）。"""
    await _published_doc(db, "DM-TRAINING-000004", version_no="v1.0")
    v2 = await _version(db, "DM-TRAINING-000004", "v2.0", status="PUBLISHED")
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == "DM-TRAINING-000004"))
    doc.current_version_id = v2
    await db.flush()
    r = await _svc.get_current_by_doc_id(db, "DM-TRAINING-000004")
    assert r.current_version_id == v2 and r.version_no == "v2.0"


# ── SRVDM002：list_training_documents ─────────────────


async def test_list_filters_status_and_category(db):
    """僅列 TRAINING 有當前發布版且在架（含 PENDING_OBSOLETE、排除 OBSOLETE / 草稿 / 送審 / 他分類）。"""
    await _published_doc(db, "DM-TRAINING-000010", name="A", published=utcnow())
    await _published_doc(db, "DM-TRAINING-000011", name="B", status="PENDING_OBSOLETE")  # 仍在架 → 列
    await _published_doc(db, "DM-TRAINING-000012", name="C", status="OBSOLETE")  # 廢止 → 不列
    await _doc(db, "DM-TRAINING-000013", status="DRAFT", current_version_id=None, name="D")  # 草稿 → 不列
    await _published_doc(db, "DM-SOP-000014", category="SOP", name="E")  # 他分類 → 不列
    items = await _svc.list_training_documents(db, category="TRAINING")
    names = {i.doc_name for i in items}
    assert names == {"A", "B"}


async def test_list_keyword_filter(db):
    await _published_doc(db, "DM-TRAINING-000020", name="用血回報教材", published=utcnow())
    await _published_doc(db, "DM-TRAINING-000021", name="成分製備教材", published=utcnow())
    items = await _svc.list_training_documents(db, keyword="用血")
    assert [i.doc_name for i in items] == ["用血回報教材"]


async def test_list_desc_order_by_published_date(db):
    """多筆不同發布時間 → 發布時間 DESC（新者在前）。"""
    base = utcnow()
    await _published_doc(db, "DM-TRAINING-000050", name="舊", published=base - timedelta(days=2))
    await _published_doc(db, "DM-TRAINING-000051", name="新", published=base)
    items = await _svc.list_training_documents(db)
    assert [i.doc_name for i in items] == ["新", "舊"]


async def test_list_tiebreak_by_doc_id(db):
    """同秒發布 → 次要鍵 doc_id 確保排序穩定。"""
    t = utcnow()
    await _published_doc(db, "DM-TRAINING-000061", name="B", published=t)
    await _published_doc(db, "DM-TRAINING-000060", name="A", published=t)
    items = await _svc.list_training_documents(db)
    assert [i.doc_id for i in items] == ["DM-TRAINING-000060", "DM-TRAINING-000061"]


async def test_list_func_code_filter(db):
    now = utcnow()
    db.add_all(
        [
            DmFunc(func_code="BS04", func_name="領血確認", created_user="seed", created_date=now),
            DmFunc(func_code="BS05", func_name="用血回報", created_user="seed", created_date=now),
        ]
    )
    await db.flush()
    await _published_doc(db, "DM-TRAINING-000030", name="F1", func_code="BS04")
    await _published_doc(db, "DM-TRAINING-000031", name="F2", func_code="BS05")
    items = await _svc.list_training_documents(db, func_code="BS04")
    assert [i.doc_name for i in items] == ["F1"]


async def test_list_non_referenceable_category_blocked(db):
    """不存在（NOPE）與存在但非可引用分類（SOP）皆擋 DM_DOC_010。"""
    await _published_doc(db, "DM-SOP-000045", category="SOP", name="SOP文件")  # 存在但不可引用
    for cat in ("NOPE", "SOP"):
        with pytest.raises(AppError) as e:
            await _svc.list_training_documents(db, category=cat)
        assert e.value.error_code == "DM_DOC_010" and e.value.status_code == 422


# ── read_file_for_reference ──────────────────────────


async def test_read_file_current_success_no_role(db):
    """不需任何 DM 角色設定即可取當前版檔（授權由 ET 自判）。"""
    vid = await _published_doc(db, "DM-TRAINING-000040", version_no="v1.0")
    f = await _svc.read_file_for_reference(db, doc_id="DM-TRAINING-000040", version_id=vid)
    assert f.path.endswith("v1.0.pdf") and f.mime == "application/pdf" and f.name == "v1.0.pdf"


async def test_read_file_non_current_blocked(db):
    """非目前發布版（D-1）→ DM_DOC_002。"""
    await _published_doc(db, "DM-TRAINING-000041", version_no="v2.0")
    old = await _version(db, "DM-TRAINING-000041", "v1.0", status="SUPERSEDED")
    with pytest.raises(AppError) as e:
        await _svc.read_file_for_reference(db, doc_id="DM-TRAINING-000041", version_id=old)
    assert e.value.error_code == "DM_DOC_002" and e.value.status_code == 403


async def test_read_file_missing_file_404(db):
    vid = await _published_doc(db, "DM-TRAINING-000042", version_no="v1.0", has_file=False)
    with pytest.raises(AppError) as e:
        await _svc.read_file_for_reference(db, doc_id="DM-TRAINING-000042", version_id=vid)
    assert e.value.error_code == "DM_DOC_001"


async def test_read_file_does_not_write_dm_doc_read(db):
    """D-2：ET 取檔不寫 DM_DOC_READ（不計入 DM 閱讀統計）。"""
    vid = await _published_doc(db, "DM-TRAINING-000043", version_no="v1.0")
    before = await db.scalar(select(func.count()).select_from(DmDocRead))
    await _svc.read_file_for_reference(db, doc_id="DM-TRAINING-000043", version_id=vid)
    after = await db.scalar(select(func.count()).select_from(DmDocRead))
    assert after == before


async def test_read_file_obsolete_still_readable(db):
    """廢止文件之當前版（廢止前最後版）仍可取（FR-003 學員仍可閱讀）。"""
    vid = await _published_doc(db, "DM-TRAINING-000044", version_no="v1.5", status="OBSOLETE")
    f = await _svc.read_file_for_reference(db, doc_id="DM-TRAINING-000044", version_id=vid)
    assert f.path.endswith("v1.5.pdf")


# ── 分類白名單：跨分類越權防線（Sec HIGH-1）────────────


async def test_read_file_non_referenceable_category_blocked(db):
    """以他分類（SOP）doc_id 取檔 → 擋（回 404 不洩漏），防跨分類枚舉取檔。"""
    vid = await _published_doc(db, "DM-SOP-000070", category="SOP", version_no="v1.0")
    with pytest.raises(AppError) as e:
        await _svc.read_file_for_reference(db, doc_id="DM-SOP-000070", version_id=vid)
    assert e.value.error_code == "DM_DOC_001" and e.value.status_code == 404


async def test_current_non_referenceable_category_blocked(db):
    """以他分類（SOP）doc_id 取 metadata → 擋（回 404 不洩漏）。"""
    await _published_doc(db, "DM-SOP-000071", category="SOP", version_no="v1.0")
    with pytest.raises(AppError) as e:
        await _svc.get_current_by_doc_id(db, "DM-SOP-000071")
    assert e.value.error_code == "DM_DOC_001" and e.value.status_code == 404


# ── 邊界隔離：門面經 app/services 匯出 ────────────────


def test_service_exported_from_app_services():
    from app.services import DmDocumentService as Exported

    assert Exported is DmDocumentService
