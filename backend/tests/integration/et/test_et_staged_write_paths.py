"""已發布課程的內容編輯不得直接寫活表（#631 PR 2）。

## 🥇 本檔是整個 PR 2 真正的守門

把編輯端導向暫存區是**逐支方法改**的——29 個寫入端點各有一個分支。抽象擋不住「漏改
一處」：漏掉的那一支會悄悄維持即時生效，而那正是 #631 要修的缺陷本身，且**沒有任何
畫面或錯誤訊息會透露它**。

唯一擋得住的是**逐端點列舉**：對一門已發布課程打每一個內容編輯端點，斷言活表的內容樹
一個位元都沒變。

⛔ **不要因為某支端點「看起來很單純」而把它從清單裡拿掉。** 清單的價值在於它是**全集**；
少一條就等於那條從此沒有人檢查。

## 尚未導向暫存區的端點標 `xfail(strict=True)`

PR 2a 只做 course 模組；material / quiz / survey 留給 PR 2b。那些端點現在**會**寫活表，
故標為預期失敗。

⭐ `strict=True` 是刻意的：PR 2b 把它們改好之後，這些 xfail 會變成 `XPASS` 而**讓測試紅**
——那是在提醒「該把標記拿掉了」。用非 strict 的話，改好了也沒有人會發現標記還留著。
"""

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.constants import ITEM_MATERIAL, ITEM_QUIZ, QUESTION_SINGLE, ROLE_TEACHER, SURVEY_QUESTION_SINGLE
from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.course.stage_live_tree import load_live_tree
from app.et.quiz.models import EtQuestion, EtQuiz
from app.et.roles.models import EtUserRole
from app.et.survey.models import EtSurvey, EtSurveyQuestion
from tests.integration.et._tag_pairs import all_units_id

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str) -> str:
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@edms.local",
            pwd_hash=hash_password("Abcd1234"),
            user_name=f"測試{user_id}",
            status="ACTIVE",
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


async def _attach_tag(db, course_id: int) -> None:
    now = utcnow()
    tag = EtTag(
        tag_name=f"標籤{course_id}",
        is_active=True,
        is_builtin=False,
        created_user="SYSTEM",
        created_date=now,
        deleted=0,
    )
    db.add(tag)
    await db.flush()
    db.add(
        EtCourseTag(
            unit_tag_id=await all_units_id(db),
            course_id=course_id,
            tag_id=tag.tag_id,
            created_user="SYSTEM",
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()


async def _course_with_content(client, db, uid: str) -> dict[str, Any]:
    """建一門**內容齊全**的課程，回傳各層 id。

    齊全是刻意的：清單裡每一支端點都要有可打的對象，少建一種就會讓對應的那條
    測試因為「沒有東西可打」而假性通過。
    """
    now = utcnow().replace(microsecond=0)
    created = await client.post(
        _COURSES,
        json={
            "course_name": "守門測試課程",
            "open_start_at": (now - timedelta(days=1)).isoformat(),
            "open_end_at": (now + timedelta(days=30)).isoformat(),
        },
        headers=_bearer(uid),
    )
    assert created.status_code == 201, created.text
    cid = created.json()["course_id"]
    await _attach_tag(db, cid)

    ch = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(uid))
    chapter_id = ch.json()["chapter_id"]
    ch2 = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第二章"}, headers=_bearer(uid))
    chapter2_id = ch2.json()["chapter_id"]
    # 第二章也要有內容，否則課程會被 BLOCK_CHAPTER_EMPTY 擋住發布，
    # 整份守門測試會倒在前置而不是倒在它要驗的事情上。
    ch2_item = await client.post(
        f"/api/et/chapters/{chapter2_id}/items",
        json={"item_type": ITEM_MATERIAL, "title": "第二章教材"},
        headers=_bearer(uid),
    )
    assert ch2_item.status_code == 201, ch2_item.text

    mat = await client.post(
        f"/api/et/chapters/{chapter_id}/items",
        json={"item_type": ITEM_MATERIAL, "title": "教材甲"},
        headers=_bearer(uid),
    )
    assert mat.status_code == 201, mat.text
    quiz = await client.post(
        f"/api/et/chapters/{chapter_id}/items",
        json={"item_type": ITEM_QUIZ, "title": "小考"},
        headers=_bearer(uid),
    )
    assert quiz.status_code == 201, quiz.text
    quiz_id = quiz.json()["quiz_id"]
    q = await client.post(
        f"/api/et/quizzes/{quiz_id}/questions",
        json={
            "question_type": QUESTION_SINGLE,
            "stem": "題幹",
            "points": 100,
            "options": [{"option_text": "A", "is_correct": True}, {"option_text": "B", "is_correct": False}],
        },
        headers=_bearer(uid),
    )
    assert q.status_code == 201, q.text

    survey = await client.post(f"{_COURSES}/{cid}/survey", json={"survey_name": "課後問卷"}, headers=_bearer(uid))
    assert survey.status_code in (200, 201), survey.text
    survey_id = survey.json()["survey_id"]
    sq = await client.post(
        f"/api/et/surveys/{survey_id}/questions",
        json={
            "question_type": SURVEY_QUESTION_SINGLE,
            "stem": "滿意度",
            # ET_SURVEY_004：單選題至少 2 個選項
            "options": [{"option_text": "好"}, {"option_text": "普通"}],
        },
        headers=_bearer(uid),
    )
    assert sq.status_code == 201, sq.text
    await db.flush()

    item_rows = list(await db.scalars(select(EtItem).where(EtItem.chapter_id == chapter_id, EtItem.deleted == 0)))
    material_item = next(i for i in item_rows if i.material_id)
    quiz_item = next(i for i in item_rows if i.quiz_id)
    question = await db.scalar(select(EtQuestion).where(EtQuestion.quiz_id == quiz_id, EtQuestion.deleted == 0))
    sq_row = await db.scalar(
        select(EtSurveyQuestion).where(EtSurveyQuestion.survey_id == survey_id, EtSurveyQuestion.deleted == 0)
    )
    chapter = await db.scalar(select(EtChapter).where(EtChapter.chapter_id == chapter_id))
    quiz_row = await db.scalar(select(EtQuiz).where(EtQuiz.quiz_id == quiz_id))
    survey_row = await db.scalar(select(EtSurvey).where(EtSurvey.survey_id == survey_id))
    return {
        "course_id": cid,
        "chapter_id": chapter_id,
        "chapter2_id": chapter2_id,
        "chapter_version": chapter.version,
        "material_item_id": material_item.item_id,
        "material_id": material_item.material_id,
        "quiz_item_id": quiz_item.item_id,
        "quiz_id": quiz_id,
        "quiz_version": quiz_row.version,
        "question_id": question.question_id,
        "question_version": question.version,
        "survey_id": survey_id,
        "survey_version": survey_row.version,
        "sq_id": sq_row.sq_id,
        "sq_version": sq_row.version,
    }


async def _publish(client, db, uid: str, cid: int) -> None:
    r = await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(uid))
    assert r.status_code == 200, r.text
    await db.flush()


async def _refresh_versions(db, ids: dict) -> None:
    """呼叫前重讀各實體的 `VERSION`。

    ⚠️ **發布會遞增課程的 `VERSION`**，所以前置時抓的值到了「已發布」那半就過期，
    帶著它打重排端點會吃 409 `ET_LOCK_001`——那是測試自己的前置錯誤，不是守門發現
    了什麼。兩個方向的測試共用本函式，才不會只在其中一邊對。
    """
    course = await db.scalar(select(EtCourse).where(EtCourse.course_id == ids["course_id"]))
    chapter = await db.scalar(select(EtChapter).where(EtChapter.chapter_id == ids["chapter_id"]))
    ids["course_version"] = course.version
    ids["chapter_version"] = chapter.version


async def _fingerprint(db, course_id: int) -> tuple:
    """活表內容樹的指紋——**每一列的每一個內容欄位**都算進去。

    只比「有幾列」會讓「改了標題」這種就地更新完全看不出來。
    """
    return tuple(
        (
            n.entity_type,
            n.key[1],
            n.sort_order,
            tuple(
                sorted(
                    (c.key, getattr(n.row, c.key))
                    for c in n.row.__mapper__.column_attrs
                    if c.key not in {"created_date", "updated_date", "created_user", "updated_user"}
                )
            ),
        )
        for n in await load_live_tree(db, course_id)
    )


# ── 內容編輯端點全集 ──────────────────────────────────────────────────────────
#
# 每一項是 `(標籤, 是否已導向暫存區, 呼叫函式)`。
# ⛔ 新增內容編輯端點時**必須**補進這張表，否則它從此沒有人檢查。

_COURSE_MODULE = [
    (
        "POST /courses/{id}/chapters",
        True,
        lambda c, u, i: c.post(
            f"{_COURSES}/{i['course_id']}/chapters", json={"chapter_name": "新章"}, headers=_bearer(u)
        ),
    ),
    (
        "PUT /courses/{id}/chapters/order",
        True,
        lambda c, u, i: c.put(
            f"{_COURSES}/{i['course_id']}/chapters/order",
            json={"chapter_ids": [i["chapter2_id"], i["chapter_id"]], "version": i["course_version"]},
            headers=_bearer(u),
        ),
    ),
    (
        "PUT /chapters/{id}",
        True,
        lambda c, u, i: c.put(
            f"/api/et/chapters/{i['chapter_id']}",
            json={"chapter_name": "改名", "version": i["chapter_version"]},
            headers=_bearer(u),
        ),
    ),
    (
        "DELETE /chapters/{id}",
        True,
        lambda c, u, i: c.delete(f"/api/et/chapters/{i['chapter2_id']}", headers=_bearer(u)),
    ),
    (
        "POST /chapters/{id}/items",
        True,
        lambda c, u, i: c.post(
            f"/api/et/chapters/{i['chapter_id']}/items",
            json={"item_type": ITEM_MATERIAL, "title": "新教材"},
            headers=_bearer(u),
        ),
    ),
    (
        "PUT /chapters/{id}/items/order",
        True,
        lambda c, u, i: c.put(
            f"/api/et/chapters/{i['chapter_id']}/items/order",
            # ⚠️ 項目重排的併發令牌是**章節**的 version，不是課程的
            json={"item_ids": [i["quiz_item_id"], i["material_item_id"]], "version": i["chapter_version"]},
            headers=_bearer(u),
        ),
    ),
    (
        "DELETE /items/{id}",
        True,
        lambda c, u, i: c.delete(f"/api/et/items/{i['material_item_id']}", headers=_bearer(u)),
    ),
]

_OTHER_MODULES = [
    (
        "PUT /materials/{id}",
        False,
        lambda c, u, i: c.put(
            f"/api/et/materials/{i['material_id']}",
            json={"material_name": "改名教材", "description_html": None, "version": 0},
            headers=_bearer(u),
        ),
    ),
    (
        "PUT /quizzes/{id}",
        False,
        lambda c, u, i: c.put(
            f"/api/et/quizzes/{i['quiz_id']}",
            json={"quiz_name": "改名測驗", "pass_score": 80, "max_retry": 3, "version": i["quiz_version"]},
            headers=_bearer(u),
        ),
    ),
    (
        "PUT /questions/{id}",
        False,
        lambda c, u, i: c.put(
            f"/api/et/questions/{i['question_id']}",
            json={
                "question_type": QUESTION_SINGLE,
                "stem": "改過的題幹",
                "points": 100,
                "options": [{"option_text": "A", "is_correct": True}, {"option_text": "B", "is_correct": False}],
                "version": i["question_version"],
            },
            headers=_bearer(u),
        ),
    ),
    (
        "DELETE /questions/{id}",
        False,
        lambda c, u, i: c.delete(f"/api/et/questions/{i['question_id']}", headers=_bearer(u)),
    ),
    (
        "PUT /surveys/{id}",
        False,
        lambda c, u, i: c.put(
            f"/api/et/surveys/{i['survey_id']}",
            json={"survey_name": "改名問卷", "is_active": True, "version": i["survey_version"]},
            headers=_bearer(u),
        ),
    ),
    (
        "PUT /survey-questions/{id}",
        False,
        lambda c, u, i: c.put(
            f"/api/et/survey-questions/{i['sq_id']}",
            json={
                "question_type": SURVEY_QUESTION_SINGLE,
                "stem": "改過的問卷題",
                "options": [{"option_text": "好"}, {"option_text": "普通"}],
                "version": i["sq_version"],
            },
            headers=_bearer(u),
        ),
    ),
    (
        "DELETE /survey-questions/{id}",
        False,
        lambda c, u, i: c.delete(f"/api/et/survey-questions/{i['sq_id']}", headers=_bearer(u)),
    ),
]

_ALL = _COURSE_MODULE + _OTHER_MODULES


@pytest.mark.parametrize(
    ("label", "call"),
    [
        pytest.param(
            label,
            call,
            id=label,
            marks=[] if staged else [pytest.mark.xfail(strict=True, reason="PR 2b 才導向暫存區")],
        )
        for label, staged, call in _ALL
    ],
)
async def test_已發布課程的內容編輯不得直接寫活表(label: str, call, client, db) -> None:
    """🥇 PR 2 的核心守門——逐端點列舉，缺一條就等於那條從此沒人檢查。"""
    uid = await _user(db, f"ZT_W{abs(hash(label)) % 10000}")
    ids = await _course_with_content(client, db, uid)
    await _publish(client, db, uid, ids["course_id"])

    await _refresh_versions(db, ids)
    before = await _fingerprint(db, ids["course_id"])
    resp = await call(client, uid, ids)
    await db.flush()
    after = await _fingerprint(db, ids["course_id"])

    assert resp.status_code < 400, f"{label} 應成功（寫進暫存區），實際 {resp.status_code}：{resp.text}"
    assert after == before, f"{label} 直接改動了活表——已發布課程的編輯必須先進暫存區"


@pytest.mark.parametrize(
    ("label", "call"),
    [pytest.param(label, call, id=label) for label, _staged, call in _COURSE_MODULE],
)
async def test_草稿課程的內容編輯仍直接寫活表(label: str, call, client, db) -> None:
    """🥇 **正向錨點**——少了它，把那些端點改成「什麼都不做」也會讓上一條通過。

    草稿沒有學員、不需版本化，行為必須完全不變。
    """
    uid = await _user(db, f"ZT_D{abs(hash(label)) % 10000}")
    ids = await _course_with_content(client, db, uid)

    await _refresh_versions(db, ids)
    before = await _fingerprint(db, ids["course_id"])
    resp = await call(client, uid, ids)
    await db.flush()
    after = await _fingerprint(db, ids["course_id"])

    assert resp.status_code < 400, f"{label} 於草稿應成功，實際 {resp.status_code}：{resp.text}"
    assert after != before, f"{label} 於草稿課程應**立即**改動活表"
