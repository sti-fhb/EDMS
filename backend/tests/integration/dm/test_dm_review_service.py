"""送審狀態機服務整合測試（T019，真實 DB）。

驗證：單一送審週期約束（不可同時兩種送審）、排除自審、核准/退回/撤回狀態轉移、終態不可重複處理。
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import AppError
from app.core.utils import utcnow
from app.dm.catalog.models import DmCategory, DmFunc  # noqa: F401  # 註冊 FK 目標
from app.dm.document.models import DmDocument
from app.dm.review.models import DmReview
from app.dm.review.service import ReviewService

pytestmark = pytest.mark.integration

_svc = ReviewService()


async def _doc(db, doc_id="DM-SOP-000001"):
    db.add(
        DmDocument(
            doc_id=doc_id,
            doc_name="d",
            category_code="SOP",
            status="DRAFT",
            created_user="author",
            created_date=utcnow(),
        )
    )
    await db.flush()
    return doc_id


async def test_submit_creates_pending(db):
    doc_id = await _doc(db)
    r = await _svc.submit(db, doc_id=doc_id, review_type="NEW", assigned_reviewer="rev1", author_id="author")
    assert r.status == "PENDING" and r.assigned_reviewer == "rev1"


async def test_submit_rejects_self_reviewer(db):
    doc_id = await _doc(db)
    with pytest.raises(AppError) as e:
        await _svc.submit(db, doc_id=doc_id, review_type="NEW", assigned_reviewer="author", author_id="author")
    assert e.value.error_code == "DM_REVIEW_001"


async def test_single_pending_constraint(db):
    """已有 PENDING 送審 → 第二次送審被擋（DM_REVIEW_002）。"""
    doc_id = await _doc(db)
    await _svc.submit(db, doc_id=doc_id, review_type="NEW", assigned_reviewer="rev1", author_id="author")
    with pytest.raises(AppError) as e:
        await _svc.submit(db, doc_id=doc_id, review_type="OBSOLETE", assigned_reviewer="rev2", author_id="author")
    assert e.value.error_code == "DM_REVIEW_002"


async def test_db_partial_unique_blocks_second_pending(db):
    """DB 級保證：繞過應用層 count 檢查，直插第二筆同文件 PENDING → partial unique index 擋下。

    這是並發雙送審（兩個 submit 同時通過 count）的最終防線；submit() 以 IntegrityError 後盾轉譯為 DM_REVIEW_002。
    """
    doc_id = await _doc(db)
    await _svc.submit(db, doc_id=doc_id, review_type="NEW", assigned_reviewer="rev1", author_id="author")
    dup = DmReview(
        doc_id=doc_id,
        review_type="OBSOLETE",
        assigned_reviewer="rev2",
        status="PENDING",
        submit_date=utcnow(),
        created_user="author",
        created_date=utcnow(),
    )
    db.add(dup)
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_approve_then_resubmit_allowed(db):
    """核准（終態）後可再送新一輪（撤回重送以新列記錄，原列保留）。"""
    doc_id = await _doc(db)
    r1 = await _svc.submit(db, doc_id=doc_id, review_type="NEW", assigned_reviewer="rev1", author_id="author")
    await _svc.approve(db, r1, approver="rev1")
    assert r1.status == "APPROVED" and r1.complete_date is not None
    # 前一輪終態 → 無 PENDING，可再送
    r2 = await _svc.submit(db, doc_id=doc_id, review_type="NEW_VERSION", assigned_reviewer="rev2", author_id="author")
    assert r2.status == "PENDING" and r2.review_id != r1.review_id


async def test_reject_requires_reason_and_completes(db):
    doc_id = await _doc(db)
    r = await _svc.submit(db, doc_id=doc_id, review_type="NEW", assigned_reviewer="rev1", author_id="author")
    await _svc.reject(db, r, approver="rev1", reason="格式不符")
    assert r.status == "REJECTED" and r.reason == "格式不符"


async def test_complete_non_pending_rejected(db):
    """已處理之送審再核准 → DM_REVIEW_003。"""
    doc_id = await _doc(db)
    r = await _svc.submit(db, doc_id=doc_id, review_type="NEW", assigned_reviewer="rev1", author_id="author")
    await _svc.withdraw(db, r, operator="author")
    with pytest.raises(AppError) as e:
        await _svc.approve(db, r, approver="rev1")
    assert e.value.error_code == "DM_REVIEW_003"
