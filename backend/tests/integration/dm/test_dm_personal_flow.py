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


async def test_drafts_last_edited_falls_back_to_created(db):
    # #222 Round-2：首次存草稿（未編輯過、updated_date NULL）→ 最後編輯回退 created_date（存草稿時間），不空白
    await _seed_user(db, "ed", "撰寫")
    await _doc(db, "DM-SOP-000560", status="DRAFT")
    await _version(db, "DM-SOP-000560", "1.0", status="DRAFT")  # 無 updated_date
    drafts = await _svc.list_drafts(db, user_id="ed")
    d = next(x for x in drafts if x.doc_id == "DM-SOP-000560")
    assert d.updated_date is not None  # coalesce 退回 created_date


async def test_drafts_only_own_and_not_deleted(db):
    await _seed_user(db, "ed", "撰寫")
    await _seed_user(db, "ed2", "他人")
    await _doc(db, "DM-SOP-000504", status="DRAFT")
    await _version(db, "DM-SOP-000504", "1.0", status="DRAFT", author="ed2")  # 他人草稿
    drafts = await _svc.list_drafts(db, user_id="ed")
    assert all(d.doc_id != "DM-SOP-000504" for d in drafts)


async def test_drafts_include_obsolete_parent_with_doc_status(db):
    # #1(Round-4)：父文件已廢止(OBSOLETE)之孤兒草稿「仍顯示」於草稿匣，帶 doc_status 供前端灰掉續編、允許刪除
    await _seed_user(db, "ed", "撰寫")
    await _doc(db, "DM-SOP-000505", status="OBSOLETE")
    await _version(db, "DM-SOP-000505", "2.0", status="DRAFT")  # 廢止前編到一半的新版草稿
    drafts = await _svc.list_drafts(db, user_id="ed")
    d = next(x for x in drafts if x.doc_id == "DM-SOP-000505")
    assert d.doc_status == "OBSOLETE"


async def test_drafts_include_pending_obsolete_parent(db):
    # #1(Round-4)：父文件廢止待簽核(PENDING_OBSOLETE)之孤兒草稿也不隱藏（與「他人送審中文件之草稿不隱藏」一致）
    await _seed_user(db, "ed", "撰寫")
    await _doc(db, "DM-SOP-000507", status="PENDING_OBSOLETE")
    await _version(db, "DM-SOP-000507", "2.0", status="DRAFT")
    drafts = await _svc.list_drafts(db, user_id="ed")
    d = next(x for x in drafts if x.doc_id == "DM-SOP-000507")
    assert d.doc_status == "PENDING_OBSOLETE"


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
    item = next(a for a in act.reviewer if a.review_id == r.review_id and a.event_kind == "submitted")
    assert item.is_overdue is True


async def test_reviewer_activity_recent_pending_not_overdue(db):
    await _seed_user(db, "rev1", "審核")
    await _doc(db, "DM-SOP-000534", status="PENDING_REVIEW")
    v = await _version(db, "DM-SOP-000534", "1.0", status="PENDING_REVIEW")
    r = await _review(db, "DM-SOP-000534", v.version_id, review_type="NEW", status="PENDING", reviewer="rev1")
    act = await _svc.list_activity(db, user_id="rev1", roles=[DM_REVIEWER])
    item = next(a for a in act.reviewer if a.review_id == r.review_id and a.event_kind == "submitted")
    assert item.is_overdue is False


async def test_activity_terminal_expands_to_two_events_newest_first(db):
    # #5：一次送審週期展開為 送審(submitted) → 結果(resolved) 兩事件，時間新→舊（結果在前）
    await _seed_user(db, "ed", "撰寫")
    await _seed_user(db, "rev1", "審核")
    await _doc(db, "DM-SOP-000541", status="DRAFT")
    v = await _version(db, "DM-SOP-000541", "1.0", status="DRAFT")
    submit = utcnow() - timedelta(days=3)
    reject = utcnow() - timedelta(days=1)
    await _review(
        db,
        "DM-SOP-000541",
        v.version_id,
        review_type="NEW",
        status="REJECTED",
        reviewer="rev1",
        author="ed",
        submit=submit,
        complete=reject,
    )
    act = await _svc.list_activity(db, user_id="ed", roles=[DM_EDITOR])
    evs = [a for a in act.author if a.doc_id == "DM-SOP-000541"]
    assert {e.event_kind for e in evs} == {"submitted", "resolved"}  # 兩事件
    assert evs[0].event_kind == "resolved" and evs[1].event_kind == "submitted"  # 結果(較近)在前
    assert evs[0].party_name == "審核"  # 撰寫者視角對造人＝指定審核者姓名


async def test_own_obsolete_shows_in_author_progression(db):
    # 本人自行發起之廢止屬撰寫者送審歷程（此為唯一在動態呈現廢止之情形；他人發起之廢止不進動態）
    await _seed_user(db, "ed", "撰寫")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    await _doc(db, "DM-SOP-000543", status="OBSOLETE", author="ed")
    v = await _version(db, "DM-SOP-000543", "1.0", status="OBSOLETE", author="ed", published=utcnow())
    await _review(
        db, "DM-SOP-000543", v.version_id, review_type="OBSOLETE", status="APPROVED", reviewer="rev1", author="ed"
    )
    act = await _svc.list_activity(db, user_id="ed", roles=[DM_EDITOR])
    assert any(a.doc_id == "DM-SOP-000543" for a in act.author)


async def test_obsolete_by_other_not_in_activity(db):
    # #1(Round-4)：他人對本人有版本之文件發起廢止 → 不進本人動態（動態只顯示自己送審的文件）
    await _seed_user(db, "ed", "撰寫")
    await _seed_user(db, "adm", "管理員", email="adm@e.com")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    await _doc(db, "DM-SOP-000542", status="OBSOLETE", author="ed")
    v = await _version(db, "DM-SOP-000542", "1.0", status="OBSOLETE", author="ed", published=utcnow())
    await _review(
        db, "DM-SOP-000542", v.version_id, review_type="OBSOLETE", status="APPROVED", reviewer="rev1", author="adm"
    )
    act = await _svc.list_activity(db, user_id="ed", roles=[DM_EDITOR])
    assert all(a.doc_id != "DM-SOP-000542" for a in act.author)


async def test_reviewer_view_terminal_expands_to_two_events(db):
    # #2(Round-4)：審核者視角與撰寫者一致——已完成送審展開為 送審 + 結果 兩列（不只改單列狀態）
    await _seed_user(db, "ed", "撰寫")
    await _seed_user(db, "rev1", "審核")
    await _doc(db, "DM-SOP-000544", status="DRAFT")
    v = await _version(db, "DM-SOP-000544", "1.0", status="DRAFT")
    submit = utcnow() - timedelta(days=3)
    reject = utcnow() - timedelta(days=1)
    r = await _review(
        db,
        "DM-SOP-000544",
        v.version_id,
        review_type="NEW",
        status="REJECTED",
        reviewer="rev1",
        author="ed",
        submit=submit,
        complete=reject,
    )
    act = await _svc.list_activity(db, user_id="rev1", roles=[DM_REVIEWER])
    evs = [a for a in act.reviewer if a.review_id == r.review_id]
    assert {e.event_kind for e in evs} == {"submitted", "resolved"}  # 兩列
    assert evs[0].event_kind == "resolved" and evs[1].event_kind == "submitted"  # 結果較近在前


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


# ── #395 D：永久卡住的送審必須看得見、且看得出卡在哪 ──────────


async def test_pending_送審超過動態窗口仍看得見(db):
    """🔴 卡住的案件在 30 天後從撰寫者畫面**完全消失**——連撤回的入口都沒了（#395 AC 4 選項 D-1）。

    撤回（`withdraw`）本身沒有時間限制，三道守門只有查無 / 非本人 / 非 PENDING。但撤回鈕渲染在
    「我的文件動態」的**每一列事件**上，而該清單原本是 30 天窗口：`PENDING` 的 `complete_date`
    是 `NULL`，`submit_date` 又早於窗口，兩個條件都不成立——**那一列根本沒從資料庫回來**。

    ⚠️ 窗口豁免的判準是 **`PENDING` 本身**，不是「逾催辦門檻」：30 天窗口的語意是「近期**歷程**」，
    而 `PENDING` 是**當前狀態**不是歷程。若改以門檻判定，「這筆案件存不存在於畫面上」就會取決於
    `DM_REMIND_THRESHOLD` 這個**催辦設定**——兩件事不該綁在一起。
    """
    await _seed_user(db, "ed395d1", "撰寫")
    await _seed_user(db, "rev395d1", "審核")
    await _doc(db, "DM-SOP-000560", status="PENDING_REVIEW", author="ed395d1")
    v = await _version(db, "DM-SOP-000560", "1.0", status="PENDING_REVIEW", author="ed395d1")
    await _review(
        db,
        "DM-SOP-000560",
        v.version_id,
        review_type="NEW",
        status="PENDING",
        reviewer="rev395d1",
        author="ed395d1",
        submit=utcnow() - timedelta(days=100),  # 遠早於 30 天窗口
    )

    act = await _svc.list_activity(db, user_id="ed395d1", roles=[DM_EDITOR])

    rows = [a for a in act.author if a.doc_id == "DM-SOP-000560"]
    assert rows, "卡住的送審必須留在動態上，否則撰寫者連撤回的入口都沒有"
    assert rows[0].event_kind == "submitted" and rows[0].status == "PENDING"
    assert rows[0].is_overdue, "早已超過催辦門檻，應標為逾期"


async def test_已完成的送審仍受_30_天窗口限制(db):
    """回歸護欄：豁免只給 `PENDING`，**不得**把整個窗口廢掉。

    已結案的送審是歷程，超過窗口就該消失——否則動態會無限成長，而那是窗口存在的理由。
    """
    await _seed_user(db, "ed395d2", "撰寫")
    await _doc(db, "DM-SOP-000561", status="PUBLISHED", author="ed395d2")
    v = await _version(db, "DM-SOP-000561", "1.0", status="PUBLISHED", author="ed395d2")
    await _review(
        db,
        "DM-SOP-000561",
        v.version_id,
        review_type="NEW",
        status="APPROVED",
        author="ed395d2",
        submit=utcnow() - timedelta(days=100),
        complete=utcnow() - timedelta(days=99),
    )

    act = await _svc.list_activity(db, user_id="ed395d2", roles=[DM_EDITOR])
    assert not [a for a in act.author if a.doc_id == "DM-SOP-000561"], "已結案且逾窗口者不該出現"


async def test_審核者帳號已停用時撰寫者看得出原因(db):
    """⭐ D-2：讓「知道」與「能做」落在同一個人身上（#395 AC 4）。

    撰寫者本來就能撤回重送，缺的只是**沒有任何東西告訴他該撤回**——他看到的是「送審中」，
    卡 1 天和卡 100 天字樣完全相同，而審核者已經登不進系統了。
    """
    from app.dp.users.service import UsersService

    await _seed_user(db, "ed395d3", "撰寫")
    await _seed_user(db, "rev395d3", "停用審核者")
    # 走產品路徑停用（#395 AC 3 的判準：不直接 UPDATE）
    await UsersService().set_status(db, user_id="rev395d3", action="disable", operator=OperatorInfo(user_id="ed395d3"))
    await _doc(db, "DM-SOP-000562", status="PENDING_REVIEW", author="ed395d3")
    v = await _version(db, "DM-SOP-000562", "1.0", status="PENDING_REVIEW", author="ed395d3")
    await _review(
        db,
        "DM-SOP-000562",
        v.version_id,
        review_type="NEW",
        status="PENDING",
        reviewer="rev395d3",
        author="ed395d3",
        submit=utcnow() - timedelta(days=40),
    )

    act = await _svc.list_activity(db, user_id="ed395d3", roles=[DM_EDITOR])
    row = next(a for a in act.author if a.doc_id == "DM-SOP-000562")
    assert row.party_unreachable == "DISABLED", "撰寫者必須看得出審核者已停用，否則他不知道要撤回"


async def test_查無審核者帳號與已停用分屬兩類(db):
    """⚠️ 兩類不可併成一句——補救動作不同（修資料 vs 換審核者），與 #399 的 log 分類同一判準。

    `DM_REVIEW.ASSIGNED_REVIEWER` 是 `String(20)` 且**無 FK**，故孤兒列造得出來；
    `party_user` 是 `outerjoin`，查無使用者時整組欄位皆為 `None`。
    """
    await _seed_user(db, "ed395d4", "撰寫")
    await _doc(db, "DM-SOP-000563", status="PENDING_REVIEW", author="ed395d4")
    v = await _version(db, "DM-SOP-000563", "1.0", status="PENDING_REVIEW", author="ed395d4")
    await _review(
        db,
        "DM-SOP-000563",
        v.version_id,
        review_type="NEW",
        status="PENDING",
        reviewer="nobody395d4",  # DP_USER 查無此列
        author="ed395d4",
        submit=utcnow() - timedelta(days=40),
    )

    act = await _svc.list_activity(db, user_id="ed395d4", roles=[DM_EDITOR])
    row = next(a for a in act.author if a.doc_id == "DM-SOP-000563")
    assert row.party_unreachable == "NOT_FOUND"


async def test_審核者正常時不標示不可達(db):
    """回歸護欄：只標示真正不可達者，正常路徑不得受影響。"""
    await _seed_user(db, "ed395d5", "撰寫")
    await _seed_user(db, "rev395d5", "正常審核者")
    await _doc(db, "DM-SOP-000564", status="PENDING_REVIEW", author="ed395d5")
    v = await _version(db, "DM-SOP-000564", "1.0", status="PENDING_REVIEW", author="ed395d5")
    await _review(
        db,
        "DM-SOP-000564",
        v.version_id,
        review_type="NEW",
        status="PENDING",
        reviewer="rev395d5",
        author="ed395d5",
    )

    act = await _svc.list_activity(db, user_id="ed395d5", roles=[DM_EDITOR])
    row = next(a for a in act.author if a.doc_id == "DM-SOP-000564")
    assert row.party_unreachable is None
