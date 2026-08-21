"""系統儀表板（US7 / DM00）整合測試（真實 DB）。

驗證：統計卡（4 內建分類已發布目前版本數 + 總計；含 PENDING_OBSOLETE、排除 OBSOLETE/草稿/送審；
固定順序；0 亦顯示）；最新更新公告（近 30 天已發布、NEW/NEW_VERSION badge、DESC、無 review 預設 NEW、
空清單）；HTTP 存取閘。
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.utils import utcnow
from app.dm.catalog.models import DmTag
from app.dm.dashboard.service import DashboardService
from app.dm.document.models import DmDocTag, DmDocument, DmDocVersion
from app.dm.review.models import DmReview
from app.dm.roles.authz import DM_ADMIN, DM_VIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_svc = DashboardService()
# privileged 呼叫者（不受可見性過濾）——多數統計/公告測試以此驗核心計數
_PRIV = {"user_id": "adm", "roles": frozenset({DM_ADMIN})}


async def _tag_doc(db, doc_id, audience_name, *, user="seed"):
    tag_id = await db.scalar(
        select(DmTag.tag_id).where(DmTag.tag_group_code == "AUDIENCE", DmTag.tag_name == audience_name)
    )
    db.add(DmDocTag(doc_id=doc_id, tag_id=tag_id, created_user=user, created_date=utcnow()))
    await db.flush()


async def _seed_user(db, uid, name):
    now = utcnow()
    db.add(
        DpUser(
            user_id=uid,
            email=f"{uid}@e.com",
            pwd_hash="x",
            user_name=name,
            pwd_changed_date=now,
            created_user="seed",
            created_date=now,
        )
    )
    await db.flush()


async def _version(db, doc_id, version_no, *, status="PUBLISHED", published=None, author="ed", summary="摘要"):
    now = utcnow()
    v = DmDocVersion(
        doc_id=doc_id,
        version_no=version_no,
        change_summary=summary,
        file_name=f"{version_no}.pdf",
        file_path=f"/x/{doc_id}-{version_no}.pdf",
        file_size=100,
        file_mime="application/pdf",
        status=status,
        published_date=published,
        created_user=author,
        created_date=now,
    )
    db.add(v)
    await db.flush()
    return v


async def _doc(db, doc_id, *, category, status, current_version_id=None, author="ed", name=None):
    db.add(
        DmDocument(
            doc_id=doc_id,
            doc_name=name or f"文件{doc_id}",
            category_code=category,
            current_version_id=current_version_id,
            status=status,
            created_user=author,
            created_date=utcnow(),
        )
    )
    await db.flush()


async def _published_doc(
    db, doc_id, *, category, status="PUBLISHED", version_no="1.0", published=None, author="ed", name=None
):
    """建在架文件（doc + PUBLISHED 版本 + current_version_id）；回該版本。"""
    await _doc(db, doc_id, category=category, status=status, author=author, name=name)
    v = await _version(db, doc_id, version_no, status="PUBLISHED", published=published or utcnow(), author=author)
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == doc_id))
    doc.current_version_id = v.version_id
    await db.flush()
    return v


async def _approved_review(db, doc_id, version_id, review_type, author="ed"):
    now = utcnow()
    db.add(
        DmReview(
            doc_id=doc_id,
            version_id=version_id,
            review_type=review_type,
            assigned_reviewer="rev1",
            status="APPROVED",
            submit_date=now,
            complete_date=now,
            approver_user_id="rev1",
            created_user=author,
            created_date=now,
        )
    )
    await db.flush()


# ── 統計卡（FR-002）──────────────────────────────────


async def test_stats_counts_live_docs_per_category(db):
    """已發布目前版本數：含 PENDING_OBSOLETE（在架）、排除 OBSOLETE/草稿/送審；4 卡固定順序、0 亦顯示。"""
    await _published_doc(db, "DM-SOP-000001", category="SOP")
    await _published_doc(db, "DM-SOP-000002", category="SOP")
    await _published_doc(db, "DM-MANUAL-000001", category="MANUAL")
    await _published_doc(db, "DM-TRAINING-000001", category="TRAINING", status="PENDING_OBSOLETE")  # 在架 → 計入
    await _published_doc(db, "DM-SOP-000003", category="SOP", status="OBSOLETE")  # 已下架 → 不計
    await _doc(db, "DM-MANUAL-000002", category="MANUAL", status="DRAFT")  # 草稿 → 不計
    await _doc(db, "DM-SOP-000004", category="SOP", status="PENDING_REVIEW")  # 送審中 → 不計
    stats = await _svc.get_stats(db, **_PRIV)
    by_code = {i.category_code: i.count for i in stats.items}
    assert by_code == {"SOP": 2, "MANUAL": 1, "TRAINING": 1, "OTHER": 0}
    assert [i.category_code for i in stats.items] == ["SOP", "MANUAL", "TRAINING", "OTHER"]  # 固定順序
    assert stats.total == 4  # 2+1+1+0


async def test_stats_all_zero_when_no_published(db):
    stats = await _svc.get_stats(db, **_PRIV)
    assert stats.total == 0 and len(stats.items) == 4 and all(i.count == 0 for i in stats.items)


# ── 最新更新公告（FR-003/004）────────────────────────


async def test_announcements_recent_with_badge_and_desc(db):
    """近 30 天已發布：NEW/NEW_VERSION badge、發布時間 DESC、撰寫者姓名。"""
    await _seed_user(db, "ed", "陳大華")
    base = utcnow()
    v1 = await _published_doc(
        db, "DM-SOP-000010", category="SOP", version_no="2.0", published=base - timedelta(days=1), name="領血SOP"
    )
    await _approved_review(db, "DM-SOP-000010", v1.version_id, "NEW_VERSION")
    v2 = await _published_doc(
        db, "DM-TRAINING-000010", category="TRAINING", version_no="1.0", published=base, name="用血教材"
    )
    await _approved_review(db, "DM-TRAINING-000010", v2.version_id, "NEW")
    items = await _svc.get_announcements(db, **_PRIV)
    assert [i.doc_id for i in items] == ["DM-TRAINING-000010", "DM-SOP-000010"]  # 新者在前
    assert items[0].kind == "NEW" and items[1].kind == "NEW_VERSION"
    assert items[0].author_name == "陳大華" and items[1].version_no == "2.0"


async def test_announcements_excludes_older_than_30d(db):
    await _published_doc(db, "DM-SOP-000011", category="SOP", published=utcnow() - timedelta(days=40))
    items = await _svc.get_announcements(db, **_PRIV)
    assert items == []


async def test_announcements_kind_defaults_new_without_review(db):
    """發布版無對應 APPROVED review（種子）→ badge 預設 NEW。"""
    await _published_doc(db, "DM-SOP-000012", category="SOP", published=utcnow())
    items = await _svc.get_announcements(db, **_PRIV)
    assert len(items) == 1 and items[0].kind == "NEW"


async def test_announcements_empty_when_no_recent(db):
    items = await _svc.get_announcements(db, **_PRIV)
    assert items == []


# ── 可見性（Sec HIGH-1 / MEDIUM-1）──────────────────────


async def test_stats_and_announcements_apply_visibility(db):
    """閱覽者只見其可見範圍（全體 / 相符可見對象）；受限文件之計數與公告不外洩；privileged 見全部。"""
    await _seed_user(db, "v1", "閱覽者")  # v1 未被授予任何可見對象
    now = utcnow()
    await _published_doc(db, "DM-SOP-000030", category="SOP", published=now, name="全體SOP")
    await _tag_doc(db, "DM-SOP-000030", "全體")  # 全體 → 所有閱覽者可見
    await _published_doc(db, "DM-SOP-000031", category="SOP", published=now, name="護理師SOP")
    await _tag_doc(db, "DM-SOP-000031", "護理師")  # 僅護理師可見；v1 無此授權
    viewer = {"user_id": "v1", "roles": frozenset({DM_VIEWER})}

    v_stats = await _svc.get_stats(db, **viewer)
    assert next(i.count for i in v_stats.items if i.category_code == "SOP") == 1  # 僅全體
    v_ann = await _svc.get_announcements(db, **viewer)
    assert {a.doc_id for a in v_ann} == {"DM-SOP-000030"}

    p_stats = await _svc.get_stats(db, **_PRIV)
    assert next(i.count for i in p_stats.items if i.category_code == "SOP") == 2  # privileged 見全部
    p_ann = await _svc.get_announcements(db, **_PRIV)
    assert {a.doc_id for a in p_ann} == {"DM-SOP-000030", "DM-SOP-000031"}


# ── HTTP 存取閘 ──────────────────────────────────────


async def test_http_stats_requires_auth(db, client):
    resp = await client.get("/api/dm/dashboard/stats")
    assert resp.status_code == 401  # 無 token


async def test_http_forbidden_without_dm_role(db, client):
    """已登入但無任何 DM 角色 → 403 DM_AUTH_001。"""
    await _seed_user(db, "norole", "無角色")
    await db.flush()
    token = create_access_token(sub="norole", ttl_minutes=15)
    resp = await client.get("/api/dm/dashboard/stats", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403 and resp.json()["error_code"] == "DM_AUTH_001"


async def test_http_stats_and_announcements_ok(db, client):
    await _seed_user(db, "viewer1", "閱覽者")
    db.add(DmUserRole(user_id="viewer1", role_code=DM_VIEWER, created_user="seed", created_date=utcnow()))
    await _published_doc(db, "DM-SOP-000020", category="SOP", published=utcnow(), author="viewer1")
    await _tag_doc(db, "DM-SOP-000020", "全體")  # 掛全體 → 閱覽者可見（套可見性後始計入）
    await db.flush()
    token = create_access_token(sub="viewer1", ttl_minutes=15)
    h = {"Authorization": f"Bearer {token}"}
    s = await client.get("/api/dm/dashboard/stats", headers=h)
    assert s.status_code == 200 and s.json()["total"] >= 1
    a = await client.get("/api/dm/dashboard/announcements", headers=h)
    assert a.status_code == 200 and isinstance(a.json(), list)
