"""簽核處理（US6 / DM02）整合測試（真實 DB）。

涵蓋：待簽核清單（只列自己 PENDING + 停留天數）、明細（新版本附舊版比對 / 非本人擋）、
核准並發布（首版 NEW / 新版 NEW_VERSION 之原子版本切換 + CURRENT_VERSION_ID + DM_CHANGE_LOG + 通知）、
退回（版本 REJECTED；NEW→文件 DRAFT、NEW_VERSION→文件維持 PUBLISHED〔Q2〕；DOC_REJECT 通知 + 原因必填）、
已完成清單、收件名單（全體 / 指定可見對象）、催辦掃描、授權（非本人 / 非 PENDING）、HTTP 存取閘。
（US8 起 OBSOLETE 核准 / 退回已支援，廢止流程細節見 test_dm_obsolete_flow.py。）
"""

import logging
import os
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text, update

from app.core.auth import create_access_token
from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dm.audience.models import DmUserTag
from app.dm.catalog.models import DmTag
from app.dm.document.file_paths import storage_root
from app.dm.document.models import DmDocTag, DmDocument, DmDocVersion, DmVersionTag
from app.dm.personal.service import PersonalService
from app.dm.review.center_service import ReviewCenterService
from app.dm.review.models import DmChangeLog, DmReview
from app.dm.review.service import ReviewService
from app.dm.roles.authz import DM_EDITOR, DM_REVIEWER, DM_VIEWER
from app.dm.roles.models import DmUserRole
from app.dp.notify.models import DpEmailLog, DpNotifyTemplate
from app.dp.params.models import DpParamDetail
from app.dp.users.models import DpUser
from app.services import MAX_RECIPIENTS

pytestmark = pytest.mark.integration


async def _auto_remind_rows(db) -> int:
    """已排入 outbox 的催辦信數。

    ⚠️ 篩 `STATUS='PENDING'`：worker 跑過後狀態會變，且渲染失敗會留下 `FAILED` 列——
    不篩就會把「寄失敗的空信」也算成成功，正是本 issue 要防的那種假陽性。
    """
    return (
        await db.scalar(
            select(func.count())
            .select_from(DpEmailLog)
            .where(DpEmailLog.template_code == "AUTO_REMIND", DpEmailLog.status == "PENDING")
        )
    ) or 0


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


async def _unit_id(db, name="全單位"):
    return await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "UNIT", DmTag.tag_name == name))


async def _doc(db, doc_id, *, status, current_version_id=None, author="ed", category="SOP", audience=(), unit="全單位"):
    """建文件；`audience` 為職位名稱、`unit` 為單位名稱——一起構成 (單位, 職位) 配對（#437）。"""
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
        db.add(
            DmDocTag(
                doc_id=doc_id,
                tag_id=await _audience_id(db, n),
                unit_tag_id=await _unit_id(db, unit),
                created_user=author,
                created_date=utcnow(),
            )
        )
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
    items = (await _svc.list_pending(db, op=_op("rev1"), page=1, limit=20))["data"]
    assert {i.doc_id for i in items} == {"DM-SOP-000301"}
    assert items[0].review_type == "NEW" and items[0].waiting_days >= 0


async def test_pending_waiting_days(db):
    from datetime import timedelta

    await _seed_user(db, "ed", "撰寫")
    await _doc(db, "DM-SOP-000303", status="PENDING_REVIEW")
    v = await _add_version(db, "DM-SOP-000303", "1.0", status="PENDING_REVIEW")
    await _review(db, "DM-SOP-000303", v.version_id, review_type="NEW", submit=utcnow() - timedelta(days=5))
    items = (await _svc.list_pending(db, op=_op("rev1"), page=1, limit=20))["data"]
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
    assert res.published_version_id == v.version_id
    # #554：本 fixture 未種任何閱覽者，而撰寫者已不再被強制加入收件名單 → 0 封。
    # 「閱覽者仍收得到」由下方 test_recipients_* 三條各自驗證（含單位 + 職位配對）。
    assert res.notified == 0

    # ⭐ 撰寫者那封信去哪了：於「我的文件動態」（撰寫者視角）見**結果**事件，
    # 前端把 resolved + APPROVED（非廢止）映射為標籤「核准發布」。
    # 只斷言 notified == 0 的話，等於只驗了「拿掉了什麼」、沒驗「什麼接住了它」。
    act = await PersonalService().list_activity(db, user_id="ed", roles=[DM_EDITOR])
    assert any(
        a.review_id == r.review_id and a.event_kind == "resolved" and a.status == "APPROVED" for a in act.author
    ), "核准發布後撰寫者應於我的文件動態看到結果事件"
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
    # #554：DOC_REJECT 改為 MSG（站內）→ **不寫 outbox**。撰寫者改於「我的文件動態」看到
    # 該事件（前端標籤「已退回」），站內可見性由 test_dm_personal_flow 驗證。
    # ⛔ 本條不刪而是翻面：刪掉就沒有東西釘住「改完之後確實不再寄信」。
    n = await db.scalar(
        text('SELECT count(*) FROM "DP_EMAIL_LOG" WHERE "TEMPLATE_CODE"=\'DOC_REJECT\' AND "RECIPIENT"=\'ed@e.com\'')
    )
    assert n == 0

    # ⭐ 那封信去哪了：撰寫者於「我的文件動態」（撰寫者視角）見此退回事件。
    # 前端把 resolved + REJECTED 映射為標籤「已退回」（dm/personal/schemas.ts）。
    # ⚠️ **必須指定 event_kind=="resolved"**：submitted 與 resolved 兩種事件都帶
    # `status=r.status`（送審紀錄的**目前**狀態），所以一筆已結案紀錄會產生兩個同 status 的
    # 事件。只比對 status 的話，resolved 那半整個壞掉（complete_date 沒寫、_TERMINAL 漏列）
    # 仍會通過——而被 Email 取代的正是「結果」這一半。
    act = await PersonalService().list_activity(db, user_id="ed", roles=[DM_EDITOR])
    assert any(
        a.review_id == r.review_id and a.event_kind == "resolved" and a.status == "REJECTED" for a in act.author
    ), "退回後撰寫者應於我的文件動態看到**結果**事件"


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


async def test_completed_帶出送審者與退回原因(db):
    """#657：已完成清單補「送審者」「退回原因」兩欄。

    送審者來源是 `DM_REVIEW.CREATED_USER`——該表**沒有**送審者欄位（只有 `ASSIGNED_REVIEWER`
    與 `APPROVER_USER_ID`），與我的文件動態的審核者視角同一來源（`personal/repository` 之
    `party_col=DmReview.created_user`）。
    """
    await _seed_user(db, "ed", "撰寫者甲", email="ed@e.com")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    _, _, r1 = await _new_submission(db, "DM-SOP-000657")
    await _svc.reject(db, review_id=r1.review_id, reason="格式不符，請補附件", op=_op("rev1"))
    _, _, r2 = await _new_submission(db, "DM-SOP-000658")
    await _svc.approve(db, review_id=r2.review_id, op=_op("rev1"))

    rows = {c.doc_id: c for c in (await _svc.list_completed(db, op=_op("rev1"), page=1, limit=20))["data"]}

    assert rows["DM-SOP-000657"].submitter_name == "撰寫者甲"
    assert rows["DM-SOP-000657"].reason == "格式不符，請補附件"
    # 正向錨點配對：核准列也要有送審者（證明 join 不是只在退回列生效），但原因留空
    assert rows["DM-SOP-000658"].submitter_name == "撰寫者甲"
    assert rows["DM-SOP-000658"].reason is None, "核准不是退回，不該有退回原因"


async def test_completed_廢止核准不帶廢止申請原因(db):
    """🔴 `DM_REVIEW.REASON` 一個欄位承載兩種語意，核准列不得把它當退回原因顯示。

    | 情境 | REASON 的內容 | 誰寫的 |
    |---|---|---|
    | 退回（REJECTED）| 退回原因 | 審核者 |
    | 廢止送審（OBSOLETE）| **廢止申請原因** | 申請人 |

    已完成清單含 `APPROVED` 列。廢止核准那筆的 `REASON` 裡是申請人寫的廢止申請原因，
    顯示在「退回原因」欄下是**錯的資訊**（不是缺漏）。規則與 #554 一致：僅 `REJECTED` 帶值
    （`personal/service.py` 已有同一條規則與註解）。

    ⚠️ 沒有這條測試的話，`reason=r.reason` 這種無條件帶出會全綠通過。
    """
    await _seed_user(db, "ed", "申請人乙", email="ed@e.com")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    doc = await _doc(db, "DM-SOP-000659", status="PENDING_OBSOLETE", current_version_id=None)
    v = await _add_version(db, "DM-SOP-000659", "1.0", status="PUBLISHED", published=utcnow())
    doc.current_version_id = v.version_id
    r = await _review(db, "DM-SOP-000659", v.version_id, review_type="OBSOLETE", reviewer="rev1")
    r.reason = "此 SOP 已由新制取代"  # 申請人於發起廢止時填寫
    await db.flush()
    await _svc.approve(db, review_id=r.review_id, op=_op("rev1"))

    row = next(c for c in (await _svc.list_completed(db, op=_op("rev1"), page=1, limit=20))["data"])
    assert row.status == "APPROVED", "前提錨點：這筆必須是核准，否則下面的斷言驗不到東西"
    assert row.reason is None, "廢止核准列不得把申請人寫的廢止申請原因當成退回原因帶出"
    assert row.submitter_name == "申請人乙"


async def test_廢止退回帶出審核者的退回原因且不覆寫申請原因(db):
    """#679：審核者對廢止申請寫的退回原因**先前無處可放**，申請人在任何畫面都看不到。

    `DM_REVIEW.REASON` 對 OBSOLETE 是**申請人寫的廢止申請原因**（`_reject_obsolete` 在
    `reject()` 覆寫後刻意寫回，那是申請理由唯一的存放處），於是審核者的退回原因只進了
    稽核與 `OBS_REJECT` 通知——而通知自 #554 起是 MSG、系統沒有站內訊息畫面。

    #679 新增 `REJECT_REASON` 欄位，`reject()` **不分 review_type 一律寫入**，語意唯一：
    它永遠是審核者寫的退回原因。`REASON` 則回歸單一語意（OBSOLETE 的申請理由）。

    ⚠️ 兩個都要驗：新欄位有值 **且** 申請人的原始廢止原因沒有被覆寫——後者是
    `_reject_obsolete` 那段「刻意寫回」的既有保證，不得因本次新增欄位而被改掉。
    """
    await _seed_user(db, "ed", "申請人丁", email="ed@e.com")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    doc = await _doc(db, "DM-SOP-000679", status="PENDING_OBSOLETE", current_version_id=None)
    v = await _add_version(db, "DM-SOP-000679", "1.0", status="PUBLISHED", published=utcnow())
    doc.current_version_id = v.version_id
    r = await _review(db, "DM-SOP-000679", v.version_id, review_type="OBSOLETE", reviewer="rev1")
    r.reason = "此 SOP 已由新制取代"  # 申請人於發起廢止時填寫
    await db.flush()

    await _svc.reject(db, review_id=r.review_id, reason="仍需沿用至年底，暫不廢止", op=_op("rev1"))

    assert r.reject_reason == "仍需沿用至年底，暫不廢止", "審核者的退回原因要有自己的欄位"
    assert r.reason == "此 SOP 已由新制取代", "申請人的廢止原因不得被覆寫（既有保證）"

    row = next(c for c in (await _svc.list_completed(db, op=_op("rev1"), page=1, limit=20))["data"])
    assert row.status == "REJECTED" and row.review_type == "OBSOLETE", "前提錨點"
    assert row.reason == "仍需沿用至年底，暫不廢止", "DM02 已完成要顯示審核者的退回原因"


async def test_新增與新版本的退回原因改由新欄位帶出(db):
    """`REJECT_REASON` 不分 review_type 一律寫入，故非廢止類也走同一條路。

    ⚠️ 這條釘住「改讀新欄位後既有情境不退化」。沒有它的話，把讀取端改成只看
    `reject_reason` 而忘了在 `reject()` 寫入，只有廢止那條測試會紅、這條情境會靜默變成「—」。
    """
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    _, _, r = await _new_submission(db, "DM-SOP-000680")
    await _svc.reject(db, review_id=r.review_id, reason="格式不符", op=_op("rev1"))

    assert r.reject_reason == "格式不符"
    row = next(c for c in (await _svc.list_completed(db, op=_op("rev1"), page=1, limit=20))["data"])
    assert row.reason == "格式不符"


async def test_completed_廢止退回顯示審核者原因而非申請人原因(db):
    """🔴 廢止退回列顯示的必須是**審核者**寫的退回原因，不得是申請人的廢止申請原因。

    ## 本條的歷程（三次改寫，意圖一次都沒變）

    | 版本 | 斷言 | 當時的實作 |
    |---|---|---|
    | #657 初版 | `row.reason is None` | 讀 `REASON`，而 OBSOLETE 的 `REASON` 是申請原因 ⇒ 只能整個不顯示 |
    | #679（本版）| `row.reason == 審核者寫的` 且 `!= 申請人寫的` | 讀 `REJECT_REASON`，語意唯一 |

    ⚠️ 改寫而**不是刪除**：這條守的意圖始終是「申請人的廢止申請原因不得出現在退回原因欄」。
    #657 時達成那件事的唯一方法是整個不顯示；#679 給了審核者的原因自己的欄位之後，
    同一個意圖變成「顯示對的那個」。若因為斷言變紅就刪掉，這個保護從此沒有測試。

    原 docstring 記的根因仍然成立，保留於下：

    `_reject_obsolete` 的 docstring 明載：退回廢止申請時會**刻意把申請人的原始廢止原因寫回**
    `review.reason`（那是 OBSOLETE 唯一存放申請理由之處，覆寫將永久失去可追溯性），而
    **審核者的退回原因僅入稽核**（`after_value.reject_reason`）與 OBS_REJECT 通知::

        obsolete_reason = review.reason          # 申請人寫的
        await self._reviews.reject(..., reason=reason)   # 覆寫成審核者寫的
        review.reason = obsolete_reason          # 還原

    ⇒ `review_type == OBSOLETE` 時，`REASON` **不論 status** 都是申請原因。
    正確判準是 `status == REJECTED AND review_type != OBSOLETE`。

    ⚠️ 本條是 `test_completed_廢止核准不帶廢止申請原因` 漏掉的另一半：那條只涵蓋
    OBSOLETE + **APPROVED**，而只看 status 的實作在 APPROVED 那側會正確、REJECTED 這側會漏。
    「兩個情境長得像」不代表同一個條件擋得住兩個。
    """
    await _seed_user(db, "ed", "申請人丙", email="ed@e.com")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    doc = await _doc(db, "DM-SOP-000661", status="PENDING_OBSOLETE", current_version_id=None)
    v = await _add_version(db, "DM-SOP-000661", "1.0", status="PUBLISHED", published=utcnow())
    doc.current_version_id = v.version_id
    r = await _review(db, "DM-SOP-000661", v.version_id, review_type="OBSOLETE", reviewer="rev1")
    r.reason = "此 SOP 已由新制取代"  # 申請人於發起廢止時填寫
    await db.flush()
    await _svc.reject(db, review_id=r.review_id, reason="仍需沿用，暫不廢止", op=_op("rev1"))

    row = next(c for c in (await _svc.list_completed(db, op=_op("rev1"), page=1, limit=20))["data"])
    assert row.status == "REJECTED" and row.review_type == "OBSOLETE", "前提錨點：必須是廢止退回"
    # `REASON` 仍是申請原因（`_reject_obsolete` 的既有保證），證明本條不是在驗一個不存在的情境
    assert r.reason == "此 SOP 已由新制取代"
    # 正向：顯示審核者寫的
    assert row.reason == "仍需沿用，暫不廢止"
    # 否定：與正向用同一個欄位比對，確保申請人的那段沒有混進來
    assert row.reason != "此 SOP 已由新制取代", "不得把申請人的廢止申請原因當成退回原因顯示"


async def test_completed_查無送審者帳號時_submitter_name_為_None(db):
    """`CREATED_USER` 無 FK（同 `ASSIGNED_REVIEWER`）→ 用 outerjoin，查無時回 None 由前端顯示「—」。

    不用 inner join：那會讓整列**從清單消失**，審核者看不到自己處理過的案件，比顯示「—」更糟。
    """
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    _, _, r = await _new_submission(db, "DM-SOP-000660", author="ghost657")  # DP_USER 查無此列
    await _svc.approve(db, review_id=r.review_id, op=_op("rev1"))

    page = await _svc.list_completed(db, op=_op("rev1"), page=1, limit=20)
    assert page["meta"]["total"] == 1, "送審者查無帳號不得讓整列消失（outerjoin 而非 join）"
    assert page["data"][0].submitter_name is None


# ── 催辦門檻（#503 第 1 項）─────────────────────────


async def _set_remind_threshold(db, days: int) -> None:
    """改寫 `DP_PARAM.DM_REMIND_THRESHOLD`（seed 預設 7）。"""
    await db.execute(
        update(DpParamDetail)
        .where(DpParamDetail.param_id == "DM_REMIND_THRESHOLD", DpParamDetail.param_key == "VALUE")
        .values(param_value=str(days))
    )
    await db.flush()


@pytest.mark.parametrize(
    ("threshold", "waited", "expected", "doc_id"),
    [
        (3, 5, True, "DM-SOP-000391"),  # 門檻調低：5 天就該標紅
        (14, 10, False, "DM-SOP-000392"),  # 門檻調高：10 天還不該標紅
    ],
)
async def test_pending_overdue_依催辦門檻判定(db, threshold, waited, expected, doc_id):
    """`overdue` 由後端讀 `DM_REMIND_THRESHOLD` 判定，不是前端寫死的 7（#503 第 1 項）。

    ⚠️ **兩筆刻意分居寫死值 7 的兩側**：5 天（< 7）期望標紅、10 天（> 7）期望不標紅。
    任一側的實作若退回「`waiting_days >= 7`」，該側的期望就會反過來而轉紅；
    只測其中一側的話，另一側的方向錯誤無人發現。
    """
    from datetime import timedelta

    await _set_remind_threshold(db, threshold)
    await _seed_user(db, "ed", "撰寫")
    await _doc(db, doc_id, status="PENDING_REVIEW")
    v = await _add_version(db, doc_id, "1.0", status="PENDING_REVIEW")
    await _review(db, doc_id, v.version_id, review_type="NEW", submit=utcnow() - timedelta(days=waited))

    page = await _svc.list_pending(db, op=_op("rev1"), page=1, limit=20)

    item = next(i for i in page["data"] if i.doc_id == doc_id)
    assert item.waiting_days == waited
    assert item.overdue is expected


# ── 撰寫者撤回後的簽核（#503 第 2 項）────────────────


async def test_approve_撤回後回_dm_review_009(db):
    """撰寫者撤回後審核者再核准 → `DM_REVIEW_009`（供前端顯示 DM-MSG-DM02-006）。

    與 `test_approve_non_pending_blocked`（已核准後再核准 → DM_REVIEW_003）成對：
    兩種終態要給不同訊息——「別人撤回了」與「你已經處理過了」對審核者是不同的事。
    """
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    _, _, r = await _new_submission(db, "DM-SOP-000360")
    await ReviewService().withdraw(db, r, operator="ed")

    with pytest.raises(AppError) as e:
        await _svc.approve(db, review_id=r.review_id, op=_op("rev1"))

    assert e.value.error_code == "DM_REVIEW_009"
    assert e.value.status_code == 409


async def test_reject_撤回後回_dm_review_009(db):
    """退回路徑同樣要區分撤回（兩個動作共用 `_complete`，但別只測其中一條）。"""
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    _, _, r = await _new_submission(db, "DM-SOP-000361")
    await ReviewService().withdraw(db, r, operator="ed")

    with pytest.raises(AppError) as e:
        await _svc.reject(db, review_id=r.review_id, reason="理由", op=_op("rev1"))

    assert e.value.error_code == "DM_REVIEW_009"


# ── 待簽核分頁（#503 第 3 項）───────────────────────


async def test_pending_分頁並維持停留最久在前(db):
    """待簽核改後端分頁（比照已完成）；排序仍為 `submit_date ASC`，不得因分頁而改變。"""
    from datetime import timedelta

    await _seed_user(db, "ed", "撰寫")
    now = utcnow()
    for n, days_ago in enumerate([10, 8, 6, 4, 2], start=1):  # 愈早送審 → 停留愈久 → 愈前面
        doc_id = f"DM-SOP-00037{n}"
        await _doc(db, doc_id, status="PENDING_REVIEW")
        v = await _add_version(db, doc_id, "1.0", status="PENDING_REVIEW")
        await _review(db, doc_id, v.version_id, review_type="NEW", submit=now - timedelta(days=days_ago))

    first = await _svc.list_pending(db, op=_op("rev1"), page=1, limit=2)
    second = await _svc.list_pending(db, op=_op("rev1"), page=2, limit=2)

    assert first["meta"] == {"total": 5, "page": 1, "limit": 2, "total_pages": 3}
    assert [i.doc_id for i in first["data"]] == ["DM-SOP-000371", "DM-SOP-000372"]
    assert [i.doc_id for i in second["data"]] == ["DM-SOP-000373", "DM-SOP-000374"]
    # 停留天數隨之遞減 → 證明「停留最久在前」跨頁仍成立
    assert first["data"][0].waiting_days > second["data"][-1].waiting_days


async def test_pending_超出頁數回空清單(db):
    """頁碼超出總頁數 → 空 data、meta 仍帶真實 total（與已完成一致）。"""
    await _seed_user(db, "ed", "撰寫")
    await _new_submission(db, "DM-SOP-000375")

    page = await _svc.list_pending(db, op=_op("rev1"), page=99, limit=20)

    assert page["data"] == [] and page["meta"]["total"] == 1


# ── 收件名單 ──────────────────────────────────────


async def test_recipients_all_audience_includes_viewers(db):
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    await _seed_user(db, "viewer_a", "閱覽A", email="va@e.com")
    await _grant(db, "viewer_a", DM_VIEWER)
    await _doc(db, "DM-SOP-000350", status="PUBLISHED", author="ed", audience=("全體",))
    emails = await _svc._repo.recipient_emails(db, "DM-SOP-000350")
    assert "va@e.com" in emails  # 全體 → 所有閱覽者
    assert "ed@e.com" not in emails  # #554：撰寫者不再收 Email（改由「我的文件動態」之「核准發布」）


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
    emails = await _svc._repo.recipient_emails(db, "DM-SOP-000351")
    assert "nurse@e.com" in emails and "soldier@e.com" not in emails
    assert "ed@e.com" not in emails  # #554：撰寫者不再收


# ── 催辦 ──────────────────────────────────────────


async def test_scan_overdue_reminds(db):
    from datetime import timedelta

    await _seed_user(db, "ed", "撰寫")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    # #627：催辦另驗 `DM_REVIEWER` 角色（詳見 `test_角色已撤的審核者不再收到催辦`）。
    # `_seed_user` 不給角色，故正向案例要自己補——這不是遷就守門：送簽時
    # `_ensure_assignable_reviewer`（#250）本就要求指定審核者具該角色，沒有角色的指派
    # 不是產品路徑造得出來的狀態。
    await _grant(db, "rev1", DM_REVIEWER)
    await _doc(db, "DM-SOP-000360", status="PENDING_REVIEW")
    v = await _add_version(db, "DM-SOP-000360", "1.0", status="PENDING_REVIEW")
    await _review(
        db, "DM-SOP-000360", v.version_id, review_type="NEW", reviewer="rev1", submit=utcnow() - timedelta(days=10)
    )
    count = await _svc.scan_overdue_and_remind(db, threshold_days=7)

    # ⭐ 斷言**可觀察的產出**而非回傳值（#627）：`count` 是本函式自己算的，無論有沒有真的寄出
    # 都會遞增——在 CHANNEL=MSG 的那段期間（2026-08-06～），這條測試全綠而催辦其實什麼都沒產生。
    # outbox 列才是「信真的排出去了」的證據。
    rows = (
        (
            await db.execute(
                select(DpEmailLog).where(DpEmailLog.template_code == "AUTO_REMIND", DpEmailLog.status == "PENDING")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, "逾期之 PENDING 應排入一封催辦信"
    assert rows[0].recipient == "rev1@e.com"
    assert "10" in rows[0].subject or "10" in rows[0].body, "停留天數應渲染進信件（{days} 佔位）"
    assert count == 1


async def test_範本停用時不排信且不計入催辦筆數(db, caplog):
    """範本停用 → 沒有產出，`count` 也不得計入（#627 AC：log 的數字必須與實際產出一致）。

    這條守的是 `count += 1` 無條件遞增那個缺陷的**一般形式**：不只 CHANNEL 不對會沒產出，
    範本停用、渲染失敗同樣沒產出，而三者都曾被算成「已催辦 N 筆」。

    ⚠️ **必須 `_grant(DM_REVIEWER)`，而且必須斷言跳過理由**。本條一度只斷言 `count == 0`
    與 outbox 零列，於是加上角色守門（#627）之後它**靜默地換了一條路**：`rev_off` 沒有角色
    → 在 `notify()` 之前就被攔掉 → 從此根本沒走到「範本停用」。兩個斷言在新路徑下同樣成立，
    所以**測試沒有變紅，卻已經不再測它宣稱在測的東西**（由 diff-cover 指出該分支零覆蓋才發現）。

    教訓：斷言「結果」而結果有不只一條路時，上游多一道守門就會把測試掏空而不留痕跡。
    故此處改為連「為什麼跳過」一起釘住。
    """
    await _seed_user(db, "ed_off", "撰寫")
    await _seed_user(db, "rev_off", "審核", email="rev_off@e.com")
    await _grant(db, "rev_off", DM_REVIEWER)
    await _doc(db, "DM-SOP-000361", status="PENDING_REVIEW")
    v = await _add_version(db, "DM-SOP-000361", "1.0", status="PENDING_REVIEW")
    await _review(
        db, "DM-SOP-000361", v.version_id, review_type="NEW", reviewer="rev_off", submit=utcnow() - timedelta(days=10)
    )
    await db.execute(
        update(DpNotifyTemplate)
        .where(DpNotifyTemplate.module == "DM", DpNotifyTemplate.template_code == "AUTO_REMIND")
        .values(is_enabled=False)
    )
    await db.flush()

    with caplog.at_level(logging.WARNING):
        count = await _svc.scan_overdue_and_remind(db, threshold_days=7)

    assert count == 0, "沒有產出就不得計入催辦筆數"
    assert await _auto_remind_rows(db) == 0
    # 錨點：證明真的走到「呼叫了 notify、但平台沒排入」這條路，而不是在更早的分支就被攔掉
    assert "催辦未排入 outbox" in caplog.text, "未走到 notify 之後的分支——上游可能多了一道守門把本條掏空"
    assert "TEMPLATE_DISABLED" in caplog.text, "跳過理由必須是範本停用，否則本條測的已不是它宣稱的情境"


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
    # #627：原本只驗 `count == 0` 與 caplog——但在 CHANNEL=MSG 期間**任何**情況都是 0 封，
    # 所以「跳過」這件事從未被真正驗證過。改 EMAIL 後這條斷言才第一次有鑑別力。
    assert await _auto_remind_rows(db) == 0, "跳過的催辦不得排入 outbox"
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
    # #627：原本只驗 `count == 0` 與 caplog——但在 CHANNEL=MSG 期間**任何**情況都是 0 封，
    # 所以「跳過」這件事從未被真正驗證過。改 EMAIL 後這條斷言才第一次有鑑別力。
    assert await _auto_remind_rows(db) == 0, "跳過的催辦不得排入 outbox"


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
    # #627：原本只驗 `count == 0` 與 caplog——但在 CHANNEL=MSG 期間**任何**情況都是 0 封，
    # 所以「跳過」這件事從未被真正驗證過。改 EMAIL 後這條斷言才第一次有鑑別力。
    assert await _auto_remind_rows(db) == 0, "跳過的催辦不得排入 outbox"
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
    await _grant(db, "rev395e", DM_REVIEWER)  # #627：不給角色會被前一個分支先攔下，驗不到本條
    await db.execute(update(DpUser).where(DpUser.user_id == "rev395e").values(email=""))
    await _doc(db, "DM-SOP-000399", status="PENDING_REVIEW")
    v = await _add_version(db, "DM-SOP-000399", "1.0", status="PENDING_REVIEW")
    await _review(
        db, "DM-SOP-000399", v.version_id, review_type="NEW", reviewer="rev395e", submit=utcnow() - timedelta(days=10)
    )

    with caplog.at_level(logging.WARNING):
        count = await _svc.scan_overdue_and_remind(db, threshold_days=7)

    assert count == 0
    # #627：原本只驗 `count == 0` 與 caplog——但在 CHANNEL=MSG 期間**任何**情況都是 0 封，
    # 所以「跳過」這件事從未被真正驗證過。改 EMAIL 後這條斷言才第一次有鑑別力。
    assert await _auto_remind_rows(db) == 0, "跳過的催辦不得排入 outbox"
    assert "查無審核者 Email" in caplog.text
    assert "審核者帳號已停用" not in caplog.text, "帳號是 ACTIVE，不該被歸成停用"


async def test_角色已撤的審核者不再收到催辦(db, caplog):
    """帳號 ACTIVE、但 `DM_REVIEWER` 角色已撤 → 不寄、留下自己那一類的 log（#627）。

    ## 為何這是獨立的一類，而不是 #395 已經處理過的

    #395 只確認了**帳號狀態**。「這個人現在還能不能處理這筆送審」另有角色這一維：
    角色撤銷走 `roles/assign_service` 的 `DmUserRole.deleted = 1`，**不碰
    `DM_REVIEW.ASSIGNED_REVIEWER`**；而簽核中心 router 掛 router-level
    `get_dm_reviewer_context`，角色一撤他連這筆送審都看不到。

    於是這個人處在最糟的組合——**催得到、做不了**，且案件永遠逾期、信永遠寄下去。
    `AUTO_REMIND` 還是 `MSG` 的期間此缺口零後果（根本沒寄信），#627 改 `EMAIL` 後才成立。

    ⚠️ 此處**走產品路徑撤角色**（`assign_roles_audiences`）而非直接 UPDATE：要驗的正是
    「產品做得出這個狀態」。若改成直接 UPDATE，這條就退化成在驗一個假想狀態。
    """
    from datetime import timedelta

    from app.dm.roles.assign_service import AssignService

    await _seed_user(db, "ed627a", "撰寫")
    await _seed_user(db, "rev627a", "已撤角色審核者", email="rev627a@e.com")
    await _grant(db, "rev627a", DM_REVIEWER)
    await _doc(db, "DM-SOP-000627", status="PENDING_REVIEW")
    v = await _add_version(db, "DM-SOP-000627", "1.0", status="PENDING_REVIEW")
    await _review(
        db, "DM-SOP-000627", v.version_id, review_type="NEW", reviewer="rev627a", submit=utcnow() - timedelta(days=10)
    )

    # 產品路徑撤銷角色（帳號仍 ACTIVE、EMAIL 仍在、DM_REVIEW.ASSIGNED_REVIEWER 不動）
    await AssignService().assign_roles_audiences(db, user_id="rev627a", roles=set(), audiences=set(), operator_id="adm")
    await db.flush()
    assert await db.scalar(select(DpUser.status).where(DpUser.user_id == "rev627a")) == "ACTIVE", (
        "前提錨點：帳號必須仍是 ACTIVE，否則下方跳過可能來自 #395 的停用分支"
    )

    with caplog.at_level(logging.WARNING):
        count = await _svc.scan_overdue_and_remind(db, threshold_days=7)

    assert count == 0
    assert await _auto_remind_rows(db) == 0, "角色已撤者不得排入 outbox"
    assert "審核者已無審核者角色" in caplog.text, "此類要有自己的分類：補救動作是改指派或補回角色"
    assert "審核者帳號已停用" not in caplog.text, "帳號是 ACTIVE，誤標成停用會讓人去翻停用清單而查無此人"


async def test_啟用中的審核者照常收到催辦(db):
    """回歸護欄：本次修正**只**排除非 ACTIVE 者，正常路徑不得受影響。"""
    from datetime import timedelta

    await _seed_user(db, "ed395c", "撰寫")
    await _seed_user(db, "rev395c", "正常審核者", email="rev395c@e.com")
    await _grant(db, "rev395c", DM_REVIEWER)  # #627：正向案例須具角色，見 test_scan_overdue_reminds
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
    # #503 起 /pending 回 {data, meta}（比照已完成頁籤之分頁形狀）
    assert resp.status_code == 200 and any(i["review_id"] == r.review_id for i in resp.json()["data"])
    resp2 = await client.post(f"/api/dm/reviews/{r.review_id}/approve", headers=h)
    assert resp2.status_code == 200 and resp2.json()["published_version_id"] == v.version_id


async def test_recipients_pair_excludes_other_unit_same_role(db):
    """文件開給「某單位的護理師」→ **其他單位的護理師不得收到發布通知**（#437）。

    收件名單是可見性的反向，兩者共用 `audience_pair_match`。此條專釘該共用關係：若本查詢退回
    只比職位（配對化前的寫法），所有單位的護理師都會收到含 `doc_name` / `change_summary` 的信——
    對看不到該文件的人洩漏其存在與摘要，且兩條既有收件測試（文件皆掛「全單位」）完全抓不到。
    """
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    await _seed_user(db, "mab_nurse", "軍醫局護理", email="mab_nurse@e.com")
    await _seed_user(db, "tsgh_nurse", "三總護理", email="tsgh_nurse@e.com")
    await _grant(db, "mab_nurse", DM_VIEWER)
    await _grant(db, "tsgh_nurse", DM_VIEWER)
    nurse_tag = await _audience_id(db, "護理師")
    mab = await _unit_id(db, "國防部軍醫局")
    tsgh = await _unit_id(db, "國防醫學院三軍總醫院")
    now = utcnow()
    db.add(DmUserTag(user_id="mab_nurse", tag_id=nurse_tag, unit_tag_id=mab, created_user="seed", created_date=now))
    db.add(DmUserTag(user_id="tsgh_nurse", tag_id=nurse_tag, unit_tag_id=tsgh, created_user="seed", created_date=now))
    await db.flush()
    await _doc(db, "DM-SOP-000352", status="PUBLISHED", author="ed", audience=("護理師",), unit="國防部軍醫局")

    emails = await _svc._repo.recipient_emails(db, "DM-SOP-000352")

    assert "mab_nurse@e.com" in emails  # 單位 + 職位皆相符
    assert "tsgh_nurse@e.com" not in emails  # 同職位但單位不符 → 不得收到
    assert "ed@e.com" not in emails  # #554：撰寫者改由站內動態承接，不再收 Email


# ── 收件人超過平台單次上限（#563）────────────────────


async def test_approve_publishes_when_recipients_exceed_platform_limit(db):
    """可見對象相符者超過平台單次上限時，核准發布**成功**且每個人都收得到（#563）。

    ## 為何這條測試非建 51 個使用者不可

    平台 `send_email` 對單次收件人數設上限（`MAX_RECIPIENTS`），超過即拋
    `AppError(422, DP_MAIL_002)`；該例外一路冒到 router，`get_db` 隨即 rollback 整個
    交易——文件沒轉 `PUBLISHED`、版本沒切、`DM_CHANGE_LOG` 沒寫、稽核沒寫。

    ⚠️ **這個缺陷的觸發條件被 fixture 的預設排除掉了**：其餘收件測試各建 2～3 位閱覽者，
    永遠碰不到上限。所以在本條之前，「CI 全綠」對這個缺陷**完全沒有證據力**——不是漏寫
    斷言，是情境從未被製造出來。故此處真的建到上限 + 1 人。

    三個斷言缺一不可：核准**成功**（擋住 rollback）、文件狀態與變更歷程**落地**（證明
    rollback 真的沒發生，不是 approve 回傳了但資料沒寫）、`DP_EMAIL_LOG` **一個都不少**
    （擋住「只寄給前 50 人」這種修法——那會讓第 51 人之後靜默收不到）。
    """
    total = MAX_RECIPIENTS + 1
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    for i in range(total):
        uid = f"zt_v{i:03d}"
        await _seed_user(db, uid, f"ZT 閱覽{i:03d}", email=f"{uid}@e.com")
        await _grant(db, uid, DM_VIEWER)
    doc, v, r = await _new_submission(db, "DM-SOP-000363", audience=("全體",))
    # ⚠️ 可見對象必須種在**版本層**：`approve` 會先跑 `apply_version_tags_to_doc`，以版本快照
    # 覆寫文件層生效值（#377）。只種文件層的話會在核准當下被清空，收件名單變成 0 人——
    # 那會讓本測試「通過」卻什麼都沒驗到。
    db.add(
        DmVersionTag(
            version_id=v.version_id,
            tag_id=await _audience_id(db, "全體"),
            unit_tag_id=await _unit_id(db, "全單位"),
            created_user="ed",
            created_date=utcnow(),
        )
    )
    await db.flush()

    res = await _svc.approve(db, review_id=r.review_id, op=_op("rev1"))

    # ① 核准成功，且通知數就是全體人數（不是被截到上限）
    assert res.published_version_id == v.version_id
    assert res.notified == total, f"應排入 {total} 封，實得 {res.notified}"

    # ② 業務寫入確實落地——若交易被 rollback，上面的回傳值仍在記憶體裡、但這裡會抓到舊值
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == "DM-SOP-000363"))
    assert doc.status == "PUBLISHED" and doc.current_version_id == v.version_id
    logs = await db.scalar(
        select(func.count())
        .select_from(DmChangeLog)
        .where(DmChangeLog.doc_id == "DM-SOP-000363", DmChangeLog.operation == "PUBLISH")
    )
    assert logs == 1

    # ③ outbox 逐人一列，一個都不少
    queued = await db.scalar(
        text(
            'SELECT count(*) FROM "DP_EMAIL_LOG" '
            "WHERE \"MODULE\" = 'DM' AND \"TEMPLATE_CODE\" = 'DOC_PUBLISH' AND \"STATUS\" = 'PENDING'"
        )
    )
    assert queued == total, f"DP_EMAIL_LOG 應有 {total} 列 PENDING，實得 {queued}"


async def test_approve_succeeds_when_publish_template_missing(db):
    """範本不存在時核准**仍成功**——通知失敗不得連坐業務交易（#563）。

    `DmNotifier` 本次起比照 `EtNotifier` 攔下 `AppError`。這是 DM **全部 8 個通知呼叫點**
    的行為變更，不只多人清單那一處：原本範本被刪 / 改 MODULE 會讓送審、廢止送審、核准、
    退回整個 rollback，現在改為靜默回 `SEND_FAILED`、操作照常完成。

    ⚠️ 本條釘的是**這個方向**（fail-open 而非 fail-closed）。單元測試只驗到 `DmNotifier`
    回傳什麼，驗不到「呼叫方的交易真的沒被回滾」——那要走真 DB。

    ⚠️ 代價寫在這裡供日後權衡：`DP_MAIL_001` 在**寫入任何列之前**發生，所以這條路徑連
    `DP_EMAIL_LOG` 都不會留下痕跡（下方斷言 0 列即是在陳述這件事）。「沒有人收到通知」
    目前只能從 `notified == 0` 看出來，而呼叫端沒有保留 `skipped_reason`。
    """
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    await _seed_user(db, "rev1", "審核", email="rev1@e.com")
    await _seed_user(db, "zt_vmiss", "ZT 閱覽", email="zt_vmiss@e.com")
    await _grant(db, "zt_vmiss", DM_VIEWER)
    doc, v, r = await _new_submission(db, "DM-SOP-000364", audience=("全體",))
    db.add(
        DmVersionTag(
            version_id=v.version_id,
            tag_id=await _audience_id(db, "全體"),
            unit_tag_id=await _unit_id(db, "全單位"),
            created_user="ed",
            created_date=utcnow(),
        )
    )
    await db.flush()
    # 把範本改名＝模擬「被刪 / 改 MODULE」；send_email 將拋 404 DP_MAIL_001
    await db.execute(
        text(
            'UPDATE "DP_NOTIFY_TEMPLATE" SET "TEMPLATE_CODE" = \'ZT_GONE\' '
            "WHERE \"MODULE\" = 'DM' AND \"TEMPLATE_CODE\" = 'DOC_PUBLISH'"
        )
    )
    await db.flush()

    res = await _svc.approve(db, review_id=r.review_id, op=_op("rev1"))

    # 正向錨點：業務寫入確實落地（若 AppError 冒出去，這裡會因 rollback 而拿到舊值）
    assert res.published_version_id == v.version_id
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == "DM-SOP-000364"))
    assert doc.status == "PUBLISHED"
    logs = await db.scalar(
        select(func.count())
        .select_from(DmChangeLog)
        .where(DmChangeLog.doc_id == "DM-SOP-000364", DmChangeLog.operation == "PUBLISH")
    )
    assert logs == 1
    # 通知那一側：一封都沒排入，且**連 FAILED 列都沒有**
    assert res.notified == 0
    queued = await db.scalar(
        text('SELECT count(*) FROM "DP_EMAIL_LOG" WHERE "MODULE" = \'DM\' AND "CALLER_MODULE" = \'DM\'')
    )
    assert queued == 0


async def test_recipients_exclude_disabled_but_keep_locked(db):
    """已停用帳號不列入發布通知；**暫時鎖定的仍列入**（#563）。

    本查詢原本只濾 `DELETED == 0`，而 `DP_USER.DELETED` 在本系統從不被設定（停用一律是
    `STATUS='DISABLED'`），等於沒有任何帳號狀態過濾——已停用 / 離職但角色未撤的人照樣收到
    含文件名稱與變更摘要的受控文件通知。

    ⚠️ 兩個方向都要釘：只斷言「停用者收不到」的話，改用 `account_usable_clause()`（連鎖定
    一起排除）也會通過，而那會讓被鎖 15 分鐘的同仁**永久少收**這一封——鎖定會自動解除，
    信不會重寄。
    """
    await _seed_user(db, "ed", "撰寫", email="ed@e.com")
    await _seed_user(db, "zt_ok", "ZT 正常", email="zt_ok@e.com")
    await _seed_user(db, "zt_off", "ZT 停用", email="zt_off@e.com")
    await _seed_user(db, "zt_lock", "ZT 鎖定", email="zt_lock@e.com")
    for uid in ("zt_ok", "zt_off", "zt_lock"):
        await _grant(db, uid, DM_VIEWER)
    await db.execute(update(DpUser).where(DpUser.user_id == "zt_off").values(status="DISABLED"))
    await db.execute(
        update(DpUser).where(DpUser.user_id == "zt_lock").values(locked_until=utcnow() + timedelta(minutes=15))
    )
    await db.flush()
    await _doc(db, "DM-SOP-000365", status="PUBLISHED", author="ed", audience=("全體",))

    emails = await _svc._repo.recipient_emails(db, "DM-SOP-000365")

    assert "zt_ok@e.com" in emails  # 正向錨點：這份名單真的有人，否則下面兩條恆真
    assert "zt_off@e.com" not in emails  # 停用 → 不該收到受控文件的名稱與摘要
    assert "zt_lock@e.com" in emails  # 鎖定是暫時的，明天就回來——不該少收
