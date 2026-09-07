"""Email 邀請：預覽、寄送與受邀加入（US8 / #273）。

`ET_ENROLL_003`「您已被移除出此課程，如需重新加入請聯繫教師」在 #247 交付時是一條
**死路**——「重新邀請」就是本 issue 要做的東西。本檔的
`test_被移除的學員可經_email_邀請回到課程` 是那句話第一次有對應操作。
"""

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.notify.models import DpEmailLog
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.common.tokens import hash_token
from app.et.constants import (
    COURSE_CLOSED,
    INVITATION_JOINED,
    INVITATION_PENDING,
    ITEM_MATERIAL,
    ROLE_STUDENT,
    ROLE_TEACHER,
    SOURCE_EMAIL_INVITE,
)
from app.et.course.models import EtCourse
from app.et.invitation.models import EtInvitation
from app.et.progress.models import EtEnrollment
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"
_ACCEPT = "/api/et/invitations/accept"


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str, role: str = ROLE_STUDENT, *, email: str | None = None) -> str:
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=email or f"{user_id}@edms.local",
            pwd_hash=hash_password("Abcd1234"),
            user_name=f"姓名{user_id}",
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


async def _published_course(client, db, teacher: str, *, name: str = "採血作業新進人員訓練") -> int:
    """建立並發布一門課程（掛一個沒有人員的標籤，避免產生非預期的收件人）。"""
    created = await client.post(
        _COURSES,
        json={"course_name": name, "open_start_at": "2026-09-01T00:00:00Z", "open_end_at": "2026-09-30T00:00:00Z"},
        headers=_bearer(teacher),
    )
    assert created.status_code == 201, created.text
    cid = created.json()["course_id"]
    tag = EtTag(
        tag_name=f"空標籤{cid}",
        is_active=True,
        is_all=False,
        is_builtin=False,
        created_user="SYSTEM",
        created_date=utcnow(),
        deleted=0,
    )
    db.add(tag)
    await db.flush()
    db.add(EtCourseTag(course_id=cid, tag_id=tag.tag_id, created_user="SYSTEM", created_date=utcnow(), deleted=0))
    ch = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(teacher))
    chapter_id = ch.json()["chapter_id"]
    await client.post(
        f"/api/et/chapters/{chapter_id}/items",
        json={"item_type": ITEM_MATERIAL, "title": "教材"},
        headers=_bearer(teacher),
    )
    published = await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(teacher))
    assert published.status_code == 200, published.text
    return cid


async def _account(db, email: str, *, user_id: str | None = None) -> str:
    """建立一個持有指定 Email 的學員帳號。

    SA 裁示後 Email 邀請**只收既有 EDMS 使用者**，故本檔的收件人一律要先有帳號；
    沒有帳號的 Email 用來驗 `ET_INVITE_005`。`user_id` 上限 20 字元，故由呼叫端指定。
    """
    return await _user(db, user_id or email.split("@")[0][:20], email=email)


async def _invite(client, teacher: str, course_id: int, emails: str):
    return await client.post(f"{_COURSES}/{course_id}/invitations", json={"emails": emails}, headers=_bearer(teacher))


async def _token_for(db, email: str) -> str:
    """由 outbox 內文取出實際寄出的明文 token（DB 只存雜湊，測試也拿不到明文）。"""
    log = await db.scalar(
        select(DpEmailLog).where(
            DpEmailLog.recipient == email,
            DpEmailLog.template_code == "COURSE_INVITE",
            DpEmailLog.status == "PENDING",
        )
    )
    assert log is not None, "沒有寄出任何信，無從取得 token"
    marker = "/et/invite?token="
    start = log.body.index(marker) + len(marker)
    end = start
    while end < len(log.body) and log.body[end] not in "\n \r":
        end += 1
    return log.body[start:end]


class TestPreview:
    """AC 6：多筆 Email → **唯讀預覽**。"""

    async def test_預覽以統一範本渲染且帶入課程資訊(self, client, db) -> None:
        teacher = await _user(db, "iv_t01", ROLE_TEACHER)
        await _account(db, "iva@x.gov.tw", user_id="iv_a01")
        await _account(db, "ivb@x.gov.tw", user_id="iv_b01")
        cid = await _published_course(client, db, teacher, name="感染管制年度訓練")

        r = await client.post(
            f"{_COURSES}/{cid}/invitations/preview",
            json={"emails": "iva@x.gov.tw\nivb@x.gov.tw"},
            headers=_bearer(teacher),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "感染管制年度訓練" in body["subject"]
        assert "姓名iv_t01" in body["body"], "應帶入課程擁有者姓名"
        assert "{" not in body["body"], "殘留未代入的佔位符代表 params key 對不上"

    async def test_預覽不呈現任何一位收件人的資料(self, client, db) -> None:
        """預覽只有一份，而每封信代入各自的姓名。

        填第 1 筆會讓教師以為每封信都長那樣；填 Email 更糟——實際寄出用的是帳號姓名，
        預覽與收到的信對不起來（使用者實測回報）。
        """
        teacher = await _user(db, "iv_t11", ROLE_TEACHER)
        await _account(db, "ivc@x.gov.tw", user_id="iv_c01")
        await _account(db, "ivd@x.gov.tw", user_id="iv_d01")
        cid = await _published_course(client, db, teacher)

        r = await client.post(
            f"{_COURSES}/{cid}/invitations/preview",
            json={"emails": "ivc@x.gov.tw,ivd@x.gov.tw"},
            headers=_bearer(teacher),
        )
        body = r.json()
        assert "〔收件人姓名〕" in body["body"], "應以佔位字樣取代稱謂"
        assert "ivc@x.gov.tw" not in body["body"]
        assert "ivd@x.gov.tw" not in body["body"]
        assert "姓名iv_c01" not in body["body"], "不得洩漏收件人的真實姓名"
        assert "recipient_sample" not in body
        assert "recipient_count" not in body

    async def test_預覽內容不隨收件人清單變動(self, client, db) -> None:
        """這是「改動清單不需重新預覽」的依據（使用者回饋 3）。"""
        teacher = await _user(db, "iv_t12", ROLE_TEACHER)
        await _account(db, "ive@x.gov.tw", user_id="iv_e01")
        await _account(db, "ivf@x.gov.tw", user_id="iv_f01")
        cid = await _published_course(client, db, teacher)
        url = f"{_COURSES}/{cid}/invitations/preview"

        one = await client.post(url, json={"emails": "ive@x.gov.tw"}, headers=_bearer(teacher))
        two = await client.post(url, json={"emails": "ive@x.gov.tw,ivf@x.gov.tw"}, headers=_bearer(teacher))
        assert one.json() == two.json()

    async def test_預覽不含可用的_token(self, client, db) -> None:
        """每位收件人的 token 於寄出當下才產生；預覽給出真的連結才是問題。"""
        teacher = await _user(db, "iv_t02", ROLE_TEACHER)
        await _account(db, "ivg@x.gov.tw", user_id="iv_g01")
        cid = await _published_course(client, db, teacher)
        r = await client.post(
            f"{_COURSES}/{cid}/invitations/preview", json={"emails": "ivg@x.gov.tw"}, headers=_bearer(teacher)
        )
        assert "/et/invite?token=…" in r.json()["body"]

    async def test_預覽不寫入任何邀請列也不寄信(self, client, db) -> None:
        teacher = await _user(db, "iv_t03", ROLE_TEACHER)
        await _account(db, "ivh@x.gov.tw", user_id="iv_h01")
        cid = await _published_course(client, db, teacher)
        await client.post(
            f"{_COURSES}/{cid}/invitations/preview", json={"emails": "ivh@x.gov.tw"}, headers=_bearer(teacher)
        )
        assert (await db.execute(select(EtInvitation))).scalars().all() == []
        logs = (await db.execute(select(DpEmailLog).where(DpEmailLog.template_code == "COURSE_INVITE"))).scalars().all()
        assert logs == []


class TestSendInvitations:
    """AC 6：寄出並記錄 `SEND_STATUS_CODE`。"""

    async def test_每筆_email_建立待加入邀請並寄信(self, client, db) -> None:
        teacher = await _user(db, "iv_t04", ROLE_TEACHER)
        await _account(db, "ivi@x.gov.tw", user_id="iv_i01")
        await _account(db, "ivj@x.gov.tw", user_id="iv_j01")
        cid = await _published_course(client, db, teacher)

        r = await _invite(client, teacher, cid, "ivi@x.gov.tw, ivj@x.gov.tw")
        assert r.status_code == 200, r.text
        assert r.json() == {"sent": 2, "failed": []}

        rows = (await db.execute(select(EtInvitation).order_by(EtInvitation.email))).scalars().all()
        assert [row.email for row in rows] == ["ivi@x.gov.tw", "ivj@x.gov.tw"]
        assert all(row.status == INVITATION_PENDING for row in rows)
        assert all(row.send_status_code == "QUEUED" for row in rows)
        assert all(row.token_hash for row in rows)

    async def test_明文_token_不落庫(self, client, db) -> None:
        """DB 只存 SHA-256；該表外洩不得反推出可用的連結。"""
        teacher = await _user(db, "iv_t05", ROLE_TEACHER)
        await _account(db, "ivk@x.gov.tw", user_id="iv_k01")
        cid = await _published_course(client, db, teacher)
        await _invite(client, teacher, cid, "ivk@x.gov.tw")

        token = await _token_for(db, "ivk@x.gov.tw")
        row = await db.scalar(select(EtInvitation).where(EtInvitation.email == "ivk@x.gov.tw"))
        assert row.token_hash != token
        assert row.token_hash == hash_token(token)

    async def test_同一_email_再次寄送不建新列且換新_token(self, client, db) -> None:
        """data-model：「再次寄送」更新 `LAST_SENT_AT`、不建新紀錄。

        換新 token 是一次性的前提——舊 token 已隨信件流出，沿用等於留一條舊路。
        """
        teacher = await _user(db, "iv_t06", ROLE_TEACHER)
        await _account(db, "ivl@x.gov.tw", user_id="iv_l01")
        cid = await _published_course(client, db, teacher)
        await _invite(client, teacher, cid, "ivl@x.gov.tw")
        first = await db.scalar(select(EtInvitation).where(EtInvitation.email == "ivl@x.gov.tw"))
        first_hash, first_id = first.token_hash, first.invitation_id

        await _invite(client, teacher, cid, "ivl@x.gov.tw")

        rows = (await db.execute(select(EtInvitation).where(EtInvitation.email == "ivl@x.gov.tw"))).scalars().all()
        assert len(rows) == 1, "再次寄送不得建新列"
        assert rows[0].invitation_id == first_id
        assert rows[0].token_hash != first_hash, "再次寄送必須換新 token"

    async def test_同一次貼上的重複_email_只寄一封(self, client, db) -> None:
        teacher = await _user(db, "iv_t07", ROLE_TEACHER)
        await _account(db, "ivm@x.gov.tw", user_id="iv_m01")
        cid = await _published_course(client, db, teacher)
        r = await _invite(client, teacher, cid, "IVM@x.gov.tw, ivm@x.gov.tw\nivm@X.gov.tw")
        assert r.json()["sent"] == 1

    async def test_草稿課程不可邀請(self, client, db) -> None:
        teacher = await _user(db, "iv_t08", ROLE_TEACHER)
        created = await client.post(_COURSES, json={"course_name": "草稿課程"}, headers=_bearer(teacher))
        cid = created.json()["course_id"]
        await _account(db, "ivn@x.gov.tw", user_id="iv_n01")
        r = await _invite(client, teacher, cid, "ivn@x.gov.tw")
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_INVITE_004"

    async def test_非擁有者不可邀請(self, client, db) -> None:
        teacher = await _user(db, "iv_t09", ROLE_TEACHER)
        other = await _user(db, "iv_t10", ROLE_TEACHER)
        cid = await _published_course(client, db, teacher)
        await _account(db, "ivo@x.gov.tw", user_id="iv_o01")
        r = await _invite(client, other, cid, "ivo@x.gov.tw")
        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_COURSE_002"


class TestUnknownEmailIsRejected:
    """SA 裁示：Email 邀請只收既有 EDMS 使用者。

    教師是用貼的，打錯一個字就會把課程資訊寄給系統外的陌生人，而他自己要到 US12 待加入
    清單才可能發現——且 `SEND_STATUS_CODE` 只記「排入佇列」，連退信都不會顯示在那裡。
    """

    async def test_寄送時查無帳號一律擋下且不建邀請列(self, client, db) -> None:
        teacher = await _user(db, "un_t01", ROLE_TEACHER)
        await _account(db, "known@x.gov.tw", user_id="un_k01")
        cid = await _published_course(client, db, teacher)

        r = await _invite(client, teacher, cid, "known@x.gov.tw, typo@x.gov.tw")

        assert r.status_code == 422
        body = r.json()
        assert body["error_code"] == "ET_INVITE_005"
        assert body["unknown_emails"] == ["typo@x.gov.tw"], "須指出是哪幾筆"
        # 全批擋下：不可只寄有帳號的那幾封（教師會以為全部都寄出去了）
        assert (await db.execute(select(EtInvitation))).scalars().all() == []

    async def test_預覽階段就擋下_不必等到按寄出(self, client, db) -> None:
        teacher = await _user(db, "un_t02", ROLE_TEACHER)
        cid = await _published_course(client, db, teacher)

        r = await client.post(
            f"{_COURSES}/{cid}/invitations/preview",
            json={"emails": "nobody@x.gov.tw"},
            headers=_bearer(teacher),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_INVITE_005"

    async def test_錯誤訊息本身不含_email(self, client, db) -> None:
        """`sti-error-codes`：`error_message` 不得嵌入動態值，明細走 `unknown_emails`。"""
        teacher = await _user(db, "un_t03", ROLE_TEACHER)
        cid = await _published_course(client, db, teacher)

        r = await _invite(client, teacher, cid, "typo2@x.gov.tw")
        assert "typo2@x.gov.tw" not in r.json()["error_message"]


class TestAcceptInvitation:
    """AC 7 / AC 8：點連結加入、已加入者導向、一次性。"""

    async def _invited_token(self, client, db, teacher: str, invitee_email: str) -> tuple[int, str]:
        cid = await _published_course(client, db, teacher)
        r = await _invite(client, teacher, cid, invitee_email)
        assert r.status_code == 200, r.text
        return cid, await _token_for(db, invitee_email)

    async def test_點連結後加入課程且來源記為_email_邀請(self, client, db) -> None:
        teacher = await _user(db, "ac_t01", ROLE_TEACHER)
        invitee = await _user(db, "ac_s01")
        cid, token = await self._invited_token(client, db, teacher, f"{invitee}@edms.local")

        r = await client.post(_ACCEPT, json={"token": token}, headers=_bearer(invitee))
        assert r.status_code == 200, r.text
        assert r.json()["course_id"] == cid
        assert r.json()["already_joined"] is False

        row = await db.scalar(
            select(EtEnrollment).where(EtEnrollment.user_id == invitee, EtEnrollment.course_id == cid)
        )
        assert row.join_source == SOURCE_EMAIL_INVITE
        assert row.is_removed is False

        invitation = await db.scalar(select(EtInvitation).where(EtInvitation.course_id == cid))
        assert invitation.status == INVITATION_JOINED
        assert invitation.joined_at is not None

    async def test_已加入者再點同一條連結導向課程不重複加入(self, client, db) -> None:
        """AC 8。token 已消耗，但呼叫者已在名單內 → 正常導航而非錯誤。"""
        teacher = await _user(db, "ac_t02", ROLE_TEACHER)
        invitee = await _user(db, "ac_s02")
        cid, token = await self._invited_token(client, db, teacher, f"{invitee}@edms.local")
        await client.post(_ACCEPT, json={"token": token}, headers=_bearer(invitee))

        again = await client.post(_ACCEPT, json={"token": token}, headers=_bearer(invitee))
        assert again.status_code == 200, again.text
        assert again.json()["already_joined"] is True
        assert again.json()["course_id"] == cid

        rows = (await db.execute(select(EtEnrollment).where(EtEnrollment.user_id == invitee))).scalars().all()
        assert len(rows) == 1

    async def test_連結被轉發給第二個人時失效(self, client, db) -> None:
        """一次性（#273 Q1 裁示）：token 消耗後，不在名單內的人拿到它一律無效。"""
        teacher = await _user(db, "ac_t03", ROLE_TEACHER)
        invitee = await _user(db, "ac_s03")
        stranger = await _user(db, "ac_s04")
        _cid, token = await self._invited_token(client, db, teacher, f"{invitee}@edms.local")
        await client.post(_ACCEPT, json={"token": token}, headers=_bearer(invitee))

        r = await client.post(_ACCEPT, json={"token": token}, headers=_bearer(stranger))
        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_INVITE_001"
        assert (await db.execute(select(EtEnrollment).where(EtEnrollment.user_id == stranger))).scalars().all() == []

    async def test_不比對登入帳號_email(self, client, db) -> None:
        """#273 Q1 裁示：不比對——收信信箱與登入帳號不同是常見情形。

        邀請寄到 personal@example.com，但受邀者用他的公務帳號登入後點連結，仍可加入。
        """
        teacher = await _user(db, "ac_t04", ROLE_TEACHER)
        invitee = await _user(db, "ac_s05", email="office_ac_s05@edms.local")
        # 邀請寄到**另一位使用者**的信箱，但由 ac_s05 登入後點連結——仍可加入。
        await _user(db, "ac_s05b", email="other_ac_s05@edms.local")
        cid, token = await self._invited_token(client, db, teacher, "other_ac_s05@edms.local")

        r = await client.post(_ACCEPT, json={"token": token}, headers=_bearer(invitee))
        assert r.status_code == 200, r.text
        assert r.json()["course_id"] == cid

    async def test_被移除的學員可經_email_邀請回到課程(self, client, db) -> None:
        """issue 約束 2：Email 邀請是**唯一**能讓被移除者回來的路徑。

        `UQ_ET_ENROLLMENT_USER_COURSE` 為全表唯一、他那一列還在，故必須 upsert；
        INSERT 會撞鍵並讓教師看到一個指向他看不見之列的資料庫錯誤。
        """
        teacher = await _user(db, "ac_t05", ROLE_TEACHER)
        invitee = await _user(db, "ac_s06")
        cid = await _published_course(client, db, teacher)
        now = utcnow()
        db.add(
            EtEnrollment(
                user_id=invitee,
                course_id=cid,
                join_source="TAG_DEFAULT",
                joined_at=now,
                completion_status="IN_PROGRESS",
                is_removed=True,
                removed_at=now,
                created_user="SYSTEM",
                created_date=now,
                deleted=0,
            )
        )
        await db.flush()

        await _invite(client, teacher, cid, f"{invitee}@edms.local")
        token = await _token_for(db, f"{invitee}@edms.local")
        r = await client.post(_ACCEPT, json={"token": token}, headers=_bearer(invitee))
        assert r.status_code == 200, r.text

        rows = (await db.execute(select(EtEnrollment).where(EtEnrollment.user_id == invitee))).scalars().all()
        assert len(rows) == 1, "必須 upsert 既有列，不可新增第二列"
        assert rows[0].is_removed is False
        assert rows[0].removed_at is None
        assert rows[0].join_source == SOURCE_EMAIL_INVITE
        assert rows[0].completion_status == "IN_PROGRESS", "回鍋不得重置學習狀態"

    async def test_邀請只能被消耗一次(self, client, db) -> None:
        """一次性由 DB 的條件式 UPDATE 保證，不是由「先查後改」的讀寫間隙保證。

        直接打 repository：兩個併發請求最終都會走到 `consume_pending`，第二次必須回
        False（否則兩人都會被加入，見該方法之說明）。以循序兩次呼叫釘住那個條件——
        若有人把 `WHERE STATUS='PENDING'` 拿掉，本測試會紅。
        """
        from app.core.operator import OperatorInfo
        from app.et.invitation.repository import EtInvitationRepository

        teacher = await _user(db, "cs_t01", ROLE_TEACHER)
        await _account(db, "ivp@x.gov.tw", user_id="iv_p01")
        cid = await _published_course(client, db, teacher)
        await _invite(client, teacher, cid, "ivp@x.gov.tw")
        row = await db.scalar(select(EtInvitation).where(EtInvitation.email == "ivp@x.gov.tw"))

        repo = EtInvitationRepository()
        first = await repo.consume_pending(db, invitation_id=row.invitation_id, operator=OperatorInfo(user_id="u1"))
        second = await repo.consume_pending(db, invitation_id=row.invitation_id, operator=OperatorInfo(user_id="u2"))

        assert first is True
        assert second is False, "第二次消耗必須失敗，否則一次性可被併發繞過"

    async def test_無效_token_回連結無效(self, client, db) -> None:
        user = await _user(db, "ac_s07")
        r = await client.post(_ACCEPT, json={"token": "does-not-exist"}, headers=_bearer(user))
        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_INVITE_001"

    async def test_課程關閉期間連結暫時失效(self, client, db) -> None:
        """#273 Q2 裁示：以課程狀態為有效期邊界，與邀請碼同一規則。"""
        teacher = await _user(db, "ac_t08", ROLE_TEACHER)
        invitee = await _user(db, "ac_s08")
        cid, token = await self._invited_token(client, db, teacher, f"{invitee}@edms.local")
        course = await db.scalar(select(EtCourse).where(EtCourse.course_id == cid))
        course.status = COURSE_CLOSED
        await db.flush()

        r = await client.post(_ACCEPT, json={"token": token}, headers=_bearer(invitee))
        assert r.status_code == 409
        assert r.json()["error_code"] == "ET_INVITE_002"
