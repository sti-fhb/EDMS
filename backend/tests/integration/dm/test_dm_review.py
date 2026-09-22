"""簽核處理（US6 / DM04）整合測試（真實 DB）。

涵蓋：待簽核清單（只列自己 PENDING + 停留天數）、明細（新版本附舊版比對 / 非本人擋）、
核准並發布（首版 NEW / 新版 NEW_VERSION 之原子版本切換 + CURRENT_VERSION_ID + DM_CHANGE_LOG + 通知）、
退回（版本 REJECTED；NEW→文件 DRAFT、NEW_VERSION→文件維持 PUBLISHED〔Q2〕；DOC_REJECT 通知 + 原因必填）、
已完成清單、收件名單（全體 / 指定可見對象）、催辦掃描、授權（非本人 / 非 PENDING）、HTTP 存取閘。
（US8 起 OBSOLETE 核准 / 退回已支援，廢止流程細節見 test_dm_obsolete_flow.py。）
"""

import logging
import os

import pytest
from sqlalchemy import func, select, text, update

from app.core.auth import create_access_token
from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dm.audience.models import DmUserTag
from app.dm.catalog.models import DmTag
from app.dm.document.file_paths import storage_root
from app.dm.document.models import DmDocTag, DmDocument, DmDocVersion
from app.dm.review.center_service import ReviewCenterService
from app.dm.review.models import DmChangeLog, DmReview
from app.dm.roles.authz import DM_REVIEWER, DM_VIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_svc = ReviewCenterService()
_PDF = "application/pdf"


def _op(uid="rev1"):
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


async def _audience_id(db, name):
    return await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "AUDIENCE", DmTag.tag_name == name))


async def _add_version(db, doc_id, version_no, *, status, author="ed", summary="摘要", published=None, file_path=None):
    # 預設落在 storage root 內（#160 圍籬會擋 root 外路徑）；測逃逸之案例自帶 file_path
    if file_path is None:
        file_path = os.path.join(storage_root(), doc_id, f"{version_no}.pdf")
    v = DmDocVersion(
        doc_id=doc_id,
        version_no=version_no,
        change_summary=summary,
        file_name=f"{version_no}.pdf",
        file_path=file_path,
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


async def _doc(db, doc_id, *, status, current_version_id=None, author="ed", category="SOP", audience=()):
    doc = DmDocument(
        doc_id=doc_id,
        doc_name=f"文件{doc_id}",
        category_code=category,
        current_version_id=current_version_id,
        status=status,
        created_user=author,
        created_date=utcnow(),
    )
    db.add(doc)
    await db.flush()
    for n in audience:
        db.add(DmDocTag(doc_id=doc_id, tag_id=await _audience_id(db, n), created_user=author, created_date=utcnow()))
    await db.flush()
    return doc


async def _review(db, doc_id, version_id, *, review_type, reviewer="rev1", author="ed", status="PENDING", submit=None):
    r = DmReview(
        doc_id=doc_id,
        version_id=version_id,
        review_type=review_type,
        assigned_reviewer=reviewer,
        status=status,
        submit_date=submit or utcnow(),
        approver_user_id=None,
        created_user=author,
        created_date=utcnow(),
    )
    db.add(r)
    await db.flush()
    return r


async def _new_submission(db, doc_id, *, reviewer="rev1", author="ed", audience=("全體",)):
    """首版送審（NEW）：doc PENDING_REVIEW + 一個 PENDING_REVIEW 版本 + NEW review。"""
    doc = await _doc(db, doc_id, status="PENDING_REVIEW", author=author, audience=audience)
    v = await _add_version(db, doc_id, "1.0", status="PENDING_REVIEW", author=author)
    r = await _review(db, doc_id, v.version_id, review_type="NEW", reviewer=reviewer, author=author)
    return doc, v, r


async def _new_version_submission(db, doc_id, *, reviewer="rev1", author="ed", audience=("全體",)):
    """已發布文件之新版送審（NEW_VERSION）：doc PUBLISHED + 目前發布版 + 新 PENDING_REVIEW 版本 + review。"""
    doc = await _doc(db, doc_id, status="PUBLISHED", current_version_id=None, author=author, audience=audience)
    cur = await _add_version(db, doc_id, "1.0", status="PUBLISHED", author=author, published=utcnow())
    doc.current_version_id = cur.version_id
    await db.flush()
    new = await _add_version(db, doc_id, "2.0", status="PENDING_REVIEW", author=author)
    r = await _review(db, doc_id, new.version_id, review_type="NEW_VERSION", reviewer=reviewer, author=author)
    return doc, cur, new, r


# ── 待簽核清單 ────────────────────────────────────


async def test_pending_lists_only_own(db):
    await _seed_user(db, "ed", "撰寫")
    await _new_submission(db, "DM-SOP-000301", reviewer="rev1")
    await _new_submission(db, "DM-SOP-000302", reviewer="rev2")  # 別人的
    items = await _svc.list_pending(db, op=_op("rev1"))
    assert {i.doc_id for i in items} == {"DM-SOP-000301"}
    assert items[0].review_type == "NEW" and items[0].waiting_days >= 0


async def test_pending_waiting_days(db):
    from datetime import timedelta

    await _seed_user(db, "ed", "撰寫")
    await _doc(db, "DM-SOP-000303", status="PENDING_REVIEW")
    v = await _add_version(db, "DM-SOP-000303", "1.0", status="PENDING_REVIEW")
    await _review(db, "DM-SOP-000303", v.version_id, review_type="NEW", submit=utcnow() - timedelta(days=5))
    items = await _svc.list_pending(db, op=_op("rev1"))
    assert items[0].waiting_days == 5


# ── 明細 ──────────────────────────────────────────


async def test_detail_new_version_has_current_for_compare(db):
    await _seed_user(db, "ed", "撰寫")
    _, cur, new, r = await _new_version_submission(db, "DM-SOP-000310")
    d = await _svc.get_detail(db, review_id=r.review_id, op=_op("rev1"))
    assert d.new_version.version_id == new.version_id
    assert d.current_version is not None and d.current_version.version_id == cur.version_id


async def test_detail_first_version_no_current(db):
    await _seed_user(db, "ed", "撰寫")
    _, v, r = await _new_submission(db, "DM-SOP-000311")
    d = await _svc.get_detail(db, review_id=r.review_id, op=_op("rev1"))
    assert d.new_version.version_id == v.version_id and d.current_version is None


async def test_detail_non_reviewer_blocked(db):
    await _seed_user(db, "ed", "撰寫")
    _, _, r = await _new_submission(db, "DM-SOP-000312", reviewer="rev1")
    with pytest.raises(AppError) as e:
        await _svc.get_detail(db, review_id=r.review_id, op=_op("other"))
    assert e.value.error_code == "DM_REVIEW_005"


# ── 明細檔案下載（待審版取檔）────────────────────────


async def test_prepare_file_reviewer_gets_pending_and_current(db):
    """指定審核者可取待審版（未發布）與目前發布版（供比對）。"""
    await _seed_user(db, "ed", "撰寫")
    _, cur, new, r = await _new_version_submission(db, "DM-SOP-000313")
    pending = await _svc.prepare_file(db, review_id=r.review_id, version_id=new.version_id, op=_op("rev1"))
    assert (
        pending.path == os.path.realpath(new.file_path) and pending.name == new.file_name
    )  # 回 fence 後 canonical 路徑
    current = await _svc.prepare_file(db, review_id=r.review_id, version_id=cur.version_id, op=_op("rev1"))
    assert current.path == os.path.realpath(cur.file_path)


async def test_prepare_file_escaping_storage_root_blocked(db):
    """storage-root 圍籬（#160，補齊第三條串流路徑）：待審版 FILE_PATH 逃逸出根目錄 → 404。"""
    await _seed_user(db, "ed", "撰寫")
    doc, _cur, new, r = await _new_version_submission(db, "DM-SOP-000317")
    new.file_path = os.path.join(storage_root(), "..", "..", "etc", "secret.pdf")  # 污染待審版落盤路徑
    await db.flush()
    with pytest.raises(AppError) as e:
        await _svc.prepare_file(db, review_id=r.review_id, version_id=new.version_id, op=_op("rev1"))
    assert e.value.error_code == "DM_DOC_001" and e.value.status_code == 404


async def test_prepare_file_non_reviewer_blocked(db):
    await _seed_user(db, "ed", "撰寫")
    _, v, r = await _new_submission(db, "DM-SOP-000314", reviewer="rev1")
    with pytest.raises(AppError) as e:
        await _svc.prepare_file(db, review_id=r.review_id, version_id=v.version_id, op=_op("other"))
    assert e.value.error_code == "DM_REVIEW_005"


async def test_prepare_file_version_not_in_review_rejected(db):
    """越權索取非本送審之版本（不在白名單）→ 404，不外洩其他版本檔案。"""
    await _seed_user(db, "ed", "撰寫")
    _, v, r = await _new_submission(db, "DM-SOP-000315", reviewer="rev1")
    other = await _add_version(db, v.doc_id, "9.9", status="DRAFT")
    with pytest.raises(AppError) as e:
        await _svc.prepare_file(db, review_id=r.review_id, version_id=other.version_id, op=_op("rev1"))
    assert e.value.status_code == 404


# ── 核准並發布 ────────────────────────────────────


async def test_approve_first_version_publishes(db):
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    doc, v, r = await _new_submission(db, "DM-SOP-000320", audience=("全體",))
    res = await _svc.approve(db, review_id=r.review_id, op=_op("rev1"))
    assert res.published_version_id == v.version_id and res.notified >= 1
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == "DM-SOP-000320"))
    v = await db.scalar(select(DmDocVersion).where(DmDocVersion.version_id == v.version_id))
    assert doc.status == "PUBLISHED" and doc.current_version_id == v.version_id
    assert v.status == "PUBLISHED" and v.approver_user_id == "rev1" and v.published_date is not None
    review = await db.scalar(select(DmReview).where(DmReview.review_id == r.review_id))
    assert review.status == "APPROVED"
    logs = await db.scalar(
        select(func.count())
        .select_from(DmChangeLog)
        .where(DmChangeLog.doc_id == "DM-SOP-000320", DmChangeLog.operation == "PUBLISH")
    )
    assert logs == 1


async def test_approve_new_version_supersedes_old(db):
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    doc, cur, new, r = await _new_version_submission(db, "DM-SOP-000321")
    await _svc.approve(db, review_id=r.review_id, op=_op("rev1"))
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == "DM-SOP-000321"))
    cur = await db.scalar(select(DmDocVersion).where(DmDocVersion.version_id == cur.version_id))
    new = await db.scalar(select(DmDocVersion).where(DmDocVersion.version_id == new.version_id))
    assert doc.status == "PUBLISHED" and doc.current_version_id == new.version_id
    assert new.status == "PUBLISHED" and cur.status == "SUPERSEDED"


async def test_approve_non_pending_blocked(db):
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    _, _, r = await _new_submission(db, "DM-SOP-000322")
    await _svc.approve(db, review_id=r.review_id, op=_op("rev1"))
    with pytest.raises(AppError) as e:  # 再核准 → 非待審核
        await _svc.approve(db, review_id=r.review_id, op=_op("rev1"))
    assert e.value.error_code == "DM_REVIEW_003"


async def test_approve_non_reviewer_blocked(db):
    await _seed_user(db, "ed", "撰寫")
    _, _, r = await _new_submission(db, "DM-SOP-000323", reviewer="rev1")
    with pytest.raises(AppError) as e:
        await _svc.approve(db, review_id=r.review_id, op=_op("other"))
    assert e.value.error_code == "DM_REVIEW_005"


async def test_approve_obsolete_now_supported_us8(db):
    # US8：OBSOLETE 核准已支援（原 DM_REVIEW_006 封鎖已解除）→ 文件轉 OBSOLETE；廢止流程細節見 test_dm_obsolete_flow
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    doc = await _doc(db, "DM-SOP-000324", status="PENDING_OBSOLETE", current_version_id=None)
    v = await _add_version(db, "DM-SOP-000324", "1.0", status="PUBLISHED", published=utcnow())
    doc.current_version_id = v.version_id
    await db.flush()
    r = await _review(db, "DM-SOP-000324", v.version_id, review_type="OBSOLETE", reviewer="rev1")
    await _svc.approve(db, review_id=r.review_id, op=_op("rev1"))
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == "DM-SOP-000324"))
    assert doc.status == "OBSOLETE" and doc.current_version_id == v.version_id


# ── 退回 ──────────────────────────────────────────


async def test_reject_first_version_doc_to_draft(db):
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    doc, v, r = await _new_submission(db, "DM-SOP-000330")
    await _svc.reject(db, review_id=r.review_id, reason="需補充", op=_op("rev1"))
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == "DM-SOP-000330"))
    v = await db.scalar(select(DmDocVersion).where(DmDocVersion.version_id == v.version_id))
    review = await db.scalar(select(DmReview).where(DmReview.review_id == r.review_id))
    assert doc.status == "DRAFT" and v.status == "DRAFT"  # 退回 → 版本回草稿供續編（FR-004）
    assert review.status == "REJECTED" and review.reason == "需補充"
    # DOC_REJECT 通知撰寫者
    n = await db.scalar(
        text('SELECT count(*) FROM "DP_EMAIL_LOG" WHERE "TEMPLATE_CODE"=\'DOC_REJECT\' AND "RECIPIENT"=\'ed@e.com\'')
    )
    assert n == 1


async def test_reject_new_version_keeps_doc_published(db):
    """Q2：退回 NEW_VERSION → 文件維持 PUBLISHED、現行發布版不動；被退新版回 DRAFT 供續編。"""
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    doc, cur, new, r = await _new_version_submission(db, "DM-SOP-000331")
    await _svc.reject(db, review_id=r.review_id, reason="不通過", op=_op("rev1"))
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == "DM-SOP-000331"))
    cur = await db.scalar(select(DmDocVersion).where(DmDocVersion.version_id == cur.version_id))
    new = await db.scalar(select(DmDocVersion).where(DmDocVersion.version_id == new.version_id))
    assert doc.status == "PUBLISHED" and doc.current_version_id == cur.version_id  # 不動
    assert cur.status == "PUBLISHED" and new.status == "DRAFT"  # 現行發布版不受影響、新版回草稿


async def test_reject_keeps_rejected_when_author_has_other_draft(db):
    """邊界：撰寫者送審後又另開草稿 → 退回不可轉 DRAFT（撞每人一份草稿索引），保留 REJECTED。"""
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    doc, cur, new, r = await _new_version_submission(db, "DM-SOP-000332")
    # 送審後撰寫者於同文件另開一份草稿
    await _add_version(db, doc.doc_id, "3.0", status="DRAFT", author="ed")
    await _svc.reject(db, review_id=r.review_id, reason="不通過", op=_op("rev1"))
    new = await db.scalar(select(DmDocVersion).where(DmDocVersion.version_id == new.version_id))
    assert new.status == "REJECTED"  # 保留、避免與既有草稿撞唯一索引


async def test_reject_empty_reason_blocked(db):
    await _seed_user(db, "ed", "撰寫")
    _, _, r = await _new_submission(db, "DM-SOP-000332")
    with pytest.raises(AppError) as e:
        await _svc.reject(db, review_id=r.review_id, reason="  ", op=_op("rev1"))
    assert e.value.error_code == "DM_REVIEW_004"


# ── 已完成 ────────────────────────────────────────


async def test_completed_lists_own_processed(db):
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    _, _, r1 = await _new_submission(db, "DM-SOP-000340")
    await _svc.approve(db, review_id=r1.review_id, op=_op("rev1"))
    _, _, r2 = await _new_submission(db, "DM-SOP-000341")
    await _svc.reject(db, review_id=r2.review_id, reason="退", op=_op("rev1"))
    page = await _svc.list_completed(db, op=_op("rev1"), page=1, limit=20)
    statuses = {c.status for c in page["data"]}
    assert page["meta"]["total"] == 2 and statuses == {"APPROVED", "REJECTED"}


async def test_completed_keyword_search(db):
    """已完成頁籤支援文件名關鍵字搜尋（AC8 搜尋分頁）。"""
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    _, _, r1 = await _new_submission(db, "DM-SOP-000342")  # doc_name = 文件DM-SOP-000342
    await _svc.approve(db, review_id=r1.review_id, op=_op("rev1"))
    _, _, r2 = await _new_submission(db, "DM-MANUAL-000343")
    await _svc.approve(db, review_id=r2.review_id, op=_op("rev1"))
    page = await _svc.list_completed(db, op=_op("rev1"), page=1, limit=20, keyword="MANUAL")
    assert page["meta"]["total"] == 1 and page["data"][0].doc_id == "DM-MANUAL-000343"


# ── 收件名單 ──────────────────────────────────────


async def test_recipients_all_audience_includes_viewers(db):
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    await _seed_user(db, "viewer_a", "閱覽A", email="va@e.com")
    await _grant(db, "viewer_a", DM_VIEWER)
    await _doc(db, "DM-SOP-000350", status="PUBLISHED", author="ed", audience=("全體",))
    emails = await _svc._repo.recipient_emails(db, "DM-SOP-000350", "ed")
    assert "ed@e.com" in emails and "va@e.com" in emails  # 全體 → 所有閱覽者 + 撰寫者


async def test_recipients_specific_audience_matches_only(db):
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    await _seed_user(db, "nurse", "護理", email="nurse@e.com")
    await _seed_user(db, "soldier", "軍人", email="soldier@e.com")
    await _grant(db, "nurse", DM_VIEWER)
    await _grant(db, "soldier", DM_VIEWER)
    nurse_tag = await _audience_id(db, "護理師")
    db.add(DmUserTag(user_id="nurse", tag_id=nurse_tag, created_user="seed", created_date=utcnow()))
    await db.flush()
    await _doc(db, "DM-SOP-000351", status="PUBLISHED", author="ed", audience=("護理師",))
    emails = await _svc._repo.recipient_emails(db, "DM-SOP-000351", "ed")
    assert "nurse@e.com" in emails and "ed@e.com" in emails and "soldier@e.com" not in emails


# ── 催辦 ──────────────────────────────────────────


async def test_scan_overdue_reminds(db):
    from datetime import timedelta

    await _seed_user(db, "ed", "撰寫")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    await _doc(db, "DM-SOP-000360", status="PENDING_REVIEW")
    v = await _add_version(db, "DM-SOP-000360", "1.0", status="PENDING_REVIEW")
    await _review(
        db, "DM-SOP-000360", v.version_id, review_type="NEW", reviewer="rev1", submit=utcnow() - timedelta(days=10)
    )
    count = await _svc.scan_overdue_and_remind(db, threshold_days=7)
    assert count == 1


async def test_停用的審核者不再收到催辦(db, caplog):
    """#395：`STATUS='DISABLED'` 只擋 API，不碰歷史指派欄位。

    後果不是「寄錯一次」而是**每天重複且案件永不消失**：審核者被停用 → 無法登入 →
    那筆 PENDING 永遠卡著 → 永遠超過門檻 → 每天再寄一封給一個進不來的人。

    ⚠️ **同模組內兩支排程原本對同一問題給出相反答案**：`dm/kpi/repository.py` 三處
    （`:82` / `:114` / `:167`）都濾了 `status == ACTIVE`，催辦這支沒濾。

    ## 🔴 停用走**產品路徑**，不直接 `UPDATE`（#395 AC 3）

    直接 `UPDATE ... SET STATUS='DISABLED'` 驗到的只是「我在測試裡寫的那個字串會被擋」
    ——那是拿自己的假設當輸入。改呼叫 `UsersService.set_status(action="disable")`
    之後，驗的是**產品真的做了什麼**：它寫進 `DP_USER.STATUS` 的值（不論日後改成什麼）
    會被催辦認出來。兩者在今天結果相同，差別在 DP 改值域的那一天——那時直接 UPDATE
    的版本會**繼續通過**，而這個版本會紅。
    """
    from datetime import timedelta

    from app.dp.users.service import UsersService

    await _seed_user(db, "ed395a", "撰寫")
    await _seed_user(db, "rev395a", "停用審核者", email="rev395a@e.com")
    # 停用者與操作者必須不同人——`set_status` 有自我保護（403 DP_USER_006）
    await UsersService().set_status(db, user_id="rev395a", action="disable", operator=OperatorInfo(user_id="ed395a"))
    await _doc(db, "DM-SOP-000395", status="PENDING_REVIEW")
    v = await _add_version(db, "DM-SOP-000395", "1.0", status="PENDING_REVIEW")
    await _review(
        db, "DM-SOP-000395", v.version_id, review_type="NEW", reviewer="rev395a", submit=utcnow() - timedelta(days=10)
    )

    with caplog.at_level(logging.WARNING):
        count = await _svc.scan_overdue_and_remind(db, threshold_days=7)

    assert count == 0, "停用的審核者不該再收到催辦"
    # ⭐ 只停止寄信會把問題從吵鬧變成安靜——案件仍卡著、仍無人能處理，只是沒人被打擾。
    # 這條釘住「跳過要留下痕跡」，否則積壓變成隱形的。
    assert "rev395a" in caplog.text and "審核者帳號已停用" in caplog.text, (
        "跳過未寄的催辦必須留下 log，否則永久卡住的案件會無聲累積"
    )


async def test_已刪除的審核者不再收到催辦(db):
    """`DELETED=1` 與 `DISABLED` 同樣處置。

    ⚠️ 註：`DP_USER.DELETED` 目前全系統沒有寫入點（系統無刪除使用者功能），所以這條在
    正式環境恆為 False。仍然要擋——它是 `deleted` 語意的一部分，而不是「現在會發生」。

    🔴 本條**只能**直接 `UPDATE`，這不是 #395 AC 3 所指的那個問題：AC 3 要求走產品路徑，
    前提是那條路徑存在（停用有 `UsersService.set_status`）。刪除使用者**沒有產品路徑**
    ——沒有 API、沒有排程、沒有任何寫入點。所以這條測的本來就是「一個假想的未來狀態」，
    而不是「產品做出來的狀態」，兩者不可混為一談。
    """
    from datetime import timedelta

    await _seed_user(db, "ed395b", "撰寫")
    await _seed_user(db, "rev395b", "已刪審核者", email="rev395b@e.com")
    await db.execute(update(DpUser).where(DpUser.user_id == "rev395b").values(deleted=1))
    await _doc(db, "DM-SOP-000396", status="PENDING_REVIEW")
    v = await _add_version(db, "DM-SOP-000396", "1.0", status="PENDING_REVIEW")
    await _review(
        db, "DM-SOP-000396", v.version_id, review_type="NEW", reviewer="rev395b", submit=utcnow() - timedelta(days=10)
    )

    assert await _svc.scan_overdue_and_remind(db, threshold_days=7) == 0


async def test_查無審核者帳號與已停用在_log_中分屬兩類(db, caplog):
    """`list_overdue_pending` 走 `outerjoin`，查無使用者列時 `reviewer_status` 是 `None`。

    ⚠️ 兩類**不能併成一句**：`None != "ACTIVE"` 也成立，若不分開，log 會說「帳號已停用」
    而真相是「那個 user_id 不存在」——日後有人照這行 log 去翻停用清單會查不到人，
    而兩者的補救動作不同（前者修資料、後者換審核者）。

    `ASSIGNED_REVIEWER` 是 `String(20)` 且**無 FK**，故此列造得出來；送簽 API 雖有
    `_ensure_assignable_reviewer`（#250）擋，DB 層不保證。
    """
    from datetime import timedelta

    await _seed_user(db, "ed395d", "撰寫")
    await _doc(db, "DM-SOP-000398", status="PENDING_REVIEW")
    v = await _add_version(db, "DM-SOP-000398", "1.0", status="PENDING_REVIEW")
    await _review(
        db,
        "DM-SOP-000398",
        v.version_id,
        review_type="NEW",
        reviewer="nobody395",  # DP_USER 查無此列
        submit=utcnow() - timedelta(days=10),
    )

    with caplog.at_level(logging.WARNING):
        count = await _svc.scan_overdue_and_remind(db, threshold_days=7)

    assert count == 0
    assert "查無審核者帳號" in caplog.text, "孤兒指派要有自己的分類，否則被誤標成已停用"
    assert "審核者帳號已停用" not in caplog.text


async def test_審核者_email_為空字串時跳過且留下_log(db, caplog):
    """`DP_USER.EMAIL` 是 `nullable=False`，故此條只能由空字串觸發。

    ⚠️ 這條是變異檢查抓出來的缺口：把 `elif not r.reviewer_email` 整條拿掉，29 條測試
    **全綠**——原本這個分支零覆蓋。它在 main 上就存在（`if not r.reviewer_email: continue`），
    但當時是在兼差擋 outerjoin 落空；三類分開後落空有自己的分支，剩下的才是本條。
    """
    from datetime import timedelta

    await _seed_user(db, "ed395e", "撰寫")
    await _seed_user(db, "rev395e", "無信箱審核者", email="rev395e@e.com")
    await db.execute(update(DpUser).where(DpUser.user_id == "rev395e").values(email=""))
    await _doc(db, "DM-SOP-000399", status="PENDING_REVIEW")
    v = await _add_version(db, "DM-SOP-000399", "1.0", status="PENDING_REVIEW")
    await _review(
        db, "DM-SOP-000399", v.version_id, review_type="NEW", reviewer="rev395e", submit=utcnow() - timedelta(days=10)
    )

    with caplog.at_level(logging.WARNING):
        count = await _svc.scan_overdue_and_remind(db, threshold_days=7)

    assert count == 0
    assert "查無審核者 Email" in caplog.text
    assert "審核者帳號已停用" not in caplog.text, "帳號是 ACTIVE，不該被歸成停用"


async def test_啟用中的審核者照常收到催辦(db):
    """回歸護欄：本次修正**只**排除非 ACTIVE 者，正常路徑不得受影響。"""
    from datetime import timedelta

    await _seed_user(db, "ed395c", "撰寫")
    await _seed_user(db, "rev395c", "正常審核者", email="rev395c@e.com")
    await _doc(db, "DM-SOP-000397", status="PENDING_REVIEW")
    v = await _add_version(db, "DM-SOP-000397", "1.0", status="PENDING_REVIEW")
    await _review(
        db, "DM-SOP-000397", v.version_id, review_type="NEW", reviewer="rev395c", submit=utcnow() - timedelta(days=10)
    )

    assert await _svc.scan_overdue_and_remind(db, threshold_days=7) == 1


# ── HTTP 存取閘 ───────────────────────────────────


async def test_http_pending_requires_auth(db, client):
    resp = await client.get("/api/dm/reviews/pending")
    assert resp.status_code == 401


async def test_http_pending_and_approve_flow(db, client):
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    await _seed_user(db, "rev9", "審核九", email="rev9@e.com")
    await _grant(db, "rev9", DM_REVIEWER)
    _, v, r = await _new_submission(db, "DM-SOP-000370", reviewer="rev9")
    token = create_access_token(sub="rev9", ttl_minutes=15)
    h = {"Authorization": f"Bearer {token}"}
    resp = await client.get("/api/dm/reviews/pending", headers=h)
    assert resp.status_code == 200 and any(i["review_id"] == r.review_id for i in resp.json())
    resp2 = await client.post(f"/api/dm/reviews/{r.review_id}/approve", headers=h)
    assert resp2.status_code == 200 and resp2.json()["published_version_id"] == v.version_id
