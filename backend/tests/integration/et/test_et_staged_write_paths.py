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
from app.et.material.models import EtMaterial
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
    material_row = await db.scalar(select(EtMaterial).where(EtMaterial.material_id == material_item.material_id))
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
        # ⚠️ 取實際版本而非寫死 0：哪天建立流程多 bump 一次，寫死的那個會變成 409，
        # 而 409 一樣讓 xfail 通過 ⇒ `strict=True` 的提醒不會響（security review L-6）
        "material_version": material_row.version,
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
        True,
        lambda c, u, i: c.put(
            f"/api/et/materials/{i['material_id']}",
            # ⚠️ **必須給說明文字**：fixture 的教材是空殼（無影片無文件），送 `None` 會先被
            # `ET_MATERIAL_002`「至少提供一項媒材」擋成 422，本條就測不到它宣稱的事。
            # 🔴 2026-10-17 發現這條一直是為了這個理由 xfail，不是為了「寫了活表」——
            # 一個**為了錯的理由而通過**的 xfail，`strict=True` 想要的提醒永遠不會響
            # （security review L-6 指出的形狀，實際成因比它推測的還早一步）。
            json={"material_name": "改名教材", "description_html": "<p>說明</p>", "version": i["material_version"]},
            headers=_bearer(u),
        ),
    ),
    (
        "PUT /quizzes/{id}",
        True,
        lambda c, u, i: c.put(
            f"/api/et/quizzes/{i['quiz_id']}",
            json={"quiz_name": "改名測驗", "pass_score": 80, "max_retry": 3, "version": i["quiz_version"]},
            headers=_bearer(u),
        ),
    ),
    (
        "PUT /questions/{id}",
        True,
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
        True,
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


async def test_暫存模式回傳的_id_可以接著用(client, db) -> None:
    """🔴 **回傳的 id 必須能被下一個請求當作對象。**

    這條補的是「活表沒變」那組守門看不到的另一面：`add_chapter` 的暫存分支曾經回傳
    **正數**的 `STAGE_ID`（寫那段時還沒定下正負號規則，之後沒回去改）。活表確實沒變、
    守門全綠，但前端拿那個 id 去打 `/chapters/{id}/items` 會 404——或更糟，撞上某個
    真實章節而改到別的東西。

    ⭐ 那個 bug 是**既有測試的前置**抓到的（53 條紅），不是我的守門抓到的。教訓：
    「不該發生什麼」與「該發生什麼」要各有一條，前者單獨存在時會漏掉整個正向路徑。
    """
    uid = await _user(db, "ZT_RT1")
    ids = await _course_with_content(client, db, uid)
    await _publish(client, db, uid, ids["course_id"])

    ch = await client.post(
        f"{_COURSES}/{ids['course_id']}/chapters", json={"chapter_name": "暫存新章"}, headers=_bearer(uid)
    )
    assert ch.status_code == 201, ch.text
    new_chapter_id = ch.json()["chapter_id"]
    assert new_chapter_id < 0, "暫存新增的節點對外必須是負數 id"

    # 拿它當對象再打一次——這是前端實際會做的事
    item = await client.post(
        f"/api/et/chapters/{new_chapter_id}/items",
        json={"item_type": ITEM_MATERIAL, "title": "暫存新教材"},
        headers=_bearer(uid),
    )

    assert item.status_code == 201, f"回傳的 id 必須能接著用：{item.text}"
    assert item.json()["item_id"] < 0
    assert item.json()["material_id"] < 0


class TestStagedRead:
    """編輯頁讀暫存、他人與學員讀已生效版本（#631 PR 2a）。

    🔴 沒有這一半，教師**看不到自己剛做的編輯**——寫進暫存區但畫面還是舊的，
    他會以為系統壞了而重複操作。
    """

    async def test_擁有者看到暫存版本(self, client, db) -> None:
        uid = await _user(db, "ZT_SR1")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        await client.post(
            f"{_COURSES}/{ids['course_id']}/chapters", json={"chapter_name": "暫存新章"}, headers=_bearer(uid)
        )

        detail = await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(uid))

        names = [c["chapter_name"] for c in detail.json()["chapters"]]
        assert "暫存新章" in names, "教師必須看得到自己剛做的編輯"

    async def test_他人看到的是已生效版本(self, client, db) -> None:
        """🔴 他人閱覽與學員端一律看已生效版本。

        給他們看還沒生效的內容，會讓「這門課有什麼」出現兩種答案。
        """
        uid = await _user(db, "ZT_SR2")
        other = await _user(db, "ZT_SR3")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        await client.post(
            f"{_COURSES}/{ids['course_id']}/chapters", json={"chapter_name": "暫存新章"}, headers=_bearer(uid)
        )

        detail = await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(other))

        names = [c["chapter_name"] for c in detail.json()["chapters"]]
        assert "暫存新章" not in names, "他人不得看到尚未生效的內容"
        assert "第一章" in names

    async def test_既有內容回活表_id_新增的回負數(self, client, db) -> None:
        """⚠️ 前端把哪個數字帶回 PUT，決定後端改到哪一邊——回錯了不報錯，只改到別的東西。"""
        uid = await _user(db, "ZT_SR4")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        await client.post(
            f"{_COURSES}/{ids['course_id']}/chapters", json={"chapter_name": "暫存新章"}, headers=_bearer(uid)
        )

        chapters = (await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(uid))).json()["chapters"]
        by_name = {c["chapter_name"]: c["chapter_id"] for c in chapters}

        assert by_name["第一章"] == ids["chapter_id"], "既有章節回活表 id，與今天相同"
        assert by_name["暫存新章"] < 0, "本次編輯新增的回負數"

    async def test_還沒編輯過時讀活表(self, client, db) -> None:
        """正向錨點：少了它，把 `has_stage` 判斷拿掉（一律讀暫存）也會讓上面幾條通過。

        還沒編輯過時暫存區是空的，讀暫存會得到**一門沒有任何章節的課**。
        """
        uid = await _user(db, "ZT_SR5")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])

        detail = await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(uid))

        assert [c["chapter_name"] for c in detail.json()["chapters"]] == ["第一章", "第二章"]


class TestHasPendingChanges:
    """`CourseDetail.has_pending_changes`——前端據此啟用「更新」鈕與顯示提示（#631）。

    🔴 少了這個旗標，教師編完直接離開會以為學員已經看到了——而那正是本功能把生效
    延後所製造的**新**風險。
    """

    async def test_編輯後為真(self, client, db) -> None:
        uid = await _user(db, "ZT_P1")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        await client.post(
            f"{_COURSES}/{ids['course_id']}/chapters", json={"chapter_name": "暫存新章"}, headers=_bearer(uid)
        )

        detail = await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(uid))

        assert detail.json()["has_pending_changes"] is True

    async def test_尚未編輯時為假(self, client, db) -> None:
        """正向錨點：少了它，讓旗標恆為真也會讓上一條通過——而那會讓「更新」鈕
        永遠亮著，教師按下去得到一個什麼都沒做的 no-op。"""
        uid = await _user(db, "ZT_P2")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])

        detail = await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(uid))

        assert detail.json()["has_pending_changes"] is False

    async def test_草稿恆為假(self, client, db) -> None:
        """草稿的編輯本來就直接生效，沒有「尚未更新」這種狀態。"""
        uid = await _user(db, "ZT_P3")
        ids = await _course_with_content(client, db, uid)
        await client.post(
            f"{_COURSES}/{ids['course_id']}/chapters", json={"chapter_name": "草稿新章"}, headers=_bearer(uid)
        )

        detail = await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(uid))

        assert detail.json()["has_pending_changes"] is False

    async def test_他人看到的恆為假(self, client, db) -> None:
        """⚠️ 他人不該知道「這門課有人正在改」——那是擁有者的編輯狀態。"""
        uid = await _user(db, "ZT_P4")
        other = await _user(db, "ZT_P5")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        await client.post(
            f"{_COURSES}/{ids['course_id']}/chapters", json={"chapter_name": "暫存新章"}, headers=_bearer(uid)
        )

        detail = await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(other))

        assert detail.json()["has_pending_changes"] is False

    async def test_更新成功後回到假(self, client, db) -> None:
        """按下「更新」之後暫存區清空，提示應消失。"""
        uid = await _user(db, "ZT_P6")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        ch = await client.post(
            f"{_COURSES}/{ids['course_id']}/chapters", json={"chapter_name": "暫存新章"}, headers=_bearer(uid)
        )
        await client.post(
            f"/api/et/chapters/{ch.json()['chapter_id']}/items",
            json={"item_type": ITEM_MATERIAL, "title": "新教材"},
            headers=_bearer(uid),
        )
        applied = await client.post(f"{_COURSES}/{ids['course_id']}/content/apply", headers=_bearer(uid))
        assert applied.status_code == 200, applied.text

        detail = await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(uid))

        assert detail.json()["has_pending_changes"] is False
        assert "暫存新章" in [c["chapter_name"] for c in detail.json()["chapters"]], "更新後內容已在活表"
