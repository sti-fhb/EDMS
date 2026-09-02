"""指定審核者下拉之帳號狀態過濾（#250 AC12，SA Q2=A）整合測試。

原本 `list_reviewers` 只濾 `DP_USER.DELETED`，未濾 `STATUS` / `LOCKED_UNTIL`——已停用、
永遠登不進系統的帳號只要仍具 `DM_REVIEWER`（停用不清角色）就會出現在送簽下拉，選中後
該送審無人可審、只能靠撰寫者撤回。本檔驗停用 / 鎖定中者不再出現。

**範圍**：只堵「新產生」的卡死。「送審當下正常、事後才被停用」之在途送審不在此處理
（SA Q2=A 明確排除，維持 US9 撰寫者撤回機制）。
"""

from datetime import timedelta

import pytest

from app.core.auth import create_access_token
from app.core.utils import utcnow
from app.dm.roles.authz import DM_EDITOR, DM_REVIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_URL = "/api/dm/reviewers"


def _headers(sub):
    return {"Authorization": f"Bearer {create_access_token(sub=sub, ttl_minutes=15)}"}


async def _seed_user(db, user_id, *, status="ACTIVE", locked_until=None):
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@e.com",
            pwd_hash="x",
            user_name=f"用戶{user_id}",
            status=status,
            locked_until=locked_until,
            pwd_changed_date=utcnow(),
            created_user="seed",
            created_date=utcnow(),
        )
    )
    await db.flush()


async def _grant(db, user_id, role):
    db.add(DmUserRole(user_id=user_id, role_code=role, created_user="seed", created_date=utcnow()))
    await db.flush()


async def test_reviewers_excludes_disabled_and_locked(db, client):
    """停用 / 鎖定中的審核者不出現；正常審核者與鎖定已逾時者仍出現。"""
    await _seed_user(db, "rv_author")
    await _grant(db, "rv_author", DM_EDITOR)

    await _seed_user(db, "rv_ok")
    await _grant(db, "rv_ok", DM_REVIEWER)
    await _seed_user(db, "rv_off", status="DISABLED")
    await _grant(db, "rv_off", DM_REVIEWER)
    await _seed_user(db, "rv_lock", locked_until=utcnow() + timedelta(hours=1))
    await _grant(db, "rv_lock", DM_REVIEWER)
    # 鎖定已逾時＝已自動解鎖，仍應可被指定（不可誤以 LOCKED_UNTIL 非空判定）
    await _seed_user(db, "rv_exp", locked_until=utcnow() - timedelta(minutes=1))
    await _grant(db, "rv_exp", DM_REVIEWER)

    r = await client.get(_URL, headers=_headers("rv_author"))
    assert r.status_code == 200
    ids = {item["user_id"] for item in r.json()}
    assert "rv_ok" in ids, "正常審核者應出現在下拉"
    assert "rv_exp" in ids, "鎖定已逾時者已自動解鎖，應出現在下拉"
    assert "rv_off" not in ids, "已停用帳號登不進系統，不應可被指定為審核者"
    assert "rv_lock" not in ids, "鎖定中帳號登不進系統，不應可被指定為審核者"


# ── 送簽時的伺服器端檢核（Code Review 發現：下拉過濾原為唯一落點，可被直接打 API 繞過）──


async def _pending_review_count(db, doc_id):
    from sqlalchemy import func, select

    from app.dm.review.models import DmReview

    return await db.scalar(select(func.count()).select_from(DmReview).where(DmReview.doc_id == doc_id))


async def _seed_doc(db, doc_id):
    """建最小文件列（DM_REVIEW.DOC_ID 為真 FK，送簽測試須有對應文件）。"""
    from app.dm.document.models import DmDocument

    db.add(
        DmDocument(
            doc_id=doc_id,
            doc_name=f"送簽測試{doc_id}",
            category_code="SOP",
            status="DRAFT",
            created_user="sub_author",
            created_date=utcnow(),
        )
    )
    await db.flush()


@pytest.mark.parametrize(
    "reviewer_state",
    [
        pytest.param({"status": "DISABLED"}, id="disabled"),
        pytest.param({"locked_until": "future"}, id="locked"),
    ],
)
async def test_submit_rejects_unusable_reviewer(db, reviewer_state):
    """送簽指定停用 / 鎖定中之審核者 → 422 DM_REVIEW_008，且不留下 review 列。

    下拉過濾只是 UI 便利；不擋在伺服器端的話，直接打送簽 API 仍可讓文件掛在一個
    永遠登不進系統的人身上（AC12 的保護目的落空）。
    """
    from app.core.exceptions import AppError
    from app.dm.review.service import ReviewService

    kwargs = dict(reviewer_state)
    if kwargs.pop("locked_until", None):
        kwargs["locked_until"] = utcnow() + timedelta(hours=1)
    await _seed_doc(db, "DM-SOP-999901")
    await _seed_user(db, "sub_rv", **kwargs)
    await _grant(db, "sub_rv", DM_REVIEWER)

    with pytest.raises(AppError) as e:
        await ReviewService().submit(
            db,
            doc_id="DM-SOP-999901",
            review_type="NEW",
            assigned_reviewer="sub_rv",
            author_id="sub_author",
            version_id=None,
        )
    assert e.value.status_code == 422 and e.value.error_code == "DM_REVIEW_008"
    assert await _pending_review_count(db, "DM-SOP-999901") == 0


async def test_submit_rejects_user_without_reviewer_role(db):
    """送簽指定「帳號正常但無 DM_REVIEWER 角色」者 → 同樣擋下。

    與下拉的可選名單同一組條件（下拉給什麼、送簽就只接受什麼），避免兩邊判準不一致。
    """
    from app.core.exceptions import AppError
    from app.dm.review.service import ReviewService

    await _seed_doc(db, "DM-SOP-999902")
    await _seed_user(db, "sub_ed")
    await _grant(db, "sub_ed", DM_EDITOR)  # 有 DM 角色但非審核者

    with pytest.raises(AppError) as e:
        await ReviewService().submit(
            db,
            doc_id="DM-SOP-999902",
            review_type="NEW",
            assigned_reviewer="sub_ed",
            author_id="sub_author",
            version_id=None,
        )
    assert e.value.status_code == 422 and e.value.error_code == "DM_REVIEW_008"


async def test_submit_accepts_usable_reviewer(db):
    """正常審核者可正常送簽（迴歸：新檢核不得擋掉合法送簽）。"""
    from app.dm.review.service import ReviewService

    await _seed_doc(db, "DM-SOP-999903")
    await _seed_user(db, "sub_ok")
    await _grant(db, "sub_ok", DM_REVIEWER)
    review = await ReviewService().submit(
        db,
        doc_id="DM-SOP-999903",
        review_type="NEW",
        assigned_reviewer="sub_ok",
        author_id="sub_author",
        version_id=None,
    )
    assert review.assigned_reviewer == "sub_ok" and review.status == "PENDING"
