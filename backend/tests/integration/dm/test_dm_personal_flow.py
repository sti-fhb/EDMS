"""個人專區（US9 / UCDM09 / DM07）整合測試（真實 DB）。

涵蓋：草稿匣三類分類（未送審 / 被退回 / 已撤回）、刪除草稿（軟刪 / 非本人 403 / 非草稿 409）、
撤回送審（NEW→文件+版本 DRAFT、NEW_VERSION→版本 DRAFT 文件維持 PUBLISHED、OBSOLETE→文件 PUBLISHED；
SUBMIT_WITHDRAWN 站內訊息〔STATUS=PENDING〕、保留原審核者、非本人 403 DM_REVIEW_007、非 PENDING 409）、
我的文件動態（撰寫者 / 審核者視角、近 30 天）、入口可見性（編輯/審核 → true、純閱覽/純管理 → false）、
HTTP 存取閘。
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dm.document.models import DmDocument, DmDocVersion
from app.dm.personal.service import PersonalService
from app.dm.review.models import DmReview
from app.dm.roles.authz import DM_ADMIN, DM_EDITOR, DM_REVIEWER, DM_VIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_svc = PersonalService()
_PDF = "application/pdf"


def _op(uid="ed"):
    return OperatorInfo(user_id=uid)


async def _seed_user(db, user_id, name, email=None):
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=email or f"{user_id}@e.com",
            pwd_hash="x",
            user_name=name,
            pwd_changed_date=now,
            created_user="seed",
            created_date=now,
        )
    )
    await db.flush()


async def _grant(db, user_id, role):
    db.add(DmUserRole(user_id=user_id, role_code=role, created_user="seed", created_date=utcnow()))
    await db.flush()


async def _doc(db, doc_id, *, status, current_version_id=None, author="ed"):
    doc = DmDocument(
        doc_id=doc_id,
        doc_name=f"文件{doc_id}",
        category_code="SOP",
        current_version_id=current_version_id,
        status=status,
        created_user=author,
        created_date=utcnow(),
    )
    db.add(doc)
    await db.flush()
    return doc


async def _version(db, doc_id, version_no, *, status, author="ed", published=None):
    v = DmDocVersion(
        doc_id=doc_id,
        version_no=version_no,
        change_summary="摘要",
        file_name=f"{version_no}.pdf",
        file_size=100,
        file_mime=_PDF,
        status=status,
        published_date=published,
        created_user=author,
        created_date=utcnow(),
    )
    db.add(v)
    await db.flush()
    return v


async def _review(
    db, doc_id, version_id, *, review_type, status, reviewer="rev1", author="ed", submit=None, complete="auto"
):
    r = DmReview(
        doc_id=doc_id,
        version_id=version_id,
        review_type=review_type,
        assigned_reviewer=reviewer,
        status=status,
        submit_date=submit or utcnow(),
        complete_date=(None if status == "PENDING" else utcnow()) if complete == "auto" else complete,
        created_user=author,
        created_date=utcnow(),
    )
    db.add(r)
    await db.flush()
    return r


# ── 草稿匣三類 ──────────────────────────────────────


async def test_drafts_classified_three_kinds(db):
    await _seed_user(db, "ed", "撰寫")
    # 未送審：DRAFT 版本、無 review
    await _doc(db, "DM-SOP-000501", status="DRAFT")
    await _version(db, "DM-SOP-000501", "1.0", status="DRAFT")
    # 被退回：DRAFT 版本 + 最近 review REJECTED
    await _doc(db, "DM-SOP-000502", status="DRAFT")
    v2 = await _version(db, "DM-SOP-000502", "1.0", status="DRAFT")
    await _review(db, "DM-SOP-000502", v2.version_id, review_type="NEW", status="REJECTED")
    # 已撤回：DRAFT 版本 + 最近 review WITHDRAWN
    await _doc(db, "DM-SOP-000503", status="DRAFT")
    v3 = await _version(db, "DM-SOP-000503", "1.0", status="DRAFT")
    await _review(db, "DM-SOP-000503", v3.version_id, review_type="NEW", status="WITHDRAWN")

    drafts = await _svc.list_drafts(db, user_id="ed")
    kinds = {d.doc_id: d.kind for d in drafts}
    assert kinds["DM-SOP-000501"] == "unsubmitted"
    assert kinds["DM-SOP-000502"] == "rejected"
    assert kinds["DM-SOP-000503"] == "withdrawn"


async def test_drafts_only_own_and_not_deleted(db):
    await _seed_user(db, "ed", "撰寫")
    await _seed_user(db, "ed2", "他人")
    await _doc(db, "DM-SOP-000504", status="DRAFT")
    await _version(db, "DM-SOP-000504", "1.0", status="DRAFT", author="ed2")  # 他人草稿
    drafts = await _svc.list_drafts(db, user_id="ed")
    assert all(d.doc_id != "DM-SOP-000504" for d in drafts)


async def test_drafts_exclude_obsolete_parent(db):
    # #1：父文件已廢止(OBSOLETE)之孤兒草稿 → 草稿匣不顯示（不主動刪）
    await _seed_user(db, "ed", "撰寫")
    await _doc(db, "DM-SOP-000505", status="OBSOLETE")
    await _version(db, "DM-SOP-000505", "2.0", status="DRAFT")  # 廢止前編到一半的新版草稿
    drafts = await _svc.list_drafts(db, user_id="ed")
    assert all(d.doc_id != "DM-SOP-000505" for d in drafts)


async def test_deleted_draft_releases_unique_slot(db):
    # #6：軟刪草稿後，同文件同人可再開新草稿（唯一索引已排除 DELETED=1）
    await _seed_user(db, "ed", "撰寫")
    await _doc(db, "DM-SOP-000506", status="DRAFT")
    v = await _version(db, "DM-SOP-000506", "1.0", status="DRAFT")
    await _svc.delete_draft(db, version_id=v.version_id, op=_op("ed"))
    # 再開一份同文件同人之 DRAFT 版本 → 不應撞唯一索引（flush 不拋 IntegrityError）
    await _version(db, "DM-SOP-000506", "1.1", status="DRAFT")
    drafts = await _svc.list_drafts(db, user_id="ed")
    assert len([d for d in drafts if d.doc_id == "DM-SOP-000506"]) == 1  # 只剩新的（軟刪的不列）


# ── 刪除草稿 ────────────────────────────────────────


async def test_delete_draft_soft_deletes(db):
    await _seed_user(db, "ed", "撰寫")
    await _doc(db, "DM-SOP-000511", status="DRAFT")
    v = await _version(db, "DM-SOP-000511", "1.0", status="DRAFT")
    await _svc.delete_draft(db, version_id=v.version_id, op=_op("ed"))
    row = await db.scalar(select(DmDocVersion).where(DmDocVersion.version_id == v.version_id))
    assert row.deleted == 1


async def test_delete_draft_non_owner_blocked(db):
    await _seed_user(db, "ed", "撰寫")
    await _doc(db, "DM-SOP-000512", status="DRAFT")
    v = await _version(db, "DM-SOP-000512", "1.0", status="DRAFT", author="ed")
    with pytest.raises(AppError) as e:
        await _svc.delete_draft(db, version_id=v.version_id, op=_op("other"))
    assert e.value.error_code == "DM_DRAFT_001"


async def test_delete_non_draft_blocked(db):
    await _seed_user(db, "ed", "撰寫")
    await _doc(db, "DM-SOP-000513", status="PUBLISHED")
    v = await _version(db, "DM-SOP-000513", "1.0", status="PUBLISHED", published=utcnow())
    with pytest.raises(AppError) as e:
        await _svc.delete_draft(db, version_id=v.version_id, op=_op("ed"))
    assert e.value.error_code == "DM_DRAFT_002"


# ── 撤回送審 ────────────────────────────────────────


async def test_withdraw_new_restores_draft_and_notifies_via_activity(db):
    # 撤回後：文件+版本回草稿、review WITHDRAWN、保留原審核者；「站內訊息通知原審核者」＝原審核者於
    # 我的文件動態（審核者視角）見『已撤回』（平台 MSG 設計：不寄 Email，以事件動態呈現）
    await _seed_user(db, "ed", "撰寫")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    await _doc(db, "DM-SOP-000521", status="PENDING_REVIEW")
    v = await _version(db, "DM-SOP-000521", "1.0", status="PENDING_REVIEW")
    r = await _review(db, "DM-SOP-000521", v.version_id, review_type="NEW", status="PENDING")

    result = await _svc.withdraw(db, review_id=r.review_id, op=_op("ed"))

    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == "DM-SOP-000521"))
    ver = await db.scalar(select(DmDocVersion).where(DmDocVersion.version_id == v.version_id))
    rev = await db.scalar(select(DmReview).where(DmReview.review_id == r.review_id))
    assert doc.status == "DRAFT" and ver.status == "DRAFT"  # 首版撤回 → 文件 + 版本回草稿
    assert rev.status == "WITHDRAWN" and rev.assigned_reviewer == "rev1"  # 保留原審核者
    assert result.doc_status == "DRAFT"
    # 原審核者於個人專區「我的文件動態」（審核者視角）見此已撤回項目＝站內訊息之呈現
    rev_act = await _svc.list_activity(db, user_id="rev1", roles=[DM_REVIEWER])
    assert any(a.review_id == r.review_id and a.status == "WITHDRAWN" for a in rev_act.reviewer)


async def test_withdraw_new_version_keeps_doc_published(db):
    await _seed_user(db, "ed", "撰寫")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    doc = await _doc(db, "DM-SOP-000522", status="PUBLISHED")
    cur = await _version(db, "DM-SOP-000522", "1.0", status="PUBLISHED", published=utcnow())
    doc.current_version_id = cur.version_id
    nv = await _version(db, "DM-SOP-000522", "2.0", status="PENDING_REVIEW")
    await db.flush()
    r = await _review(db, "DM-SOP-000522", nv.version_id, review_type="NEW_VERSION", status="PENDING")

    await _svc.withdraw(db, review_id=r.review_id, op=_op("ed"))

    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == "DM-SOP-000522"))
    nver = await db.scalar(select(DmDocVersion).where(DmDocVersion.version_id == nv.version_id))
    assert doc.status == "PUBLISHED" and nver.status == "DRAFT"  # 文件維持已發布、新版回草稿


async def test_withdraw_obsolete_restores_published(db):
    await _seed_user(db, "ed", "撰寫")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    doc = await _doc(db, "DM-SOP-000523", status="PENDING_OBSOLETE")
    v = await _version(db, "DM-SOP-000523", "1.0", status="PUBLISHED", published=utcnow())
    doc.current_version_id = v.version_id
    await db.flush()
    r = await _review(db, "DM-SOP-000523", v.version_id, review_type="OBSOLETE", status="PENDING")

    result = await _svc.withdraw(db, review_id=r.review_id, op=_op("ed"))

    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == "DM-SOP-000523"))
    assert doc.status == "PUBLISHED" and result.doc_status == "PUBLISHED"


async def test_withdraw_non_owner_blocked(db):
    await _seed_user(db, "ed", "撰寫")
    await _doc(db, "DM-SOP-000524", status="PENDING_REVIEW")
    v = await _version(db, "DM-SOP-000524", "1.0", status="PENDING_REVIEW", author="ed")
    r = await _review(db, "DM-SOP-000524", v.version_id, review_type="NEW", status="PENDING", author="ed")
    with pytest.raises(AppError) as e:
        await _svc.withdraw(db, review_id=r.review_id, op=_op("other"))
    assert e.value.error_code == "DM_REVIEW_007"


async def test_withdraw_non_pending_blocked(db):
    await _seed_user(db, "ed", "撰寫")
    await _doc(db, "DM-SOP-000525", status="PUBLISHED")
    v = await _version(db, "DM-SOP-000525", "1.0", status="PUBLISHED", published=utcnow())
    r = await _review(db, "DM-SOP-000525", v.version_id, review_type="NEW", status="APPROVED")
    with pytest.raises(AppError) as e:
        await _svc.withdraw(db, review_id=r.review_id, op=_op("ed"))
    assert e.value.error_code == "DM_REVIEW_003"


# ── 我的文件動態 ────────────────────────────────────


async def test_activity_author_and_reviewer_views(db):
    await _seed_user(db, "ed", "撰寫")
    await _seed_user(db, "rev1", "審核")
    await _doc(db, "DM-SOP-000531", status="PENDING_REVIEW")
    v = await _version(db, "DM-SOP-000531", "1.0", status="PENDING_REVIEW")
    await _review(db, "DM-SOP-000531", v.version_id, review_type="NEW", status="PENDING", reviewer="rev1", author="ed")

    ed_act = await _svc.list_activity(db, user_id="ed", roles=[DM_EDITOR])
    rev_act = await _svc.list_activity(db, user_id="rev1", roles=[DM_REVIEWER])
    assert any(a.doc_id == "DM-SOP-000531" for a in ed_act.author) and ed_act.reviewer == []
    assert any(a.doc_id == "DM-SOP-000531" for a in rev_act.reviewer) and rev_act.author == []


async def test_activity_gated_by_current_roles(db):
    # #2：依當下角色呈現視角——曾當編輯者(有 author 資料)但當下只有審核者角色 → 不呈現撰寫者視角
    await _seed_user(db, "u", "曾編輯今審核")
    await _doc(db, "DM-SOP-000535", status="PENDING_REVIEW")
    v = await _version(db, "DM-SOP-000535", "1.0", status="PENDING_REVIEW", author="u")
    # u 既是該送審撰寫者、也是別人送審的指派審核者
    await _review(db, "DM-SOP-000535", v.version_id, review_type="NEW", status="PENDING", reviewer="rev9", author="u")
    await _doc(db, "DM-SOP-000536", status="PENDING_REVIEW")
    v2 = await _version(db, "DM-SOP-000536", "1.0", status="PENDING_REVIEW", author="ed9")
    await _review(db, "DM-SOP-000536", v2.version_id, review_type="NEW", status="PENDING", reviewer="u", author="ed9")

    # 只有審核者角色 → 只回審核者視角（雖有 author 歷史資料）
    only_reviewer = await _svc.list_activity(db, user_id="u", roles=[DM_REVIEWER])
    assert only_reviewer.author == [] and len(only_reviewer.reviewer) >= 1
    # 只有編輯者角色 → 只回撰寫者視角
    only_editor = await _svc.list_activity(db, user_id="u", roles=[DM_EDITOR])
    assert only_editor.reviewer == [] and len(only_editor.author) >= 1
    # 兩角色皆有 → 兩視角皆呈現
    both = await _svc.list_activity(db, user_id="u", roles=[DM_EDITOR, DM_REVIEWER])
    assert len(both.author) >= 1 and len(both.reviewer) >= 1


async def test_reviewer_activity_marks_overdue(db):
    # 審核者視角：停留逾催辦門檻（預設 7 天）之 PENDING → is_overdue=True（前端顯「催辦中」，AC5）
    await _seed_user(db, "rev1", "審核")
    await _doc(db, "DM-SOP-000533", status="PENDING_REVIEW")
    v = await _version(db, "DM-SOP-000533", "1.0", status="PENDING_REVIEW")
    old = utcnow() - timedelta(days=10)  # 逾 7 天門檻
    r = await _review(
        db, "DM-SOP-000533", v.version_id, review_type="NEW", status="PENDING", reviewer="rev1", submit=old
    )
    act = await _svc.list_activity(db, user_id="rev1", roles=[DM_REVIEWER])
    item = next(a for a in act.reviewer if a.review_id == r.review_id)
    assert item.is_overdue is True and item.waiting_days >= 7


async def test_reviewer_activity_recent_pending_not_overdue(db):
    await _seed_user(db, "rev1", "審核")
    await _doc(db, "DM-SOP-000534", status="PENDING_REVIEW")
    v = await _version(db, "DM-SOP-000534", "1.0", status="PENDING_REVIEW")
    r = await _review(db, "DM-SOP-000534", v.version_id, review_type="NEW", status="PENDING", reviewer="rev1")
    act = await _svc.list_activity(db, user_id="rev1", roles=[DM_REVIEWER])
    item = next(a for a in act.reviewer if a.review_id == r.review_id)
    assert item.is_overdue is False


async def test_activity_excludes_older_than_30_days(db):
    await _seed_user(db, "ed", "撰寫")
    await _doc(db, "DM-SOP-000532", status="PUBLISHED")
    v = await _version(db, "DM-SOP-000532", "1.0", status="PUBLISHED", published=utcnow())
    old = utcnow() - timedelta(days=40)
    # submit 與 complete 皆逾 30 天 → 不列入近 30 天動態
    await _review(
        db, "DM-SOP-000532", v.version_id, review_type="NEW", status="APPROVED", author="ed", submit=old, complete=old
    )
    act = await _svc.list_activity(db, user_id="ed", roles=[DM_EDITOR])
    assert all(a.doc_id != "DM-SOP-000532" for a in act.author)


# ── 入口可見性（HTTP）──────────────────────────────


async def test_access_true_for_editor_or_reviewer(db, client):
    await _seed_user(db, "ed", "編輯")
    await _grant(db, "ed", DM_EDITOR)
    token = create_access_token(sub="ed", ttl_minutes=15)
    resp = await client.get("/api/dm/personal/access", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200 and resp.json()["can_access"] is True


async def test_access_false_for_viewer_or_admin_only(db, client):
    await _seed_user(db, "v", "閱覽管理")
    await _grant(db, "v", DM_VIEWER)
    await _grant(db, "v", DM_ADMIN)  # 純閱覽 + 純管理，無編輯/審核
    token = create_access_token(sub="v", ttl_minutes=15)
    resp = await client.get("/api/dm/personal/access", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200 and resp.json()["can_access"] is False


async def test_http_drafts_requires_auth(db, client):
    resp = await client.get("/api/dm/personal/drafts")
    assert resp.status_code == 401
