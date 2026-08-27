"""ET02 章節項目整合測試（US3 / #203）。

重點在需要真 DB 才驗得了的四件事：

1. 新增項目時**同交易**建立教材 / 測驗空殼（拆兩次請求會留孤兒項目）
2. `SORT_ORDER` 的追加、重排（兩階段寫入）與刪除後遞補
3. 刪除項目時**教材 / 測驗內容與學員紀錄之連帶軟刪除**——須先建學員測資才驗得出
4. 樂觀鎖粒度：項目重排帶**章節層** version，不動項目自身 version
"""

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.constants import ATTEMPT_IN_PROGRESS, ITEM_MATERIAL, ITEM_QUIZ, ROLE_TEACHER
from app.et.course.models import EtChapter, EtItem
from app.et.material.models import EtMaterial, EtMaterialDoc, EtMaterialVideo
from app.et.progress.models import EtProgress, EtProgressInterval, EtProgressVideo
from app.et.quiz.models import EtOption, EtQuestion, EtQuiz, EtQuizAttemptD, EtQuizAttemptM
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"


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


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _chapter(client, uid: str) -> tuple[int, int]:
    """建課程 + 一個章節，回 `(course_id, chapter_id)`。"""
    created = await client.post(_COURSES, json={"course_name": "課程"}, headers=_bearer(uid))
    cid = created.json()["course_id"]
    r = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(uid))
    return cid, r.json()["chapter_id"]


async def _add_item(client, uid: str, chapter_id: int, item_type: str, title: str) -> dict:
    r = await client.post(
        f"/api/et/chapters/{chapter_id}/items",
        json={"item_type": item_type, "title": title},
        headers=_bearer(uid),
    )
    assert r.status_code == 201, r.text
    return r.json()


class TestAddItem:
    async def test_新增教材項目同時建立教材空殼(self, client, db) -> None:
        """同一交易建立——否則中途失敗會留下指不到內容的項目（CHECK 也不允許）。"""
        uid = await _user(db, "ETI_A1")
        _, chapter_id = await _chapter(client, uid)
        body = await _add_item(client, uid, chapter_id, ITEM_MATERIAL, "教材一")

        assert body["item_type"] == ITEM_MATERIAL
        assert body["material_id"] is not None
        assert body["quiz_id"] is None
        material = await db.scalar(select(EtMaterial).where(EtMaterial.material_id == body["material_id"]))
        assert material is not None
        assert material.material_name == "教材一"

    async def test_新增測驗項目同時建立測驗空殼並帶預設值(self, client, db) -> None:
        uid = await _user(db, "ETI_A2")
        _, chapter_id = await _chapter(client, uid)
        body = await _add_item(client, uid, chapter_id, ITEM_QUIZ, "小考")

        assert body["quiz_id"] is not None and body["material_id"] is None
        quiz = await db.scalar(select(EtQuiz).where(EtQuiz.quiz_id == body["quiz_id"]))
        assert (quiz.quiz_name, quiz.pass_score, quiz.max_retry) == ("小考", 80, 3)
        assert quiz.time_limit_min is None, "作答時間限制預設空白＝不限時"
        assert quiz.description is None, "測驗說明為選填（SA 裁示 #203 Q1）"

    async def test_追加至最末且順序自_1_起(self, client, db) -> None:
        uid = await _user(db, "ETI_A3")
        _, chapter_id = await _chapter(client, uid)
        for i, t in enumerate(["教材", "測驗", "教材2"]):
            kind = ITEM_QUIZ if i == 1 else ITEM_MATERIAL
            await _add_item(client, uid, chapter_id, kind, t)
        rows = await db.scalars(select(EtItem).where(EtItem.chapter_id == chapter_id).order_by(EtItem.sort_order))
        assert [i.sort_order for i in rows] == [1, 2, 3]

    async def test_名稱可留空由使用者於視窗內填寫(self, client, db) -> None:
        """不代填「新教材」——使用者開了視窗第一件事就是把預設值選起來刪掉。

        空名稱只是「還沒填」的過渡狀態；**儲存時仍必填**（見
        `test_名稱全空白時無法儲存`）。
        """
        uid = await _user(db, "ETI_A4")
        _, chapter_id = await _chapter(client, uid)
        r = await client.post(
            f"/api/et/chapters/{chapter_id}/items",
            json={"item_type": ITEM_MATERIAL, "title": "   "},
            headers=_bearer(uid),
        )
        assert r.status_code == 201, r.text
        assert r.json()["title"] == ""

    async def test_未帶名稱亦可建立(self, client, db) -> None:
        uid = await _user(db, "ETI_A4B")
        _, chapter_id = await _chapter(client, uid)
        r = await client.post(
            f"/api/et/chapters/{chapter_id}/items",
            json={"item_type": ITEM_MATERIAL},
            headers=_bearer(uid),
        )
        assert r.status_code == 201, r.text

    async def test_名稱全空白時無法儲存(self, client, db) -> None:
        """建立可空、儲存必填——空名稱不是可以存檔的樣子。"""
        uid = await _user(db, "ETI_A4C")
        _, chapter_id = await _chapter(client, uid)
        item = await _add_item(client, uid, chapter_id, ITEM_MATERIAL, "")
        r = await client.put(
            f"/api/et/materials/{item['material_id']}",
            json={
                "material_name": "  ",
                "description_html": "<p>說明</p>",
                "doc_ids": [],
                "video_ids": [],
                "version": 0,
            },
            headers=_bearer(uid),
        )
        assert r.status_code == 422

    async def test_未知項目類型被擋(self, client, db) -> None:
        uid = await _user(db, "ETI_A5")
        _, chapter_id = await _chapter(client, uid)
        r = await client.post(
            f"/api/et/chapters/{chapter_id}/items",
            json={"item_type": "SURVEY", "title": "問卷"},
            headers=_bearer(uid),
        )
        assert r.status_code == 422

    async def test_非擁有者不可新增(self, client, db) -> None:
        owner = await _user(db, "ETI_A6")
        other = await _user(db, "ETI_A7")
        _, chapter_id = await _chapter(client, owner)
        r = await client.post(
            f"/api/et/chapters/{chapter_id}/items",
            json={"item_type": ITEM_MATERIAL, "title": "教材"},
            headers=_bearer(other),
        )
        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_COURSE_002"

    async def test_課程詳細帶出項目且依順序(self, client, db) -> None:
        uid = await _user(db, "ETI_A8")
        cid, chapter_id = await _chapter(client, uid)
        await _add_item(client, uid, chapter_id, ITEM_MATERIAL, "教材甲")
        await _add_item(client, uid, chapter_id, ITEM_QUIZ, "測驗乙")

        detail = await client.get(f"{_COURSES}/{cid}", headers=_bearer(uid))
        items = detail.json()["chapters"][0]["items"]
        assert [i["title"] for i in items] == ["教材甲", "測驗乙"]
        assert [i["item_type"] for i in items] == [ITEM_MATERIAL, ITEM_QUIZ]


class TestReorderItems:
    async def test_重排交換相鄰兩項(self, client, db) -> None:
        """交換相鄰兩項會在中途撞唯一索引——驗兩階段寫入確實生效。"""
        uid = await _user(db, "ETI_R1")
        _, chapter_id = await _chapter(client, uid)
        a = await _add_item(client, uid, chapter_id, ITEM_MATERIAL, "A")
        b = await _add_item(client, uid, chapter_id, ITEM_MATERIAL, "B")
        chapter = await db.scalar(select(EtChapter).where(EtChapter.chapter_id == chapter_id))

        r = await client.put(
            f"/api/et/chapters/{chapter_id}/items/order",
            json={"item_ids": [b["item_id"], a["item_id"]], "version": chapter.version},
            headers=_bearer(uid),
        )
        assert r.status_code == 204, r.text
        rows = await db.scalars(select(EtItem).where(EtItem.chapter_id == chapter_id).order_by(EtItem.sort_order))
        assert [i.item_id for i in rows] == [b["item_id"], a["item_id"]]

    async def test_重排不遞增項目自身版本(self, client, db) -> None:
        """順序屬章節結構；遞增項目版本會讓正在編輯該教材的另一裝置無故衝突。"""
        uid = await _user(db, "ETI_R2")
        _, chapter_id = await _chapter(client, uid)
        a = await _add_item(client, uid, chapter_id, ITEM_MATERIAL, "A")
        b = await _add_item(client, uid, chapter_id, ITEM_MATERIAL, "B")
        chapter = await db.scalar(select(EtChapter).where(EtChapter.chapter_id == chapter_id))

        await client.put(
            f"/api/et/chapters/{chapter_id}/items/order",
            json={"item_ids": [b["item_id"], a["item_id"]], "version": chapter.version},
            headers=_bearer(uid),
        )
        await db.refresh(chapter)
        rows = await db.scalars(select(EtItem).where(EtItem.chapter_id == chapter_id))
        assert all(i.version == 0 for i in rows), "項目版本不應被重排改動"
        assert chapter.version == 1, "章節版本應遞增（重排以章節層版本保護）"

    async def test_版本不符回_409(self, client, db) -> None:
        uid = await _user(db, "ETI_R3")
        _, chapter_id = await _chapter(client, uid)
        a = await _add_item(client, uid, chapter_id, ITEM_MATERIAL, "A")
        r = await client.put(
            f"/api/et/chapters/{chapter_id}/items/order",
            json={"item_ids": [a["item_id"]], "version": 99},
            headers=_bearer(uid),
        )
        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_LOCK_001"

    async def test_清單缺漏被擋(self, client, db) -> None:
        uid = await _user(db, "ETI_R4")
        _, chapter_id = await _chapter(client, uid)
        a = await _add_item(client, uid, chapter_id, ITEM_MATERIAL, "A")
        await _add_item(client, uid, chapter_id, ITEM_MATERIAL, "B")
        chapter = await db.scalar(select(EtChapter).where(EtChapter.chapter_id == chapter_id))

        r = await client.put(
            f"/api/et/chapters/{chapter_id}/items/order",
            json={"item_ids": [a["item_id"]], "version": chapter.version},
            headers=_bearer(uid),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_ITEM_002"

    async def test_夾帶他人章節之項目被擋(self, client, db) -> None:
        """防越權：把別的章節的項目 id 塞進重排清單。"""
        uid = await _user(db, "ETI_R5")
        cid, chapter_a = await _chapter(client, uid)
        other = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第二章"}, headers=_bearer(uid))
        chapter_b = other.json()["chapter_id"]
        a = await _add_item(client, uid, chapter_a, ITEM_MATERIAL, "A")
        b = await _add_item(client, uid, chapter_b, ITEM_MATERIAL, "B")
        chapter = await db.scalar(select(EtChapter).where(EtChapter.chapter_id == chapter_a))

        r = await client.put(
            f"/api/et/chapters/{chapter_a}/items/order",
            json={"item_ids": [a["item_id"], b["item_id"]], "version": chapter.version},
            headers=_bearer(uid),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_ITEM_002"


class TestDeleteItem:
    async def test_刪除後剩餘項目順序遞補(self, client, db) -> None:
        """部分唯一索引若未排除軟刪除列，遞補會撞鍵——此測試釘住該 migration。"""
        uid = await _user(db, "ETI_D1")
        _, chapter_id = await _chapter(client, uid)
        ids = [(await _add_item(client, uid, chapter_id, ITEM_MATERIAL, n))["item_id"] for n in "ABC"]

        r = await client.delete(f"/api/et/items/{ids[0]}", headers=_bearer(uid))
        assert r.status_code == 204, r.text
        rows = await db.scalars(
            select(EtItem).where(EtItem.chapter_id == chapter_id, EtItem.deleted == 0).order_by(EtItem.sort_order)
        )
        remaining = list(rows)
        assert [i.item_id for i in remaining] == ids[1:]
        assert [i.sort_order for i in remaining] == [1, 2]

    async def test_刪除教材項目連帶軟刪教材與學員觀看紀錄(self, client, db) -> None:
        """先建學員測資再刪——沒有測資的話「連帶處理」等於沒被驗到。"""
        uid = await _user(db, "ETI_D2")
        _, chapter_id = await _chapter(client, uid)
        item = await _add_item(client, uid, chapter_id, ITEM_MATERIAL, "教材")
        now = utcnow()
        audit = {"created_user": uid, "created_date": now, "deleted": 0}

        video = EtMaterialVideo(
            material_id=item["material_id"],
            file_path="/x/a.mp4",
            file_name="a.mp4",
            duration_sec=180,
            file_size_bytes=1024,
            sort_order=1,
            **audit,
        )
        db.add(video)
        db.add(EtMaterialDoc(material_id=item["material_id"], doc_id="DM-TRAINING-000007", sort_order=1, **audit))
        await db.flush()
        db.add(EtProgressVideo(user_id="STU01", video_id=video.video_id, coverage_pct=50, **audit))
        db.add(EtProgressInterval(user_id="STU01", video_id=video.video_id, start_sec=0, end_sec=90, **audit))
        await db.flush()

        r = await client.delete(f"/api/et/items/{item['item_id']}", headers=_bearer(uid))
        assert r.status_code == 204, r.text

        material = await db.scalar(select(EtMaterial).where(EtMaterial.material_id == item["material_id"]))
        assert material.deleted == 1, "教材本體應軟刪"
        for model, col, val in (
            (EtMaterialVideo, EtMaterialVideo.video_id, video.video_id),
            (EtProgressVideo, EtProgressVideo.video_id, video.video_id),
            (EtProgressInterval, EtProgressInterval.video_id, video.video_id),
        ):
            rows = list(await db.scalars(select(model).where(col == val)))
            assert rows and all(r.deleted == 1 for r in rows), f"{model.__name__} 應連帶軟刪"
        docs = list(await db.scalars(select(EtMaterialDoc).where(EtMaterialDoc.material_id == item["material_id"])))
        assert docs and all(d.deleted == 1 for d in docs)

    async def test_刪除測驗項目連帶軟刪題目選項與作答紀錄(self, client, db) -> None:
        uid = await _user(db, "ETI_D3")
        cid, chapter_id = await _chapter(client, uid)
        item = await _add_item(client, uid, chapter_id, ITEM_QUIZ, "測驗")
        now = utcnow()
        audit = {"created_user": uid, "created_date": now, "deleted": 0}

        question = EtQuestion(
            quiz_id=item["quiz_id"], question_type="SINGLE", stem="題幹", points=100, sort_order=1, version=0, **audit
        )
        db.add(question)
        attempt = EtQuizAttemptM(
            user_id="STU01",
            course_id=cid,
            quiz_id=item["quiz_id"],
            attempt_no=1,
            status=ATTEMPT_IN_PROGRESS,
            question_order="[]",
            option_order="[]",
            pass_score_snapshot=80,
            started_at=now,
            **audit,
        )
        db.add(attempt)
        await db.flush()
        db.add(EtOption(question_id=question.question_id, option_text="選項", is_correct=True, sort_order=1, **audit))
        db.add(
            EtQuizAttemptD(
                attempt_id=attempt.attempt_id,
                question_id=question.question_id,
                stem_snapshot="題幹",
                points_snapshot=100,
                type_snapshot="SINGLE",
                options_snapshot="[]",
                **audit,
            )
        )
        await db.flush()

        r = await client.delete(f"/api/et/items/{item['item_id']}", headers=_bearer(uid))
        assert r.status_code == 204, r.text

        quiz = await db.scalar(select(EtQuiz).where(EtQuiz.quiz_id == item["quiz_id"]))
        assert quiz.deleted == 1
        for model, col, val in (
            (EtQuestion, EtQuestion.question_id, question.question_id),
            (EtOption, EtOption.question_id, question.question_id),
            (EtQuizAttemptM, EtQuizAttemptM.attempt_id, attempt.attempt_id),
            (EtQuizAttemptD, EtQuizAttemptD.attempt_id, attempt.attempt_id),
        ):
            rows = list(await db.scalars(select(model).where(col == val)))
            assert rows and all(r.deleted == 1 for r in rows), f"{model.__name__} 應連帶軟刪"

    async def test_刪除項目連帶軟刪學員完成進度(self, client, db) -> None:
        uid = await _user(db, "ETI_D4")
        cid, chapter_id = await _chapter(client, uid)
        item = await _add_item(client, uid, chapter_id, ITEM_MATERIAL, "教材")
        now = utcnow()
        db.add(
            EtProgress(
                user_id="STU01",
                course_id=cid,
                item_id=item["item_id"],
                is_completed=True,
                created_user=uid,
                created_date=now,
                deleted=0,
            )
        )
        await db.flush()

        await client.delete(f"/api/et/items/{item['item_id']}", headers=_bearer(uid))
        rows = list(await db.scalars(select(EtProgress).where(EtProgress.item_id == item["item_id"])))
        assert rows and all(p.deleted == 1 for p in rows), "學員紀錄應軟刪而非硬刪（#202 裁示）"

    async def test_刪除章節連帶刪其下項目之教材內容(self, client, db) -> None:
        """「刪章節」與「逐一刪項目」的結果須一致，否則兩條路徑殘留不同資料。"""
        uid = await _user(db, "ETI_D5")
        _, chapter_id = await _chapter(client, uid)
        item = await _add_item(client, uid, chapter_id, ITEM_MATERIAL, "教材")

        r = await client.delete(f"/api/et/chapters/{chapter_id}", headers=_bearer(uid))
        assert r.status_code == 204, r.text
        material = await db.scalar(select(EtMaterial).where(EtMaterial.material_id == item["material_id"]))
        assert material.deleted == 1, "刪章節時教材本體亦應軟刪，不可留成孤兒"

    async def test_查無項目回_404(self, client, db) -> None:
        uid = await _user(db, "ETI_D6")
        r = await client.delete("/api/et/items/999999", headers=_bearer(uid))
        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_ITEM_001"

    async def test_非擁有者不可刪除(self, client, db) -> None:
        owner = await _user(db, "ETI_D7")
        other = await _user(db, "ETI_D8")
        _, chapter_id = await _chapter(client, owner)
        item = await _add_item(client, owner, chapter_id, ITEM_MATERIAL, "教材")
        r = await client.delete(f"/api/et/items/{item['item_id']}", headers=_bearer(other))
        assert r.status_code == 403
