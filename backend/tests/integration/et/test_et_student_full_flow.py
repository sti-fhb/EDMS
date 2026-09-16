"""學員端完整作業流程（ET-14 / #341 T117 / AC 2）。

## 這一檔與既有 662+ 條的差別

既有測試每一條都只驗**單一功能面**：`test_et_enrollment.py` 驗加入、`test_et_progress.py`
驗進度、`test_et_attempt.py` 驗作答、`test_et_survey_fill.py` 驗問卷。每一段都有人把關，
**但沒有任何一條把它們串起來走完**。

差別不是形式問題。單一功能面的測試必須**自己造出前一段的產物**，而造出來的東西與真實
產物之間的落差，正是接縫 bug 的棲地。本檔走完整條鏈，所以每一步吃的都是真產物：

| 既有測試造的 | 本檔用的 |
|---|---|
| `db.add(EtEnrollment(...))` 直接建在籍列 | `POST /api/et/enrollments` 帶**發布時真的產出的邀請碼** |
| `db.add(EtProgress(is_completed=True))` 造完成項目 | `POST /items/{id}/viewed` 與**真的通過測驗** |
| `db.add(EtUserRole(role=STUDENT))` 造 ET 學員角色 | DP 驗證通過時由 `module_provisioning_gate` **真的授予** |
| 單一教材項目的課程 | 教材 + 測驗**兩種項目**，缺一不完課 |

> ⚠️ 這些**不是**「既有測試漏驗」的清單。完課推導（`is_course_completed`）、作答回寫項目
> 完成（`test_et_attempt.py::test_單選答對得滿分並回寫項目完成`）、問卷入口狀態機各自都有
> 人把關，實測把 `is_course_completed` 改成恆偽會讓既有的 `test_et_survey_fill.py` 紅掉 24 條。
> **本檔驗的是這些零件組起來會動**——尤其「多項目課程要兩種項目都由真實動作完成才完課」
> 這件事，在既有的單項目 + 造假 progress 列的形狀下不會被觸及。

本檔**不重複驗各段內部的邏輯**（那些既有測試已充分涵蓋，見 #341 的覆蓋盤點留言）。

## 為什麼寫成一條長測試而不是拆開

拆成「加入」「學習」「作答」「完課」「問卷」五條、各自建前置資料，就退化回既有測試的形狀，
**接縫又沒人驗了**。本檔刻意讓每一步吃前一步的真實產物；階段以註解分段，斷言訊息寫明是哪
一階段斷掉，換取可診斷性。

## 涵蓋範圍

從 **DP 自助註冊**開始（AC 2 的「註冊 → 登入」是字面要求），因此也順帶驗到一條跨模組接縫：
Email 驗證通過時由 `module_provisioning_gate` 授予的 **ET 學員角色**，是否真的足以通過 ET
的存取閘。既有 DP 測試用的是 stub granter（`test_dp_user_verify.py` 的 `et_stub`），驗不到
真實 granter 的產物能不能用。
"""

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.notify.models import DpEmailLog
from app.dp.user import router as dp_auth_router
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.constants import (
    COMPLETION_COMPLETED,
    ITEM_MATERIAL,
    ITEM_QUIZ,
    QUESTION_SINGLE,
    ROLE_STUDENT,
    ROLE_TEACHER,
    SURVEY_QUESTION_SINGLE,
)
from app.et.progress.models import EtEnrollment
from app.et.roles.models import EtUserRole
from app.et.survey_fill.rules import ENTRY_FILLABLE, ENTRY_HIDDEN, ENTRY_SUBMITTED

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"
_STUDENT_EMAIL = "flow-student@edms.local"
_STUDENT_PWD = "FlowPwd2026"


@pytest.fixture(autouse=True)
def _reset_dp_limits():
    """DP 的限流器與冷卻器是 module-level 單例，會累積整個測試 session 的用量。

    本檔要真的走一次 register / verify / login，若前面的 DP 測試已把同 IP 的額度用掉，
    這裡會拿到 429 而失敗在一個與被測行為無關的地方。
    """
    dp_auth_router._register_limiter._hits.clear()
    dp_auth_router._login_limiter._hits.clear()
    dp_auth_router._verify_limiter._hits.clear()
    dp_auth_router._verify_send_cooldown._last.clear()
    yield


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _teacher(db, user_id: str) -> str:
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@edms.local",
            pwd_hash=hash_password("Abcd1234"),
            user_name=f"教師{user_id}",
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


async def _verify_token(db, email: str) -> str:
    """由 outbox 取出註冊驗證信的明文 token（DB 只存 SHA-256，測試也拿不到明文）。"""
    log = await db.scalar(
        select(DpEmailLog).where(
            DpEmailLog.recipient == email,
            DpEmailLog.template_code == "ACCOUNT_VERIFY",
            DpEmailLog.status == "PENDING",
        )
    )
    assert log is not None, "註冊未寄出驗證信——後續整條流程都走不下去"
    marker = "/verify-email?token="
    start = log.body.index(marker) + len(marker)
    end = start
    while end < len(log.body) and log.body[end] not in '\n \r"<':
        end += 1
    return log.body[start:end]


async def _published_course(client, db, teacher: str) -> dict:
    """建一門**完整**課程並發布：標籤 + 起訖時間 + 章節 + 教材 + 測驗（含題目）+ 問卷（含題目）。

    回傳後續各階段需要的所有 id 與邀請碼。
    """
    created = await client.post(
        _COURSES,
        json={
            "course_name": "感染管制年度訓練",
            "open_start_at": "2026-01-01T00:00:00Z",
            "open_end_at": "2027-12-31T00:00:00Z",
        },
        headers=_bearer(teacher),
    )
    assert created.status_code == 201, created.text
    course_id = created.json()["course_id"]

    tag = EtTag(
        tag_name=f"受訓單位{course_id}",
        is_active=True,
        is_builtin=False,
        created_user="SYSTEM",
        created_date=utcnow(),
        deleted=0,
    )
    db.add(tag)
    await db.flush()
    db.add(EtCourseTag(course_id=course_id, tag_id=tag.tag_id, created_user="SYSTEM", created_date=utcnow(), deleted=0))
    await db.flush()

    chapter = await client.post(
        f"{_COURSES}/{course_id}/chapters", json={"chapter_name": "第一章 基本概念"}, headers=_bearer(teacher)
    )
    assert chapter.status_code == 201, chapter.text
    chapter_id = chapter.json()["chapter_id"]

    material = await client.post(
        f"/api/et/chapters/{chapter_id}/items",
        json={"item_type": ITEM_MATERIAL, "title": "閱讀教材"},
        headers=_bearer(teacher),
    )
    assert material.status_code == 201, material.text
    # 教材需至少一項媒材才算完整；用說明文字（不必上傳真影片）
    await client.put(
        f"/api/et/materials/{material.json()['material_id']}",
        json={
            "material_name": "閱讀教材",
            "description_html": "<p>請詳閱本章內容。</p>",
            "doc_ids": [],
            "video_ids": [],
            "version": 0,
        },
        headers=_bearer(teacher),
    )

    quiz = await client.post(
        f"/api/et/chapters/{chapter_id}/items",
        json={"item_type": ITEM_QUIZ, "title": "章節小考"},
        headers=_bearer(teacher),
    )
    assert quiz.status_code == 201, quiz.text
    quiz_id = quiz.json()["quiz_id"]
    question = await client.post(
        f"/api/et/quizzes/{quiz_id}/questions",
        json={
            "question_type": QUESTION_SINGLE,
            "stem": "洗手的五個時機不包含下列何者？",
            "points": 100,
            "options": [
                {"option_text": "接觸病人前", "is_correct": False},
                {"option_text": "下班打卡時", "is_correct": True},
            ],
        },
        headers=_bearer(teacher),
    )
    assert question.status_code == 201, question.text

    survey = await client.post(
        f"{_COURSES}/{course_id}/survey", json={"survey_name": "課後滿意度問卷"}, headers=_bearer(teacher)
    )
    assert survey.status_code == 201, survey.text
    survey_id = survey.json()["survey_id"]
    sq = await client.post(
        f"/api/et/surveys/{survey_id}/questions",
        json={
            "question_type": SURVEY_QUESTION_SINGLE,
            "stem": "您對本課程是否滿意？",
            "options": [{"option_text": "滿意"}, {"option_text": "普通"}, {"option_text": "不滿意"}],
        },
        headers=_bearer(teacher),
    )
    assert sq.status_code == 201, sq.text

    published = await client.post(f"{_COURSES}/{course_id}/publish", headers=_bearer(teacher))
    assert published.status_code == 200, f"基準課程應可發布，實得 {published.text}"

    return {
        "course_id": course_id,
        "chapter_id": chapter_id,
        "material_item_id": material.json()["item_id"],
        "quiz_item_id": quiz.json()["item_id"],
        "quiz_id": quiz_id,
        "question_id": question.json()["question_id"],
        "correct_option_id": next(o["option_id"] for o in question.json()["options"] if o["is_correct"]),
        "survey_id": survey_id,
        "survey_question": sq.json(),
        "invitation_code": published.json()["invitation_code"],
    }


async def test_學員從註冊到填完問卷的完整流程(client, db) -> None:
    """AC 2 的完整鏈：註冊 → 驗證設密碼 → 登入 → 加入 → 學習 → 通過測驗 → 完課 → 填問卷。

    每一步都吃**前一步的真實產物**（真 token、真邀請碼、真 attempt_id、真完課狀態），
    這正是既有測試補不到的部分——它們各自造前置資料。
    """
    teacher = await _teacher(db, "t_flow01")
    course = await _published_course(client, db, teacher)

    # ── 階段 1：DP 自助註冊（方案 B：驗證前不建 DP_USER）──────────────────────
    registered = await client.post("/api/register", json={"email": _STUDENT_EMAIL, "user_name": "王小明"})
    assert registered.status_code == 202, registered.text
    assert await db.scalar(select(DpUser).where(DpUser.email == _STUDENT_EMAIL)) is None, (
        "方案 B：驗證通過前不得建立 DP_USER"
    )

    # ── 階段 2：點驗證連結、當場設定密碼（#212：密碼不由匿名註冊者提供）────────
    token = await _verify_token(db, _STUDENT_EMAIL)
    verified = await client.post(
        "/api/verify-email",
        json={"token": token, "new_password": _STUDENT_PWD, "confirm_password": _STUDENT_PWD},
    )
    assert verified.status_code == 200, verified.text
    student_row = await db.scalar(select(DpUser).where(DpUser.email == _STUDENT_EMAIL))
    assert student_row is not None and student_row.status == "ACTIVE"
    student = student_row.user_id

    # 跨模組接縫：真實的 ET granter（非 DP 測試用的 stub）是否真的授了學員角色
    role = await db.scalar(
        select(EtUserRole).where(
            EtUserRole.user_id == student, EtUserRole.role == ROLE_STUDENT, EtUserRole.deleted == 0
        )
    )
    assert role is not None and role.is_active, "驗證通過應由 module_provisioning_gate 授予 ET 學員角色"

    # ── 階段 3：以自設密碼登入 ───────────────────────────────────────────────
    logged_in = await client.post("/api/login", json={"email": _STUDENT_EMAIL, "password": _STUDENT_PWD})
    assert logged_in.status_code == 200, logged_in.text
    headers = {"Authorization": f"Bearer {logged_in.json()['access_token']}"}

    # ── 階段 4：以邀請碼加入課程（用發布時真的產出的那一組碼）──────────────────
    preview = await client.post(
        "/api/et/enrollments/preview", json={"invitation_code": course["invitation_code"]}, headers=headers
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["already_joined"] is False

    joined = await client.post(
        "/api/et/enrollments", json={"invitation_code": course["invitation_code"]}, headers=headers
    )
    assert joined.status_code == 201, joined.text

    # ── 階段 5：學習——第一項教材可讀，測驗尚未解鎖 ──────────────────────────
    structure = await client.get(f"{_COURSES}/{course['course_id']}/learn", headers=headers)
    assert structure.status_code == 200, structure.text
    items = structure.json()["chapters"][0]["items"]
    assert [i["item_id"] for i in items] == [course["material_item_id"], course["quiz_item_id"]]
    assert items[0]["locked"] is False and items[1]["locked"] is True, "序列解鎖：測驗須待教材完成"

    # 問卷入口此刻應為隱藏——完課是它的前提，而學員才剛開始
    form_before = await client.get(f"{_COURSES}/{course['course_id']}/survey/form", headers=headers)
    assert form_before.status_code == 200, form_before.text
    assert form_before.json()["state"] == ENTRY_HIDDEN, "未完課時問卷入口不該開放"

    viewed = await client.post(f"/api/et/items/{course['material_item_id']}/viewed", headers=headers)
    assert viewed.status_code == 200, viewed.text
    assert viewed.json()["completed"] is True, "無影片教材開啟即完成"

    # ── 階段 6：作答並通過測驗 ───────────────────────────────────────────────
    attempt = await client.post(f"/api/et/quizzes/{course['quiz_id']}/attempts", headers=headers)
    assert attempt.status_code == 201, f"教材已完成，測驗應已解鎖，實得 {attempt.text}"
    attempt_id = attempt.json()["attempt_id"]

    saved = await client.put(
        f"/api/et/attempts/{attempt_id}/answers/{course['question_id']}",
        json={"selected_options": [course["correct_option_id"]]},
        headers=headers,
    )
    assert saved.status_code == 204, saved.text

    result = await client.post(f"/api/et/attempts/{attempt_id}/submit", headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["is_pass"] is True, f"全對應及格，實得 {result.json()}"

    # ── 階段 7：完課由「真的學完」推導 ───────────────────────────────────────
    #
    # ⚠️ **不可斷言 `EtEnrollment.COMPLETION_STATUS`**——那是死欄位：只在加入課程時寫入
    # `NOT_STARTED`，全 codebase 沒有任何路徑推進它（`COMPLETED_AT` 更是全無寫入點，
    # 見 `tracking/schemas.py::StudentRow` 的說明）。完課一律由完成項目數**即時導出**。
    #
    # 下面那條反向斷言是刻意的：它把「這個欄位是死的」釘成測試。哪天有人補上寫入路徑，
    # 它會紅，而那正是該重新確認「即時導出仍是單一事實來源」的時點——兩個來源並存而
    # 不一致，畫面上看不出資料是死的（ET04 於 #284 踩過同一個坑）。
    enrolled_row = await db.scalar(
        select(EtEnrollment).where(
            EtEnrollment.course_id == course["course_id"], EtEnrollment.user_id == student, EtEnrollment.deleted == 0
        )
    )
    assert enrolled_row is not None and enrolled_row.completion_status != COMPLETION_COMPLETED, (
        "COMPLETION_STATUS 應仍是加入時寫入的值——若它變了，代表有人補上了寫入路徑，"
        "此時 tracking / my-courses 的即時導出是否仍為單一事實來源需重新確認"
    )

    my_courses = await client.get("/api/et/my-courses", headers=headers)
    assert my_courses.status_code == 200, my_courses.text
    body = my_courses.json()
    mine = [c for c in body["courses"] if c["course_id"] == course["course_id"]]
    assert len(mine) == 1 and mine[0]["completion_status"] == COMPLETION_COMPLETED, (
        f"學完全部項目後「我的課程」應顯示完課——這條因果既有測試從未驗過，實得 {mine}"
    )
    assert mine[0]["progress_pct"] == 100
    # 統計卡與清單來自同一次查詢，兩者必須一致（schema docstring 明訂）
    assert body["summary"]["completed"] == 1 and body["summary"]["in_progress"] == 0, (
        f"上方統計與卡片不一致，實得 {body['summary']}"
    )

    # ── 階段 8：完課後問卷入口開啟並填完 ─────────────────────────────────────
    form = await client.get(f"{_COURSES}/{course['course_id']}/survey/form", headers=headers)
    assert form.status_code == 200, form.text
    assert form.json()["state"] == ENTRY_FILLABLE, f"完課後問卷應可填，實得 {form.json()['state']}"

    submitted = await client.post(
        f"{_COURSES}/{course['course_id']}/survey/response",
        json={
            "answers": [
                {
                    "sq_id": course["survey_question"]["sq_id"],
                    "so_id": course["survey_question"]["options"][0]["so_id"],
                }
            ]
        },
        headers=headers,
    )
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["submitted_at"] is not None

    after = await client.get(f"{_COURSES}/{course['course_id']}/survey/form", headers=headers)
    assert after.json()["state"] == ENTRY_SUBMITTED

    # ── 階段 9：教師端看得到這位學員的成果（跨到 ET03 追蹤）────────────────────
    students = await client.get(f"{_COURSES}/{course['course_id']}/students", headers=_bearer(teacher))
    assert students.status_code == 200, students.text
    rows = [r for r in students.json()["data"] if r["user_id"] == student]
    assert len(rows) == 1, "教師端追蹤清單應看得到這位學員"
    assert rows[0]["completion_status"] == COMPLETION_COMPLETED
    assert rows[0]["last_activity_at"] is not None, "作答與問卷都送出過，最後活動時間不該是空的"
