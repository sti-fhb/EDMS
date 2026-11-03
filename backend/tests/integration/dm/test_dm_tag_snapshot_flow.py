"""標籤版本層快照流程整合測試（#377，真實 DB）。

驗證標籤生效時點由「存草稿當下」改為「核准發布當下」：草稿階段的標籤變更存於版本層
（DM_VERSION_TAG），文件層（DM_DOC_TAG，即 visibility 判定依據）僅於核准發布時更新，
退回則完全不套用。推翻 spec_us5 FR-003 原「存檔當下即生效」之設計。
"""

import json

import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dm.catalog.models import DmCategory, DmTag
from app.dm.document.models import DmDocTag, DmVersionTag
from app.dm.editor.service import EditorService
from app.dm.personal.service import PersonalService
from app.dm.review.center_service import ReviewCenterService
from app.dm.roles.authz import DM_EDITOR, DM_REVIEWER
from app.dm.roles.models import DmUserRole
from app.dp.audit.models import DpAuditLog
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration


async def _all_units_id(db):
    """單位組通用值「全單位」＝不限單位（#437 可見對象配對）。"""
    return await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "UNIT", DmTag.tag_name == "全單位"))


_editor = EditorService()
_review = ReviewCenterService()
_PDF = "application/pdf"


@pytest.fixture(autouse=True)
def _storage_root(tmp_path, monkeypatch):
    """落盤根目錄導向 tmp，避免污染工作目錄。"""
    monkeypatch.setattr(settings, "DM_FILE_STORAGE_ROOT", str(tmp_path))


def _op(uid):
    return OperatorInfo(user_id=uid)


async def _seed_user(db, user_id, name):
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@e.com",
            pwd_hash="x",
            user_name=name,
            pwd_changed_date=utcnow(),
            created_user="seed",
            created_date=utcnow(),
        )
    )
    await db.flush()


async def _grant(db, user_id, role):
    db.add(DmUserRole(user_id=user_id, role_code=role, created_user="seed", created_date=utcnow()))
    await db.flush()


async def _two_audience_ids(db) -> tuple[int, int]:
    """取兩個相異之可見對象標籤（不寫死名稱，避免綁定 seed 內容）。"""
    rows = await db.scalars(
        select(DmTag.tag_id).where(DmTag.tag_group_code == "AUDIENCE").order_by(DmTag.tag_id).limit(2)
    )
    ids = list(rows.all())
    assert len(ids) == 2, "seed 需至少 2 個 AUDIENCE 標籤"
    return ids[0], ids[1]


async def _tag_name(db, tag_id: int) -> str:
    return await db.scalar(select(DmTag.tag_name).where(DmTag.tag_id == tag_id))


async def _doc_tag_ids(db, doc_id) -> set[int]:
    """文件層（生效中）之標籤集合。"""
    rows = await db.scalars(select(DmDocTag.tag_id).where(DmDocTag.doc_id == doc_id, DmDocTag.deleted == 0))
    return set(rows.all())


async def _specific_unit_id(db) -> int:
    """取一個具體單位（非通用值「全單位」）。"""
    return await db.scalar(
        select(DmTag.tag_id)
        .where(DmTag.tag_group_code == "UNIT", DmTag.tag_name != "全單位")
        .order_by(DmTag.tag_id)
        .limit(1)
    )


async def _doc_tag_pairs(db, doc_id) -> set[tuple[int, int | None]]:
    """文件層（生效中）之 (TAG_ID, UNIT_TAG_ID) 配對集合。"""
    rows = await db.execute(
        select(DmDocTag.tag_id, DmDocTag.unit_tag_id).where(DmDocTag.doc_id == doc_id, DmDocTag.deleted == 0)
    )
    return {(r[0], r[1]) for r in rows.all()}


async def _version_tag_ids(db, version_id) -> set[int]:
    """版本層（該版本提議）之標籤集合。"""
    rows = await db.scalars(
        select(DmVersionTag.tag_id).where(DmVersionTag.version_id == version_id, DmVersionTag.deleted == 0)
    )
    return set(rows.all())


async def _publish_first_version(db, *, audience_id: int) -> tuple[str, int]:
    """建立文件 + 首版並核准發布，回傳 (doc_id, version_id)。"""
    created = await _editor.create_document(
        db,
        doc_name="標籤快照測試文件",
        category_code="SOP",
        func_code=None,
        audience_unit_ids=[await _all_units_id(db)],
        audience_role_ids=[audience_id],
        retrieval_ids=[],
        version_no="1.0",
        change_summary="首版",
        file_name="v1.pdf",
        file_bytes=b"%PDF-1.4 v1",
        file_mime=_PDF,
        op=_op("ed"),
    )
    submitted = await _editor.submit(
        db, doc_id=created.doc_id, version_id=created.version_id, assigned_reviewer="rev1", op=_op("ed")
    )
    await _review.approve(db, review_id=submitted.review_id, op=_op("rev1"))
    return created.doc_id, created.version_id


async def _seed_editor_and_reviewer(db):
    await _seed_user(db, "ed", "撰寫者")
    await _grant(db, "ed", DM_EDITOR)
    await _seed_user(db, "rev1", "審核者")
    await _grant(db, "rev1", DM_REVIEWER)


async def test_draft_tag_change_does_not_touch_doc_tag(db):
    """AC1：已發布文件開新版改可見對象並存草稿 → 文件層不變、版本層持有新值。"""
    await _seed_editor_and_reviewer(db)
    aud_a, aud_b = await _two_audience_ids(db)
    doc_id, _ = await _publish_first_version(db, audience_id=aud_a)
    assert await _doc_tag_ids(db, doc_id) == {aud_a}

    ver2 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_unit_ids=[await _all_units_id(db)],
        audience_role_ids=[aud_b],  # 改成另一組可見對象
        retrieval_ids=[],
        version_no="2.0",
        change_summary="改版",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )

    # 核心：草稿階段文件層完全不受影響（已發布文件之可見範圍不因存草稿而改變）
    assert await _doc_tag_ids(db, doc_id) == {aud_a}
    assert await _version_tag_ids(db, ver2.version_id) == {aud_b}


async def test_approve_applies_version_tags_to_doc(db):
    """AC2：核准發布後文件層等同該版本之版本層快照。"""
    await _seed_editor_and_reviewer(db)
    aud_a, aud_b = await _two_audience_ids(db)
    doc_id, _ = await _publish_first_version(db, audience_id=aud_a)

    ver2 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_unit_ids=[await _all_units_id(db)],
        audience_role_ids=[aud_b],
        retrieval_ids=[],
        version_no="2.0",
        change_summary="改版",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )
    submitted = await _editor.submit(
        db, doc_id=doc_id, version_id=ver2.version_id, assigned_reviewer="rev1", op=_op("ed")
    )
    await _review.approve(db, review_id=submitted.review_id, op=_op("rev1"))

    assert await _doc_tag_ids(db, doc_id) == {aud_b}


async def test_training_audience_ids_discarded_server_side(db):
    """TRAINING 即使繞過前端帶入 audience_ids，伺服端亦不寫入；送簽不被擋，核准後文件層仍為空。

    spec_us5 FR-009：該分類 MUST NOT 寫入可見對象。前端雖已隱藏欄位，直接呼叫 API 仍須擋下——
    否則核准發布後會套用至文件層，使教材出現在純閱覽者的文件庫檢索結果。
    """
    await _seed_editor_and_reviewer(db)
    aud_a, _ = await _two_audience_ids(db)

    created = await _editor.create_document(
        db,
        doc_name="用血回報訓練教材",
        category_code="TRAINING",
        func_code=None,
        audience_unit_ids=[await _all_units_id(db)],
        audience_role_ids=[aud_a],  # 繞過前端直接帶入
        retrieval_ids=[],
        version_no="1.0",
        change_summary="首版",
        file_name="t.pdf",
        file_bytes=b"%PDF-1.4 t",
        file_mime=_PDF,
        op=_op("ed"),
    )
    assert await _version_tag_ids(db, created.version_id) == set()  # 靜默丟棄

    # 免填可見對象仍可送簽（不擋 DM_DOC_005），核准後文件層維持空集合
    submitted = await _editor.submit(
        db, doc_id=created.doc_id, version_id=created.version_id, assigned_reviewer="rev1", op=_op("ed")
    )
    await _review.approve(db, review_id=submitted.review_id, op=_op("rev1"))

    assert await _doc_tag_ids(db, created.doc_id) == set()


async def test_withdraw_does_not_apply_version_tags(db):
    """撤回送審 MUST NOT 套用標籤——與退回對稱（防日後比照 approve 誤加套用）。"""
    await _seed_editor_and_reviewer(db)
    aud_a, aud_b = await _two_audience_ids(db)
    doc_id, _ = await _publish_first_version(db, audience_id=aud_a)

    ver2 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_unit_ids=[await _all_units_id(db)],
        audience_role_ids=[aud_b],
        retrieval_ids=[],
        version_no="2.0",
        change_summary="改版",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )
    submitted = await _editor.submit(
        db, doc_id=doc_id, version_id=ver2.version_id, assigned_reviewer="rev1", op=_op("ed")
    )
    await PersonalService().withdraw(db, review_id=submitted.review_id, op=_op("ed"))

    assert await _doc_tag_ids(db, doc_id) == {aud_a}  # 文件層不受影響
    assert await _version_tag_ids(db, ver2.version_id) == {aud_b}  # 草稿保留自己的快照


async def test_review_detail_shows_version_snapshot_tags(db):
    """AC6/9：新版本送審之明細，標籤取該版本快照（非文件層現值），並附分類中文名。"""
    await _seed_editor_and_reviewer(db)
    aud_a, aud_b = await _two_audience_ids(db)
    doc_id, _ = await _publish_first_version(db, audience_id=aud_a)

    ver2 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_unit_ids=[await _all_units_id(db)],
        audience_role_ids=[aud_b],
        retrieval_ids=[],
        version_no="2.0",
        change_summary="改版",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )
    submitted = await _editor.submit(
        db, doc_id=doc_id, version_id=ver2.version_id, assigned_reviewer="rev1", op=_op("ed")
    )

    detail = await _review.get_detail(db, review_id=submitted.review_id, op=_op("rev1"))

    # 審核者看到的是「本次送審提議、核准後會生效」的可見對象，而非文件層目前值（aud_a）。
    # 呈現為 (單位, 職位) 配對字串（#437）——多筆配對時拆成兩排標籤會無從對應。
    assert detail.audience_tags == [f"全單位 + {await _tag_name(db, aud_b)}"]
    assert detail.category_name == await db.scalar(
        select(DmCategory.category_name).where(DmCategory.category_code == "SOP")
    )


async def test_submit_blocked_when_version_snapshot_empty(db):
    """送簽檢核確實讀版本層：文件層有可見對象、版本層為空 → 仍擋 DM_DOC_005。

    此即 migration 必須回填在途草稿的原因——檢核來源改為版本層後，改動前既有的草稿若不回填，
    送簽會被誤擋。回填 SQL 本身屬 schema/資料操作，依 sti-testing 不另寫一次性驗收測試。
    """
    await _seed_editor_and_reviewer(db)
    aud_a, _ = await _two_audience_ids(db)
    doc_id, _v1 = await _publish_first_version(db, audience_id=aud_a)
    assert await _doc_tag_ids(db, doc_id) == {aud_a}  # 文件層有值

    ver2 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_unit_ids=[await _all_units_id(db)],
        audience_role_ids=[aud_a],
        retrieval_ids=[],
        version_no="2.0",
        change_summary="改版",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )
    # 模擬「migration 未回填」之在途草稿：抹除該版本快照
    await db.execute(delete(DmVersionTag).where(DmVersionTag.version_id == ver2.version_id))
    await db.flush()

    with pytest.raises(AppError) as exc:
        await _editor.submit(db, doc_id=doc_id, version_id=ver2.version_id, assigned_reviewer="rev1", op=_op("ed"))
    assert exc.value.error_code == "DM_DOC_005"


async def test_reject_keeps_doc_tags_unchanged(db):
    """AC3：送審被退回 → 文件層維持退回前的值，不被草稿值污染。"""
    await _seed_editor_and_reviewer(db)
    aud_a, aud_b = await _two_audience_ids(db)
    doc_id, _ = await _publish_first_version(db, audience_id=aud_a)

    ver2 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_unit_ids=[await _all_units_id(db)],
        audience_role_ids=[aud_b],
        retrieval_ids=[],
        version_no="2.0",
        change_summary="改版",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )
    submitted = await _editor.submit(
        db, doc_id=doc_id, version_id=ver2.version_id, assigned_reviewer="rev1", op=_op("ed")
    )
    await _review.reject(db, review_id=submitted.review_id, reason="可見對象選錯", op=_op("rev1"))

    # 退回不套用：文件層維持原值；草稿保留自己的快照供續編
    assert await _doc_tag_ids(db, doc_id) == {aud_a}
    assert await _version_tag_ids(db, ver2.version_id) == {aud_b}


async def test_同職位換單位_核准後文件層改為新單位(db):
    """AC5（#437）：只換單位、職位不變 → 核准後文件層必須更新為新單位。

    這條專釘**比對鍵**：`set_version_tags` 與 `apply_version_tags_to_doc` 若仍以 `TAG_ID`
    單欄比對，會把「全單位 + 護理師」與「某單位 + 護理師」視為同一列而判定「已存在、不需
    異動」——文件層的單位就停在舊值，且全程不報錯。可見範圍因此與審核者核准的內容不符。
    """
    await _seed_editor_and_reviewer(db)
    role_id, _ = await _two_audience_ids(db)
    all_units = await _all_units_id(db)
    unit_id = await _specific_unit_id(db)
    doc_id, _ = await _publish_first_version(db, audience_id=role_id)
    assert await _doc_tag_pairs(db, doc_id) == {(role_id, all_units)}

    ver2 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_unit_ids=[unit_id],  # 同職位，只換單位
        audience_role_ids=[role_id],
        retrieval_ids=[],
        version_no="2.0",
        change_summary="限縮至特定單位",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )
    submitted = await _editor.submit(
        db, doc_id=doc_id, version_id=ver2.version_id, assigned_reviewer="rev1", op=_op("ed")
    )
    assert await _doc_tag_pairs(db, doc_id) == {(role_id, all_units)}  # 核准前不動

    await _review.approve(db, review_id=submitted.review_id, op=_op("rev1"))

    assert await _doc_tag_pairs(db, doc_id) == {(role_id, unit_id)}


async def test_同職位多單位_並存為兩列(db):
    """AC5（#437）：同一職位掛兩個單位 → 文件層兩列並存，不互相覆蓋。"""
    await _seed_editor_and_reviewer(db)
    role_id, _ = await _two_audience_ids(db)
    all_units = await _all_units_id(db)
    unit_id = await _specific_unit_id(db)
    doc_id, _ = await _publish_first_version(db, audience_id=role_id)

    ver2 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_unit_ids=[all_units, unit_id],
        audience_role_ids=[role_id, role_id],  # 同職位、兩個單位
        retrieval_ids=[],
        version_no="2.0",
        change_summary="兩個單位",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )
    submitted = await _editor.submit(
        db, doc_id=doc_id, version_id=ver2.version_id, assigned_reviewer="rev1", op=_op("ed")
    )
    await _review.approve(db, review_id=submitted.review_id, op=_op("rev1"))

    assert await _doc_tag_pairs(db, doc_id) == {(role_id, all_units), (role_id, unit_id)}


# ─────────────────────────────────────────────────────────────────────────────
# L1-a：停用的標籤不得於核准時產生新的生效引用（#388）
# ─────────────────────────────────────────────────────────────────────────────
#
# ⚠️ 情境是**時間差**造成的，不是驗證漏掉：存草稿當下 `editor/repository.py` 已擋停用標籤
# （`DmTag.is_enabled.is_(True)`），所以必須先存好草稿、**再**停用標籤，才建得出這個狀態。
# 直接用停用的標籤存草稿會在更早的地方就被擋，測不到核准那一段。


async def _disable_tag(db, tag_id: int) -> None:
    """把標籤停用（模擬管理者在草稿送審後執行 soft-retire）。"""
    tag = await db.scalar(select(DmTag).where(DmTag.tag_id == tag_id))
    tag.is_enabled = False
    await db.flush()


async def test_核准時停用的職位不得產生新的生效引用(db):
    """L1：草稿存檔後標籤才被停用 → 核准時不得把它寫進文件層。

    🔴 文件層（`DM_DOC_TAG`）是 `visibility.py` 的判定依據，而 `visibility` **不濾
    `is_enabled`**。所以一旦寫進去，持有該停用標籤的閱覽者就看得到——「保留既有引用」
    是政策，「停用後還能產生**新**引用」不是。
    """
    await _seed_editor_and_reviewer(db)
    aud_a, aud_b = await _two_audience_ids(db)
    doc_id, _ = await _publish_first_version(db, audience_id=aud_a)

    ver2 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_unit_ids=[await _all_units_id(db)],
        audience_role_ids=[aud_b],
        retrieval_ids=[],
        version_no="2.0",
        change_summary="改版",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )
    submitted = await _editor.submit(
        db, doc_id=doc_id, version_id=ver2.version_id, assigned_reviewer="rev1", op=_op("ed")
    )

    # 送審之後、核准之前才停用——這是 L1 的觸發條件
    await _disable_tag(db, aud_b)

    await _review.approve(db, review_id=submitted.review_id, op=_op("rev1"))

    doc_tags = await _doc_tag_pairs(db, doc_id)
    assert all(t != aud_b for t, _ in doc_tags), f"停用的職位 {aud_b} 不得出現在文件層：{doc_tags}"


async def test_核准時停用的單位不得產生新的生效引用(db):
    """L1 的另一半：可見對象是 **(單位, 職位) 配對**，兩個欄位都是 FK → `DM_TAG`。

    只濾 `TAG_ID` 會漏掉「單位被停用」那半——而 `UNIT_TAG_ID` 同樣指向 `DM_TAG.TAG_ID`
    （`document/models.py` 的 `FK_DM_VERSION_TAG_UNIT`）。沒有這條，只檢查職位的實作會過。
    """
    await _seed_editor_and_reviewer(db)
    aud_a, aud_b = await _two_audience_ids(db)
    doc_id, _ = await _publish_first_version(db, audience_id=aud_a)

    unit_id = await _specific_unit_id(db)
    assert unit_id is not None, "測試需要一個非「全單位」的單位標籤——正向錨點，否則下面驗不到東西"

    ver2 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_unit_ids=[unit_id],
        audience_role_ids=[aud_b],
        retrieval_ids=[],
        version_no="2.0",
        change_summary="改版",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )
    submitted = await _editor.submit(
        db, doc_id=doc_id, version_id=ver2.version_id, assigned_reviewer="rev1", op=_op("ed")
    )

    await _disable_tag(db, unit_id)  # 停用的是**單位**那半

    await _review.approve(db, review_id=submitted.review_id, op=_op("rev1"))

    doc_tags = await _doc_tag_pairs(db, doc_id)
    assert all(u != unit_id for _, u in doc_tags), f"停用的單位 {unit_id} 不得出現在文件層：{doc_tags}"


async def test_未停用的配對仍正常生效(db):
    """正向錨點：濾掉停用者不得順手把正常的也濾掉。

    沒有這條，L1 的實作用「永遠不寫入」也會讓上面兩條通過。
    """
    await _seed_editor_and_reviewer(db)
    aud_a, aud_b = await _two_audience_ids(db)
    doc_id, _ = await _publish_first_version(db, audience_id=aud_a)

    ver2 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_unit_ids=[await _all_units_id(db)],
        audience_role_ids=[aud_b],
        retrieval_ids=[],
        version_no="2.0",
        change_summary="改版",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )
    submitted = await _editor.submit(
        db, doc_id=doc_id, version_id=ver2.version_id, assigned_reviewer="rev1", op=_op("ed")
    )
    await _review.approve(db, review_id=submitted.review_id, op=_op("rev1"))

    assert await _doc_tag_pairs(db, doc_id) == {(aud_b, await _all_units_id(db))}


# ─────────────────────────────────────────────────────────────────────────────
# L3：核准稽核要記錄「實際生效的可見範圍」（#388）
# ─────────────────────────────────────────────────────────────────────────────


async def _approve_audit_after(db, doc_id: str) -> dict:
    """取該文件最後一筆 DM-REVIEW UPDATE 稽核的 after_value。"""
    row = await db.scalar(
        select(DpAuditLog)
        .where(DpAuditLog.func_name == "DM-REVIEW", DpAuditLog.target_id == doc_id)
        .order_by(DpAuditLog.log_id.desc())
        .limit(1)
    )
    assert row is not None, f"找不到 {doc_id} 的簽核稽核——正向錨點，否則下面驗不到東西"
    return json.loads(row.after_value) if isinstance(row.after_value, str) else row.after_value


async def test_核准稽核記錄實際生效的可見對象(db):
    """L3：`after_value` 原本只有 review_id / published_version_id / operation。

    可見範圍的變更時點就在核准這一刻，但要回答「這份文件何時對全體可見、誰核准的」
    得另撈 `DM_DOC_TAG` 的 `CREATED_USER` / `UPDATED_DATE`。併入稽核即可直接回答。
    """
    await _seed_editor_and_reviewer(db)
    aud_a, aud_b = await _two_audience_ids(db)
    doc_id, _ = await _publish_first_version(db, audience_id=aud_a)

    ver2 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_unit_ids=[await _all_units_id(db)],
        audience_role_ids=[aud_b],
        retrieval_ids=[],
        version_no="2.0",
        change_summary="改版",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )
    submitted = await _editor.submit(
        db, doc_id=doc_id, version_id=ver2.version_id, assigned_reviewer="rev1", op=_op("ed")
    )
    await _review.approve(db, review_id=submitted.review_id, op=_op("rev1"))

    after = await _approve_audit_after(db, doc_id)
    assert after["published_version_id"] == ver2.version_id, "既有欄位不得被擠掉"
    assert after["audience"] == [[aud_b, await _all_units_id(db)]], f"應記錄實際生效的配對：{after}"


async def test_核准稽核記錄因停用而未生效的配對(db):
    """🔴 C 裁示的可見性落在這裡：核准成功、但不完整，而那個不完整必須留下紀錄。

    ⛔ 不擋下核准（會讓所有在途草稿卡住），改為濾掉並記錄——「朝看得見的失敗倒」。
    沒有這條，L1 的濾除就是一次**靜默**的範圍縮減，事後無從得知發生過。
    """
    await _seed_editor_and_reviewer(db)
    aud_a, aud_b = await _two_audience_ids(db)
    doc_id, _ = await _publish_first_version(db, audience_id=aud_a)
    all_units = await _all_units_id(db)

    ver2 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_unit_ids=[all_units],
        audience_role_ids=[aud_b],
        retrieval_ids=[],
        version_no="2.0",
        change_summary="改版",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )
    submitted = await _editor.submit(
        db, doc_id=doc_id, version_id=ver2.version_id, assigned_reviewer="rev1", op=_op("ed")
    )
    await _disable_tag(db, aud_b)
    await _review.approve(db, review_id=submitted.review_id, op=_op("rev1"))

    after = await _approve_audit_after(db, doc_id)
    assert after["audience_skipped"] == [[aud_b, all_units]], f"應記錄被濾掉的配對：{after}"


async def test_全數生效時不留空的跳過欄位(db):
    """正向錨點：沒有東西被濾掉時，`audience_skipped` 不該出現。

    否則每筆稽核都帶一個空清單，讀的人會以為「有這個欄位＝有東西被濾」，
    而真正該被注意的那一筆就淹沒在雜訊裡。
    """
    await _seed_editor_and_reviewer(db)
    aud_a, _ = await _two_audience_ids(db)
    doc_id, _ = await _publish_first_version(db, audience_id=aud_a)

    after = await _approve_audit_after(db, doc_id)
    assert "audience_skipped" not in after, f"全數生效時不應有此欄位：{after}"


# ─────────────────────────────────────────────────────────────────────────────
# L4：新版本送審時併列「目前生效」與「本次提議」（#388）
# ─────────────────────────────────────────────────────────────────────────────


async def _submit_new_version(db, doc_id: str, *, unit_ids: list[int], role_ids: list[int]) -> int:
    ver = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_unit_ids=unit_ids,
        audience_role_ids=role_ids,
        retrieval_ids=[],
        version_no="2.0",
        change_summary="改版",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )
    submitted = await _editor.submit(
        db, doc_id=doc_id, version_id=ver.version_id, assigned_reviewer="rev1", op=_op("ed")
    )
    return submitted.review_id


async def test_新版本送審之明細併列目前生效的可見對象(db):
    """長壽草稿會靜默把可見範圍改回較寬的舊值（「後核准者勝」，#377 規劃第 10 節）。

    審核者光看「本次提議」無從判斷這是擴大還是縮小——他需要同時看到目前生效值。
    ⛔ 此處**不**做快照基準比對、也不擋核准（該機制已於 #377 第 10 節裁示不做），
    只是把判斷所需的另一半資訊攤在同一個畫面上。
    """
    await _seed_editor_and_reviewer(db)
    aud_a, aud_b = await _two_audience_ids(db)
    doc_id, _ = await _publish_first_version(db, audience_id=aud_a)
    all_units = await _all_units_id(db)

    review_id = await _submit_new_version(db, doc_id, unit_ids=[all_units], role_ids=[aud_b])

    detail = await _review.get_detail(db, review_id=review_id, op=_op("rev1"))

    assert detail.audience_tags == [f"全單位 + {await _tag_name(db, aud_b)}"], "本次提議值不得被擠掉"
    assert detail.current_audience_tags == [f"全單位 + {await _tag_name(db, aud_a)}"], "應併列目前生效值"


async def test_可見對象未變動時不併列目前生效(db):
    """正向錨點的反面：相同時不顯示。

    若每次都併列，「有這兩排」就不再是訊號，真正改動了可見範圍的那一次會淹沒在例行畫面裡。
    撰寫者多數改版不動可見對象，故這才是常態。
    """
    await _seed_editor_and_reviewer(db)
    aud_a, _ = await _two_audience_ids(db)
    doc_id, _ = await _publish_first_version(db, audience_id=aud_a)
    all_units = await _all_units_id(db)

    review_id = await _submit_new_version(db, doc_id, unit_ids=[all_units], role_ids=[aud_a])

    detail = await _review.get_detail(db, review_id=review_id, op=_op("rev1"))

    assert detail.audience_tags == [f"全單位 + {await _tag_name(db, aud_a)}"]
    assert detail.current_audience_tags is None, "與提議值相同時不應併列"


async def test_首版送審沒有目前生效值可併列(db):
    """`NEW`（首版）之文件層本來就是空的，併列一排「目前生效：—」只是雜訊。

    ⚠️ `None` 與 `[]` 不同義：`None` ＝不必比對（相同 / 首版 / 廢止類），
    `[]` ＝目前生效為空但本次提議非空——那是**擴大**，必須顯示。
    """
    await _seed_editor_and_reviewer(db)
    aud_a, _ = await _two_audience_ids(db)
    created = await _editor.create_document(
        db,
        doc_name="ZT首版併列",
        category_code="SOP",
        func_code=None,
        audience_unit_ids=[await _all_units_id(db)],
        audience_role_ids=[aud_a],
        retrieval_ids=[],
        version_no="1.0",
        change_summary="首版",
        file_name="v1.pdf",
        file_bytes=b"%PDF-1.4 v1",
        file_mime=_PDF,
        op=_op("ed"),
    )
    submitted = await _editor.submit(
        db, doc_id=created.doc_id, version_id=created.version_id, assigned_reviewer="rev1", op=_op("ed")
    )

    detail = await _review.get_detail(db, review_id=submitted.review_id, op=_op("rev1"))

    assert detail.review_type == "NEW"
    assert detail.current_audience_tags is None, "首版無目前生效值，不應併列"


async def test_停用標籤的既有生效引用不得因核准而被收回(db):
    """🔴 驗證 code review 指出的 HIGH：L1-a 的濾除會不會順手撤銷**既有**引用？

    政策是「停用採 soft-retire，既有 `DM_DOC_TAG` 列保留、不收回可見性」
    （`catalog/service.py` docstring、data-model.md DM_TAG 節）。L1-a 要擋的是**新**引用。

    情境：v1 已生效 (A, 全單位)；v2 草稿由現值預帶、快照仍含 A（`get_doc_tags` 不濾
    `is_enabled`，#602/#624「預帶不濾、寫入濾」）；送審後管理者才停用 A。
    """
    await _seed_editor_and_reviewer(db)
    aud_a, aud_b = await _two_audience_ids(db)
    doc_id, _ = await _publish_first_version(db, audience_id=aud_a)
    all_units = await _all_units_id(db)

    ver2 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_unit_ids=[all_units, all_units],
        audience_role_ids=[aud_a, aud_b],  # 預帶的 A + 本次新增的 B（兩清單平行配對）
        retrieval_ids=[],
        version_no="2.0",
        change_summary="改版",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )
    submitted = await _editor.submit(
        db, doc_id=doc_id, version_id=ver2.version_id, assigned_reviewer="rev1", op=_op("ed")
    )
    await _disable_tag(db, aud_a)  # 送審之後才停用——寫入時的檢核已經過了
    await _review.approve(db, review_id=submitted.review_id, op=_op("rev1"))

    pairs = await _doc_tag_pairs(db, doc_id)
    assert (aud_a, all_units) in pairs, "既有生效引用不得被收回——soft-retire 政策是『不收回既有可見性』"
    assert (aud_b, all_units) in pairs, "未停用的配對應正常生效（正向錨點）"


async def _third_audience_id(db) -> int:
    """取第三個可見對象標籤；seed 不足時自建一個 ZT 前綴的。"""
    ids = list((await db.scalars(
        select(DmTag.tag_id).where(DmTag.tag_group_code == "AUDIENCE").order_by(DmTag.tag_id).limit(3)
    )).all())
    if len(ids) >= 3:
        return ids[2]
    tag = DmTag(tag_group_code="AUDIENCE", tag_name="ZT第三個職位", created_user="e", created_date=utcnow())
    db.add(tag)
    await db.flush()
    return tag.tag_id


async def test_同一次核准中既有停用配對保留而新增停用配對被擋(db):
    """混合情境：一次核准同時出現三種配對，三種結果必須各自正確。

    只測單一種類的話，「整批不寫入」或「整批照寫」都可能矇混過關——
    前者會讓正常配對消失，後者讓停用配對生效，而兩種都有一半的斷言會過。
    """
    await _seed_editor_and_reviewer(db)
    aud_a, aud_b = await _two_audience_ids(db)
    aud_c = await _third_audience_id(db)
    doc_id, _ = await _publish_first_version(db, audience_id=aud_a)
    all_units = await _all_units_id(db)

    ver2 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_unit_ids=[all_units, all_units, all_units],
        audience_role_ids=[aud_a, aud_b, aud_c],
        retrieval_ids=[],
        version_no="2.0",
        change_summary="改版",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )
    submitted = await _editor.submit(
        db, doc_id=doc_id, version_id=ver2.version_id, assigned_reviewer="rev1", op=_op("ed")
    )
    await _disable_tag(db, aud_a)  # 既有且已生效 → 保留
    await _disable_tag(db, aud_c)  # 本次才新增 → 擋下
    await _review.approve(db, review_id=submitted.review_id, op=_op("rev1"))

    pairs = await _doc_tag_pairs(db, doc_id)
    assert (aud_a, all_units) in pairs, "既有生效引用：保留"
    assert (aud_b, all_units) in pairs, "未停用之新配對：生效"
    assert (aud_c, all_units) not in pairs, "停用且既有沒有的配對：擋下"

    after = await _approve_audit_after(db, doc_id)
    assert after["audience_skipped"] == [[aud_c, all_units]], f"只有真正被擋的才算跳過：{after}"
    assert sorted(after["audience"]) == sorted([[aud_a, all_units], [aud_b, all_units]]), (
        f"稽核的生效範圍應含被保留的既有配對：{after}"
    )


async def test_同職位多單位且內容未變時不併列(db):
    """L4 的相同判定**不可依賴排序**：兩邊查的是不同的表（`DM_DOC_TAG` / `DM_VERSION_TAG`）。

    「同職位多單位」是合法資料（見 `test_同職位多單位_並存為兩列`），此時只靠 `TAG_ID`
    排序無法決定兩列的先後。若以 list 直接比對，內容相同但順序不同就會誤判為「相異」而
    多出一排——正好打掉「常態不出現」的設計。
    """
    await _seed_editor_and_reviewer(db)
    role_id, _ = await _two_audience_ids(db)
    all_units = await _all_units_id(db)
    unit_id = await _specific_unit_id(db)
    doc_id, _ = await _publish_first_version(db, audience_id=role_id)

    # v2：兩個單位共用同一職位，核准後文件層有兩列
    ver2 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_unit_ids=[all_units, unit_id],
        audience_role_ids=[role_id, role_id],
        retrieval_ids=[],
        version_no="2.0",
        change_summary="兩個單位",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )
    s2 = await _editor.submit(db, doc_id=doc_id, version_id=ver2.version_id, assigned_reviewer="rev1", op=_op("ed"))
    await _review.approve(db, review_id=s2.review_id, op=_op("rev1"))

    # v3：可見對象原封不動送審
    ver3 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_unit_ids=[all_units, unit_id],
        audience_role_ids=[role_id, role_id],
        retrieval_ids=[],
        version_no="3.0",
        change_summary="只改內文",
        file_name="v3.pdf",
        file_bytes=b"%PDF-1.4 v3",
        file_mime=_PDF,
        op=_op("ed"),
    )
    s3 = await _editor.submit(db, doc_id=doc_id, version_id=ver3.version_id, assigned_reviewer="rev1", op=_op("ed"))

    detail = await _review.get_detail(db, review_id=s3.review_id, op=_op("rev1"))

    assert len(detail.audience_tags) == 2, "正向錨點：確實是同職位兩單位的情境"
    assert detail.current_audience_tags is None, "可見對象未變，不應因排序差異而誤判為相異"


async def test_停用標籤的既有引用已被移除者不得復活(db):
    """「保留既有有效列」的邊界：既有列是 `deleted=1`（曾經掛過、後來被移除）時**不得**復活。

    讓它復活等同產生一筆新的生效引用——正是 L1-a 要擋的那件事。這條與
    `test_停用標籤的既有生效引用不得因核准而被收回` 是同一個判斷的兩側，
    差別只在既有列的 `DELETED`；少了這條，把 `row.deleted == 0` 條件拿掉不會有人發現。
    """
    await _seed_editor_and_reviewer(db)
    aud_a, aud_b = await _two_audience_ids(db)
    doc_id, _ = await _publish_first_version(db, audience_id=aud_a)
    all_units = await _all_units_id(db)

    # v2 把可見對象換成 B → A 的文件層列轉為 deleted=1
    ver2 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_unit_ids=[all_units],
        audience_role_ids=[aud_b],
        retrieval_ids=[],
        version_no="2.0",
        change_summary="換對象",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )
    s2 = await _editor.submit(db, doc_id=doc_id, version_id=ver2.version_id, assigned_reviewer="rev1", op=_op("ed"))
    await _review.approve(db, review_id=s2.review_id, op=_op("rev1"))
    assert (aud_a, all_units) not in await _doc_tag_pairs(db, doc_id), "前置：A 的列已被軟刪除"

    # v3 又把 A 加回來（此時 A 仍啟用，寫入檢核過得了），送審後才停用 A
    ver3 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_unit_ids=[all_units, all_units],
        audience_role_ids=[aud_a, aud_b],
        retrieval_ids=[],
        version_no="3.0",
        change_summary="加回 A",
        file_name="v3.pdf",
        file_bytes=b"%PDF-1.4 v3",
        file_mime=_PDF,
        op=_op("ed"),
    )
    s3 = await _editor.submit(db, doc_id=doc_id, version_id=ver3.version_id, assigned_reviewer="rev1", op=_op("ed"))
    await _disable_tag(db, aud_a)
    await _review.approve(db, review_id=s3.review_id, op=_op("rev1"))

    pairs = await _doc_tag_pairs(db, doc_id)
    assert (aud_a, all_units) not in pairs, "已移除的停用配對不得復活——復活即是新的生效引用"
    assert (aud_b, all_units) in pairs, "正向錨點：未停用者照常生效"
    after = await _approve_audit_after(db, doc_id)
    assert after["audience_skipped"] == [[aud_a, all_units]], f"被擋下的要留痕：{after}"
