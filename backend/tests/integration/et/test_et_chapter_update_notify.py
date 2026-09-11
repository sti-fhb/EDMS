"""已發布課程新增章節之通知信（ET-13 / US3 補強 / #303）。

驗 `spec_us3` 場景 29 / FR-ET-US3-14：教師於已發布課程新增章節 → 自動寄信通知所有已加入
學員（**含已完課者**）；已完課者之完課狀態回到「進行中」；已填問卷不因此失效。

## 為何整檔都是 integration

收件人來自 `ET_ENROLLMENT` × `DP_USER` 的 join、信件落在 `DP_EMAIL_LOG`、完課狀態由
`ET_PROGRESS` 的計數導出——每一條斷言都需要真 DB。params 的 key 組法那一半（唯一不需
DB 的部分）已在 `tests/unit/et/test_et_course_update_mail.py` 涵蓋，此處不重複。

⚠️ **斷言必須篩 `STATUS='PENDING'`**：params 的 key 與範本佔位對不上時，平台
`_SafeFormatter` 會拋 `KeyError` → 該筆寫成 `STATUS='FAILED'`、`queued_count=0`
**且不外拋**。只查「有沒有列」會讓「寄出空信」這種失敗看起來像成功。
"""

import pytest
from sqlalchemy import select, update

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.notify.models import DpEmailLog
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.constants import (
    ITEM_MATERIAL,
    ROLE_STUDENT,
    ROLE_TEACHER,
    SOURCE_INVITATION_CODE,
)
from app.et.course.models import EtCourse
from app.et.notify.course_update import TEMPLATE_COURSE_UPDATE
from app.et.progress.models import EtEnrollment, EtProgress
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str, role: str, *, email: str | None = None) -> str:
    """建使用者並賦予單一 ET 角色。

    ⚠️ `EMAIL` 全小寫——`DP_USER.EMAIL` 以小寫儲存，大寫會讓收件人比對落空。
    `email=""` 用於驗「查無 Email 者略過」。
    """
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@edms.local" if email is None else email,
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
    now = utcnow()
    tag_id = await db.scalar(select(EtTag.tag_id).where(EtTag.tag_name == name, EtTag.deleted == 0))
    if tag_id is None:
        tag = EtTag(tag_name=name, is_active=True, is_builtin=False, created_user="SYSTEM", created_date=now, deleted=0)
        db.add(tag)
        await db.flush()
        tag_id = tag.tag_id
    return tag_id


async def _course(client, db, slug: str, *, publish: bool = True) -> dict:
    """一門課程（1 章節 + 1 教材 + 1 標籤 + 起訖），依 `publish` 決定是否發布。

    ⚠️ 標籤刻意用課程專屬名稱、**不用「全體」**：後者會在發布時觸發標籤自動邀請，把
    全站學員角色者都加進課程並各寄一封 `COURSE_INVITE`。本檔要數的是 `COURSE_UPDATE`
    的封數，混進別的收件人會讓斷言相依於 DB 裡有多少學員。
    """
    teacher = await _user(db, f"t_{slug}", ROLE_TEACHER)
    created = await client.post(
        _COURSES,
        json={
            "course_name": "採血作業訓練",
            "open_start_at": "2026-09-01T00:00:00Z",
            "open_end_at": "2027-09-30T00:00:00Z",
        },
        headers=_bearer(teacher),
    )
    assert created.status_code == 201, created.text
    cid = created.json()["course_id"]

    db.add(
        EtCourseTag(
            course_id=cid, tag_id=await _tag(db, f"標籤{cid}"), created_user="SYSTEM", created_date=utcnow(), deleted=0
        )
    )
    await db.flush()

    ch = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(teacher))
    assert ch.status_code == 201, ch.text
    item = await client.post(
        f"/api/et/chapters/{ch.json()['chapter_id']}/items",
        json={"item_type": ITEM_MATERIAL, "title": "教材"},
        headers=_bearer(teacher),
    )
    assert item.status_code == 201, item.text

    if publish:
        published = await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(teacher))
        assert published.status_code == 200, published.text

    return {"teacher": teacher, "course_id": cid, "item_id": item.json()["item_id"]}


async def _enroll(db, user_id: str, course_id: int, *, removed: bool = False) -> None:
    now = utcnow()
    db.add(
        EtEnrollment(
            user_id=user_id,
            course_id=course_id,
            join_source=SOURCE_INVITATION_CODE,
            joined_at=now,
            completion_status="NOT_STARTED",
            is_removed=removed,
            removed_at=now if removed else None,
            created_user=user_id,
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()


async def _complete(db, user_id: str, course_id: int, item_id: int) -> None:
    """直接寫 `ET_PROGRESS` 讓學員完課（走端點亦可，但此處只需要「已完課」這個前提）。"""
    db.add(
        EtProgress(
            user_id=user_id,
            course_id=course_id,
            item_id=item_id,
            is_completed=True,
            created_user=user_id,
            created_date=utcnow(),
            deleted=0,
        )
    )
    await db.flush()


async def _update_mails(db) -> list[DpEmailLog]:
    """渲染成功並排入 outbox 的 `COURSE_UPDATE`（`FAILED` 代表 params 對不上佔位）。"""
    rows = await db.execute(
        select(DpEmailLog).where(
            DpEmailLog.template_code == TEMPLATE_COURSE_UPDATE,
            DpEmailLog.module == "ET",
            DpEmailLog.status == "PENDING",
        )
    )
    return list(rows.scalars().all())


async def _add_chapter(client, ctx: dict, name: str):
    return await client.post(
        f"{_COURSES}/{ctx['course_id']}/chapters", json={"chapter_name": name}, headers=_bearer(ctx["teacher"])
    )


class TestNotifyOnChapterAdded:
    async def test_寄給所有在籍學員(self, client, db) -> None:
        """AC 1：每位在籍學員各一封（逐人一封才能個人化 `{{USER_NAME}}`）。"""
        ctx = await _course(client, db, "cu01")
        for i in range(3):
            await _enroll(db, await _user(db, f"s_cu01_{i}", ROLE_STUDENT), ctx["course_id"])

        r = await _add_chapter(client, ctx, "第二章")

        assert r.status_code == 201, r.text
        mails = await _update_mails(db)
        assert len(mails) == 3
        assert {m.recipient for m in mails} == {f"s_cu01_{i}@edms.local" for i in range(3)}

    async def test_信件內容帶新章節名稱與課程名稱(self, client, db) -> None:
        """params 對不上佔位時會渲染成空信且記 `FAILED`，故要驗**內文**而非只驗有列。"""
        ctx = await _course(client, db, "cu02")
        await _enroll(db, await _user(db, "s_cu02", ROLE_STUDENT), ctx["course_id"])

        await _add_chapter(client, ctx, "第二章 異常處理")

        mails = await _update_mails(db)
        assert len(mails) == 1
        body = mails[0].body or ""
        assert "第二章 異常處理" in body
        assert "採血作業訓練" in body
        assert "測試s_cu02" in body, "個人化稱謂——逐人一封的理由"

    async def test_草稿課程新增章節不寄信(self, client, db) -> None:
        """AC 2：草稿沒有學員也不對學員可見，寄信沒有對象。"""
        ctx = await _course(client, db, "cu03", publish=False)
        # 草稿理論上不會有 enrollment；刻意塞一筆，驗「判定看課程狀態、不看有沒有人」
        await _enroll(db, await _user(db, "s_cu03", ROLE_STUDENT), ctx["course_id"])

        r = await _add_chapter(client, ctx, "第二章")

        assert r.status_code == 201, r.text
        assert await _update_mails(db) == []

    async def test_已移除學員不寄(self, client, db) -> None:
        """AC 1：`IS_REMOVED` 者已被教師移出課程，不該再收到課程更新。"""
        ctx = await _course(client, db, "cu04")
        await _enroll(db, await _user(db, "s_cu04_in", ROLE_STUDENT), ctx["course_id"])
        await _enroll(db, await _user(db, "s_cu04_out", ROLE_STUDENT), ctx["course_id"], removed=True)

        await _add_chapter(client, ctx, "第二章")

        mails = await _update_mails(db)
        assert [m.recipient for m in mails] == ["s_cu04_in@edms.local"]

    async def test_已完課學員也要收到(self, client, db) -> None:
        """`spec_us3` 場景 29 明寫「**包含已完課學員**」——他們正是最需要知道有新內容的人。"""
        ctx = await _course(client, db, "cu05")
        student = await _user(db, "s_cu05", ROLE_STUDENT)
        await _enroll(db, student, ctx["course_id"])
        await _complete(db, student, ctx["course_id"], ctx["item_id"])

        await _add_chapter(client, ctx, "第二章")

        assert [m.recipient for m in await _update_mails(db)] == ["s_cu05@edms.local"]

    async def test_查無Email者略過但其他人照寄(self, client, db) -> None:
        """比照 `EtNotifyRepository.recipients` 的既有行為：沒有 Email 就寄不了，
        但不能因為一個人沒有 Email 就讓整批都不寄。
        """
        ctx = await _course(client, db, "cu06")
        await _enroll(db, await _user(db, "s_cu06_ok", ROLE_STUDENT), ctx["course_id"])
        await _enroll(db, await _user(db, "s_cu06_no", ROLE_STUDENT, email=""), ctx["course_id"])

        await _add_chapter(client, ctx, "第二章")

        assert [m.recipient for m in await _update_mails(db)] == ["s_cu06_ok@edms.local"]

    async def test_每次新增各寄一封(self, client, db) -> None:
        """contracts 明寫「每次新增即寄」且 `{{NEW_CHAPTER_NAME}}` 為單數。

        ET02 的「儲存並繼續新增」會連續呼叫本端點，故 2 章節 × 1 學員 = 2 封。
        通知量放大的風險已記於 #303 規劃 §12。
        """
        ctx = await _course(client, db, "cu07")
        await _enroll(db, await _user(db, "s_cu07", ROLE_STUDENT), ctx["course_id"])

        await _add_chapter(client, ctx, "第二章")
        await _add_chapter(client, ctx, "第三章")

        mails = await _update_mails(db)
        assert len(mails) == 2
        # 兩封各自帶自己那一章的名稱——不是同一封寄兩次
        assert sorted("第二章" if "第二章" in (m.body or "") else "第三章" for m in mails) == ["第三章", "第二章"]

    async def test_寄信失敗章節仍建立(self, client, db) -> None:
        """AC：寄送失敗 MUST NOT 影響章節本身。

        以「停用範本」製造失敗——平台會回 `skipped_reason=TEMPLATE_DISABLED`、
        `queued_count=0`，且不拋例外（`EtNotifier` 於唯一出口吞掉 `AppError`）。
        這比 mock 更接近真實故障：管理者停用一支範本就會走到這條路徑。
        """
        from app.dp.notify.models import DpNotifyTemplate

        ctx = await _course(client, db, "cu08")
        await _enroll(db, await _user(db, "s_cu08", ROLE_STUDENT), ctx["course_id"])
        await db.execute(
            update(DpNotifyTemplate)
            .where(DpNotifyTemplate.template_code == TEMPLATE_COURSE_UPDATE, DpNotifyTemplate.module == "ET")
            .values(is_enabled=False)
        )
        await db.flush()

        r = await _add_chapter(client, ctx, "第二章")

        assert r.status_code == 201, r.text
        assert r.json()["chapter_name"] == "第二章"
        assert await _update_mails(db) == []
        chapters = await db.scalars(
            select(EtCourse).where(EtCourse.course_id == ctx["course_id"], EtCourse.deleted == 0)
        )
        assert chapters.first() is not None, "課程與章節皆未因寄信失敗而回滾"


class TestCompletionStatusRollback:
    """AC 3：章節更新後，已完課學員之完課狀態回到「進行中」。

    ⚠️ **#303 SA Q1 裁示 A：不寫 `ET_ENROLLMENT.COMPLETION_STATUS` 欄位。**

    該欄位在現行程式碼中**只被寫一次**（加入課程時的 `NOT_STARTED`）且**從未被讀**
    ——所有讀取端自 #284 起一律用 `derive_completion_status(done, total)` 即時導出。
    因此 `UPDATE ... WHERE completion_status='COMPLETED'` 會永遠匹配零列。

    故本類驗的是**可觀察行為**（API 回的完課狀態）而非一個空的 UPDATE：新增章節使項目
    總數變大，`done < total`，狀態自動從已完成回到進行中。
    """

    async def test_新增章節後完課狀態由已完成變回進行中(self, client, db) -> None:
        ctx = await _course(client, db, "cs01")
        student = await _user(db, "s_cs01", ROLE_STUDENT)
        await _enroll(db, student, ctx["course_id"])
        await _complete(db, student, ctx["course_id"], ctx["item_id"])

        before = await client.get("/api/et/my-courses", headers=_bearer(student))
        assert before.json()["courses"][0]["completion_status"] == "COMPLETED"

        # 新增章節本身不夠——完課率的分母是**項目**數，故新章節要掛一個項目
        ch = await _add_chapter(client, ctx, "第二章")
        added = await client.post(
            f"/api/et/chapters/{ch.json()['chapter_id']}/items",
            json={"item_type": ITEM_MATERIAL, "title": "新教材"},
            headers=_bearer(ctx["teacher"]),
        )
        assert added.status_code == 201, added.text

        after = await client.get("/api/et/my-courses", headers=_bearer(student))
        assert after.json()["courses"][0]["completion_status"] == "IN_PROGRESS"

    async def test_進度紀錄不因章節更新而被清除(self, client, db) -> None:
        """回退只是分母變大，**不是把已學的東西歸零**。"""
        ctx = await _course(client, db, "cs02")
        student = await _user(db, "s_cs02", ROLE_STUDENT)
        await _enroll(db, student, ctx["course_id"])
        await _complete(db, student, ctx["course_id"], ctx["item_id"])

        await _add_chapter(client, ctx, "第二章")

        rows = (
            await db.scalars(
                select(EtProgress).where(EtProgress.user_id == student, EtProgress.course_id == ctx["course_id"])
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].is_completed is True

    async def test_已填問卷不因章節更新而失效或需重填(self, client, db) -> None:
        """AC 4 / `spec_us3` 場景 29 明寫「學員已填之課後問卷**不因回退而失效或重填**」。

        這條之所以要測：完課狀態回退後，學員的問卷入口理論上可能被重新判成「可填寫」
        ——那會讓他被要求再填一次同一份問卷，而 `ET_SURVEY_RESPONSE_M` 的唯一約束會讓
        第二次送出撞 409。`derive_entry_state` 的判定順序是「**已填優先於完課與課程狀態**」
        （#284），所以入口維持 `SUBMITTED`；本測試釘住那個順序不被後續改動破壞。
        """
        ctx = await _course(client, db, "cs03")
        student = await _user(db, "s_cs03", ROLE_STUDENT)
        await _enroll(db, student, ctx["course_id"])
        await _complete(db, student, ctx["course_id"], ctx["item_id"])

        survey = await client.post(
            f"{_COURSES}/{ctx['course_id']}/survey", json={"survey_name": "課後問卷"}, headers=_bearer(ctx["teacher"])
        )
        assert survey.status_code == 201, survey.text
        question = await client.post(
            f"/api/et/surveys/{survey.json()['survey_id']}/questions",
            # 單選題至少 2 個選項（`ET_SURVEY_004`）
            json={
                "question_type": "SINGLE",
                "stem": "滿意嗎？",
                "options": [{"option_text": "滿意"}, {"option_text": "普通"}],
            },
            headers=_bearer(ctx["teacher"]),
        )
        assert question.status_code == 201, question.text
        form = await client.get(f"{_COURSES}/{ctx['course_id']}/survey/form", headers=_bearer(student))
        submitted = await client.post(
            f"{_COURSES}/{ctx['course_id']}/survey/response",
            json={
                "answers": [
                    {
                        "sq_id": form.json()["questions"][0]["sq_id"],
                        "so_id": form.json()["questions"][0]["options"][0]["so_id"],
                    }
                ]
            },
            headers=_bearer(student),
        )
        assert submitted.status_code == 201, submitted.text

        # 新增帶項目的章節 → 完課狀態回退為進行中
        ch = await _add_chapter(client, ctx, "第二章")
        added = await client.post(
            f"/api/et/chapters/{ch.json()['chapter_id']}/items",
            json={"item_type": ITEM_MATERIAL, "title": "新教材"},
            headers=_bearer(ctx["teacher"]),
        )
        assert added.status_code == 201, added.text

        mine = await client.get("/api/et/my-courses", headers=_bearer(student))
        assert mine.json()["courses"][0]["completion_status"] == "IN_PROGRESS", "前提：確實已回退"

        after = await client.get(f"{_COURSES}/{ctx['course_id']}/survey/form", headers=_bearer(student))
        assert after.status_code == 200, after.text
        assert after.json()["state"] == "SUBMITTED", "已填者維持唯讀回看，不得被要求重填"
        assert len(after.json()["my_answers"]) == 1, "填答內容保留"
