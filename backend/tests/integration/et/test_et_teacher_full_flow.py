"""教師端完整作業流程（ET-14 / #341 T116 / AC 1）。

## 這一檔補的接縫

與 `test_et_student_full_flow.py` 同一個理由：既有測試逐段都有（`test_et_course_crud.py` 48 條、
`test_et_item_crud.py` 21 條、`test_et_material.py` 29 條、`test_et_quiz.py` 26 條、
`test_et_publish.py` 17 條、`test_et_tag_invite.py` 8 條、`test_et_tracking.py` 55 條），
**但沒有一條把它們串起來走完**。

本檔特別針對三個**只在串起來時才存在**的接縫：

1. **發布 → 自動帶入標籤學員 → 寄邀請信**：三者由同一次 `POST /publish` 觸發。既有的
   `test_et_tag_invite.py` 驗的是 `target_user_ids()` 這支查詢，`test_et_tag_invite_notify.py`
   驗寄信，但「發布這個動作是否真的把兩者都觸發了」在既有測試裡是分開的
2. **Email 邀請 → 信中 token → accept → 在籍**：`test_et_invitation.py` 驗發信與 token 雜湊，
   但 accept 之後那個人能不能真的被 ET03 追蹤到，跨過了 invitation 與 tracking 兩個模組
3. **追蹤三區塊對「真的有作答 / 真的填過問卷」的資料**：`test_et_tracking.py` 55 條的作答與
   填答紀錄多由 `db.add(...)` 造出，本檔的是學員真的打 API 產生的

## 不重複驗的部分

各段內部的邏輯（欄位驗證、權限、版本鎖、六項發布檢核的組合）既有測試已充分涵蓋，
本檔只走 happy path 並在接縫處斷言。
"""

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.notify.models import DpEmailLog
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag, EtUserTag
from app.et.constants import (
    COURSE_PUBLISHED,
    ITEM_MATERIAL,
    ITEM_QUIZ,
    QUESTION_SINGLE,
    ROLE_STUDENT,
    ROLE_TEACHER,
    SOURCE_EMAIL_INVITE,
    SOURCE_TAG_DEFAULT,
    SURVEY_QUESTION_SINGLE,
)
from app.et.progress.models import EtEnrollment
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str, role: str = ROLE_STUDENT, *, email: str | None = None) -> str:
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=email or f"{user_id}@edms.local",
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
    db.add(EtUserRole(user_id=user_id, role=role, is_active=True, created_user="SYSTEM", created_date=now, deleted=0))
    await db.flush()
    return user_id


async def _tag(db, name: str) -> int:
    tag = EtTag(
        tag_name=name, is_active=True, is_builtin=False, created_user="SYSTEM", created_date=utcnow(), deleted=0
    )
    db.add(tag)
    await db.flush()
    return tag.tag_id


async def _invite_token(db, email: str) -> str:
    """由 outbox 取出課程邀請信的明文 token。"""
    log = await db.scalar(
        select(DpEmailLog).where(
            DpEmailLog.recipient == email,
            DpEmailLog.template_code == "COURSE_INVITE",
            DpEmailLog.status == "PENDING",
        )
    )
    assert log is not None, f"未寄出邀請信給 {email}"
    marker = "/et/invite?token="
    start = log.body.index(marker) + len(marker)
    end = start
    while end < len(log.body) and log.body[end] not in '\n \r"<':
        end += 1
    return log.body[start:end]


async def test_教師從建立課程到看見學員成果的完整流程(client, db) -> None:
    """AC 1 的完整鏈：建立 → 掛標籤 → 編章節 / 教材 / 測驗 → 建問卷 → 設起訖 → 發布
    （自動邀請）→ Email 邀請 → 追蹤三區塊。
    """
    teacher = await _user(db, "t_tflow", ROLE_TEACHER)
    tagged_student = await _user(db, "s_tagged")
    invited_student = await _user(db, "s_invited", email="invited-flow@x.gov.tw")

    # ── 階段 1：建立課程並設定起訖時間 ───────────────────────────────────────
    created = await client.post(
        _COURSES,
        json={
            "course_name": "檢驗作業品質管理",
            "open_start_at": "2026-01-01T00:00:00Z",
            "open_end_at": "2027-12-31T00:00:00Z",
        },
        headers=_bearer(teacher),
    )
    assert created.status_code == 201, created.text
    course_id = created.json()["course_id"]

    # ── 階段 2：掛受訓單位標籤（發布時據此自動帶入學員）──────────────────────
    unit_tag = await _tag(db, f"檢驗科{course_id}")
    db.add(EtCourseTag(course_id=course_id, tag_id=unit_tag, created_user="SYSTEM", created_date=utcnow(), deleted=0))
    db.add(EtUserTag(user_id=tagged_student, tag_id=unit_tag, created_user="SYSTEM", created_date=utcnow(), deleted=0))
    await db.flush()

    # ── 階段 3：編排章節 → 教材 → 測驗（含題目）─────────────────────────────
    chapter = await client.post(
        f"{_COURSES}/{course_id}/chapters", json={"chapter_name": "第一章 品管概論"}, headers=_bearer(teacher)
    )
    assert chapter.status_code == 201, chapter.text
    chapter_id = chapter.json()["chapter_id"]

    material = await client.post(
        f"/api/et/chapters/{chapter_id}/items",
        json={"item_type": ITEM_MATERIAL, "title": "品管手冊導讀"},
        headers=_bearer(teacher),
    )
    assert material.status_code == 201, material.text
    filled = await client.put(
        f"/api/et/materials/{material.json()['material_id']}",
        json={
            "material_name": "品管手冊導讀",
            "description_html": "<p>請詳閱品管手冊第一章。</p>",
            "doc_ids": [],
            "video_ids": [],
            "version": 0,
        },
        headers=_bearer(teacher),
    )
    assert filled.status_code == 204, filled.text

    quiz = await client.post(
        f"/api/et/chapters/{chapter_id}/items",
        json={"item_type": ITEM_QUIZ, "title": "品管小考"},
        headers=_bearer(teacher),
    )
    assert quiz.status_code == 201, quiz.text
    quiz_id = quiz.json()["quiz_id"]
    question = await client.post(
        f"/api/et/quizzes/{quiz_id}/questions",
        json={
            "question_type": QUESTION_SINGLE,
            "stem": "品管圖用途為何？",
            "points": 100,
            "options": [
                {"option_text": "監控分析流程穩定度", "is_correct": True},
                {"option_text": "統計出勤", "is_correct": False},
            ],
        },
        headers=_bearer(teacher),
    )
    assert question.status_code == 201, question.text
    correct_option = next(o["option_id"] for o in question.json()["options"] if o["is_correct"])

    # ── 階段 4：建立課後問卷 ─────────────────────────────────────────────────
    survey = await client.post(
        f"{_COURSES}/{course_id}/survey", json={"survey_name": "課後回饋"}, headers=_bearer(teacher)
    )
    assert survey.status_code == 201, survey.text
    sq = await client.post(
        f"/api/et/surveys/{survey.json()['survey_id']}/questions",
        json={
            "question_type": SURVEY_QUESTION_SINGLE,
            "stem": "課程內容是否實用？",
            "options": [{"option_text": "實用"}, {"option_text": "普通"}],
        },
        headers=_bearer(teacher),
    )
    assert sq.status_code == 201, sq.text

    # ── 階段 5：發布前預檢應全數通過 ─────────────────────────────────────────
    check = await client.get(f"{_COURSES}/{course_id}/publish-check", headers=_bearer(teacher))
    assert check.status_code == 200, check.text
    assert check.json()["can_publish"] is True, f"逐步建齊後應可發布，實得 {check.json()['blockers']}"

    # ── 階段 6：發布——同一個動作要同時做成三件事 ────────────────────────────
    published = await client.post(f"{_COURSES}/{course_id}/publish", headers=_bearer(teacher))
    assert published.status_code == 200, published.text
    invitation_code = published.json()["invitation_code"]
    assert invitation_code, "發布應產出邀請碼"

    # (a) 狀態轉為已發布
    detail = await client.get(f"{_COURSES}/{course_id}", headers=_bearer(teacher))
    assert detail.json()["status"] == COURSE_PUBLISHED

    # (b) 掛同一標籤的學員被自動帶入（來源記為標籤帶入）
    auto = await db.scalar(
        select(EtEnrollment).where(
            EtEnrollment.course_id == course_id,
            EtEnrollment.user_id == tagged_student,
            EtEnrollment.deleted == 0,
        )
    )
    assert auto is not None, "發布未帶入掛該標籤的學員"
    assert auto.join_source == SOURCE_TAG_DEFAULT

    # (c) 該學員收到邀請信——既有測試分別驗過「帶入」與「寄信」，此處驗的是
    #     「同一次發布把兩者都做了」
    tag_mail = await db.scalar(
        select(DpEmailLog).where(DpEmailLog.recipient == f"{tagged_student}@edms.local", DpEmailLog.status == "PENDING")
    )
    assert tag_mail is not None, "被標籤帶入的學員未收到通知信"

    # ── 階段 7：另以 Email 邀請一位學員，並走完他那側的 accept ────────────────
    invited = await client.post(
        f"{_COURSES}/{course_id}/invitations",
        json={"emails": "invited-flow@x.gov.tw"},
        headers=_bearer(teacher),
    )
    assert invited.status_code == 200, invited.text

    token = await _invite_token(db, "invited-flow@x.gov.tw")
    accepted = await client.post("/api/et/invitations/accept", json={"token": token}, headers=_bearer(invited_student))
    assert accepted.status_code == 200, accepted.text

    by_mail = await db.scalar(
        select(EtEnrollment).where(
            EtEnrollment.course_id == course_id,
            EtEnrollment.user_id == invited_student,
            EtEnrollment.deleted == 0,
        )
    )
    assert by_mail is not None and by_mail.join_source == SOURCE_EMAIL_INVITE

    # ── 階段 8：讓其中一位學員真的作答與填問卷（追蹤的資料來源）────────────────
    h = _bearer(tagged_student)
    await client.post(f"/api/et/items/{material.json()['item_id']}/viewed", headers=h)
    attempt = await client.post(f"/api/et/quizzes/{quiz_id}/attempts", headers=h)
    assert attempt.status_code == 201, attempt.text
    await client.put(
        f"/api/et/attempts/{attempt.json()['attempt_id']}/answers/{question.json()['question_id']}",
        json={"selected_options": [correct_option]},
        headers=h,
    )
    submitted = await client.post(f"/api/et/attempts/{attempt.json()['attempt_id']}/submit", headers=h)
    assert submitted.status_code == 200, submitted.text
    survey_sent = await client.post(
        f"{_COURSES}/{course_id}/survey/response",
        json={"answers": [{"sq_id": sq.json()["sq_id"], "so_id": sq.json()["options"][0]["so_id"]}]},
        headers=h,
    )
    assert survey_sent.status_code == 201, survey_sent.text

    # ── 階段 9：ET03 三區塊都看得到真實資料 ──────────────────────────────────
    students = await client.get(f"{_COURSES}/{course_id}/students", headers=_bearer(teacher))
    assert students.status_code == 200, students.text
    listed = {r["user_id"] for r in students.json()["data"]}
    assert listed == {tagged_student, invited_student}, f"兩種來源的學員都該在清單裡，實得 {listed}"

    overview = await client.get(f"{_COURSES}/{course_id}/attempt-overview", headers=_bearer(teacher))
    assert overview.status_code == 200, overview.text
    answered = {s["user_id"] for s in overview.json()["students"]}
    assert answered == {tagged_student}, f"區塊 2 只列曾作答者，實得 {answered}"

    result = await client.get(f"{_COURSES}/{course_id}/survey-result", headers=_bearer(teacher))
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["has_survey"] is True
    assert body["filled_count"] == 1 and body["not_filled_count"] == 1, (
        f"一位填過、一位沒填，母體為在籍學員，實得 {body['filled_count']} / {body['not_filled_count']}"
    )
