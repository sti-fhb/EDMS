"""Email 邀請：預覽、寄送與受邀加入（US8 / #273）。

`ET_ENROLL_003`「您已被移除出此課程，如需重新加入請聯繫教師」在 #247 交付時是一條
**死路**——「重新邀請」就是本 issue 要做的東西。本檔的
`test_被移除的學員可經_email_邀請回到課程` 是那句話第一次有對應操作。
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

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
    INVITATION_REVOKED,
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
    # ⚠️ 必須排序：重寄後同一收件人會有兩封 PENDING 信，無 `order_by` 時取到哪一封
    # 由執行計畫決定。取**最新**的那封——呼叫端要的一律是「剛剛寄出的那個 token」。
    log = await db.scalar(
        select(DpEmailLog)
        .where(
            DpEmailLog.recipient == email,
            DpEmailLog.template_code == "COURSE_INVITE",
            DpEmailLog.status == "PENDING",
        )
        .order_by(DpEmailLog.message_id.desc())
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


class TestPendingInviteList:
    """ET-12 待加入清單（AC 1 / 2 / 6）。

    清單只列 `PENDING`——`JOINED` 已在「已加入」分頁（US9），`REVOKED` 是終態且教師
    已明示不要那個人。三者混列會讓教師分不出哪些還需要追。
    """

    async def test_待加入清單只列PENDING(self, client, db) -> None:
        teacher = await _user(db, "t_pi01", ROLE_TEACHER)
        course_id = await _published_course(client, db, teacher)
        await _account(db, "pending01@edms.local")
        await _account(db, "joined01@edms.local")
        await _account(db, "revoked01@edms.local")
        await _invite(client, teacher, course_id, "pending01@edms.local,joined01@edms.local,revoked01@edms.local")
        # 一筆改 JOINED、一筆改 REVOKED（撤回端點於步驟 2 才做）
        await db.execute(
            update(EtInvitation)
            .where(EtInvitation.course_id == course_id, EtInvitation.email == "joined01@edms.local")
            .values(status=INVITATION_JOINED, joined_at=utcnow())
        )
        await db.execute(
            update(EtInvitation)
            .where(EtInvitation.course_id == course_id, EtInvitation.email == "revoked01@edms.local")
            .values(status=INVITATION_REVOKED, revoked_at=utcnow())
        )
        await db.commit()

        r = await client.get(f"{_COURSES}/{course_id}/invitations", headers=_bearer(teacher))

        assert r.status_code == 200, r.text
        emails = [row["email"] for row in r.json()["data"]]
        assert emails == ["pending01@edms.local"]

    async def test_待加入清單欄位齊全(self, client, db) -> None:
        teacher = await _user(db, "t_pi02", ROLE_TEACHER)
        course_id = await _published_course(client, db, teacher)
        await _account(db, "fields01@edms.local")
        await _invite(client, teacher, course_id, "fields01@edms.local")
        await db.commit()

        r = await client.get(f"{_COURSES}/{course_id}/invitations", headers=_bearer(teacher))

        row = r.json()["data"][0]
        assert row["email"] == "fields01@edms.local"
        assert row["status"] == INVITATION_PENDING
        # 顯示 LAST_SENT_AT 而非 SENT_AT：教師重寄後畫面日期不變會讓他以為沒寄出去
        assert row["last_sent_at"] is not None
        assert "invitation_id" in row, "前端要用它呼叫重寄 / 撤回"

    async def test_他人課程不可讀待加入清單(self, client, db) -> None:
        """擁有權判定——非擁有者拿不到別人課程的受邀 Email 名單。"""
        owner = await _user(db, "t_pi03", ROLE_TEACHER)
        other = await _user(db, "t_pi03b", ROLE_TEACHER)
        course_id = await _published_course(client, db, owner)
        await _account(db, "secret01@edms.local")
        await _invite(client, owner, course_id, "secret01@edms.local")
        await db.commit()

        r = await client.get(f"{_COURSES}/{course_id}/invitations", headers=_bearer(other))

        assert r.status_code == 403, r.text

    async def test_課程已關閉仍可讀待加入清單(self, client, db) -> None:
        """AC 7 的「讀」那一半——關閉只停寫入，清單照常可看。"""
        teacher = await _user(db, "t_pi04", ROLE_TEACHER)
        course_id = await _published_course(client, db, teacher)
        await _account(db, "closed01@edms.local")
        await _invite(client, teacher, course_id, "closed01@edms.local")
        await db.execute(update(EtCourse).where(EtCourse.course_id == course_id).values(status=COURSE_CLOSED))
        await db.commit()

        r = await client.get(f"{_COURSES}/{course_id}/invitations", headers=_bearer(teacher))

        assert r.status_code == 200, r.text
        assert len(r.json()["data"]) == 1


class TestResendInvitation:
    """再次寄送（AC 3）。"""

    async def test_再次寄送更新最後寄送時間且不建新列(self, client, db) -> None:
        """`data-model` §ET_INVITATION：「再次寄送」更新 `LAST_SENT_AT`，**不建新紀錄**。

        建新列會讓同一個受邀者在清單上出現多次，教師無從判斷該重寄哪一筆；且舊 token
        不會失效。
        """
        teacher = await _user(db, "t_rs01", ROLE_TEACHER)
        course_id = await _published_course(client, db, teacher)
        await _account(db, "resend01@edms.local")
        await _invite(client, teacher, course_id, "resend01@edms.local")
        await db.commit()
        listed = await client.get(f"{_COURSES}/{course_id}/invitations", headers=_bearer(teacher))
        row = listed.json()["data"][0]
        before = row["last_sent_at"]

        r = await client.post(f"/api/et/invitations/{row['invitation_id']}/resend", headers=_bearer(teacher))

        assert r.status_code == 204, r.text
        after = await client.get(f"{_COURSES}/{course_id}/invitations", headers=_bearer(teacher))
        rows = after.json()["data"]
        assert len(rows) == 1, "不可建新列"
        assert rows[0]["last_sent_at"] >= before

    async def test_再次寄送換新token舊連結失效(self, client, db) -> None:
        """舊 token 已隨信流出，沿用會讓「一次性」只是延後生效（`upsert_pending` docstring）。"""
        teacher = await _user(db, "t_rs02", ROLE_TEACHER)
        course_id = await _published_course(client, db, teacher)
        student = await _account(db, "resend02@edms.local")
        await _invite(client, teacher, course_id, "resend02@edms.local")
        await db.commit()
        old_token = await _token_for(db, "resend02@edms.local")
        listed = await client.get(f"{_COURSES}/{course_id}/invitations", headers=_bearer(teacher))
        await client.post(
            f"/api/et/invitations/{listed.json()['data'][0]['invitation_id']}/resend", headers=_bearer(teacher)
        )
        await db.commit()

        r = await client.post(_ACCEPT, json={"token": old_token}, headers=_bearer(student))

        assert r.status_code == 404, r.text
        assert r.json()["error_code"] == "ET_INVITE_001"

    async def test_手動關閉時不可再次寄送(self, client, db) -> None:
        """AC 7 的「寫」那一半——**來源一：教師手動關閉**。

        ⚠️ 回 `ET_INVITE_004`（422）而非 `ET_INVITE_002`（409）。#288 刻意分流：
        草稿 / 已關閉 → `004`「僅已發布課程可邀請學員」；**已發布但期間已過** → `002`
        「此課程目前關閉中」。共用一碼會對一門 `STATUS` 確實是 `PUBLISHED` 的課程說出
        與教師畫面矛盾的話。
        """
        teacher = await _user(db, "t_rs03", ROLE_TEACHER)
        course_id = await _published_course(client, db, teacher)
        await _account(db, "resend03@edms.local")
        await _invite(client, teacher, course_id, "resend03@edms.local")
        await db.commit()
        listed = await client.get(f"{_COURSES}/{course_id}/invitations", headers=_bearer(teacher))
        invitation_id = listed.json()["data"][0]["invitation_id"]
        await db.execute(update(EtCourse).where(EtCourse.course_id == course_id).values(status=COURSE_CLOSED))
        await db.commit()

        r = await client.post(f"/api/et/invitations/{invitation_id}/resend", headers=_bearer(teacher))

        assert r.status_code == 422, r.text
        assert r.json()["error_code"] == "ET_INVITE_004"

    async def test_閱課期間已過時不可再次寄送(self, client, db) -> None:
        """AC 7 的「寫」那一半——**來源二：已發布但閱課期間已過**（ET-16 掃到之前的空窗）。

        這條與上一條是同一個 AC 的兩種來源，回的碼不同（見上）。只驗其中一種會讓另一
        條路徑無覆蓋——而「期間已過但狀態仍是 PUBLISHED」在 ET-16 排程執行前是真實狀態。
        """
        teacher = await _user(db, "t_rs04", ROLE_TEACHER)
        course_id = await _published_course(client, db, teacher)
        await _account(db, "resend04@edms.local")
        await _invite(client, teacher, course_id, "resend04@edms.local")
        await db.commit()
        listed = await client.get(f"{_COURSES}/{course_id}/invitations", headers=_bearer(teacher))
        invitation_id = listed.json()["data"][0]["invitation_id"]
        # 狀態維持 PUBLISHED，只把訖止推到過去
        await db.execute(
            update(EtCourse).where(EtCourse.course_id == course_id).values(open_end_at=utcnow() - timedelta(days=1))
        )
        await db.commit()

        r = await client.post(f"/api/et/invitations/{invitation_id}/resend", headers=_bearer(teacher))

        assert r.status_code == 409, r.text
        assert r.json()["error_code"] == "ET_INVITE_002"


class TestRevokeInvitation:
    """撤回邀請（AC 4）。"""

    async def test_撤回寫入狀態與時間並移出清單(self, client, db) -> None:
        teacher = await _user(db, "t_rv01", ROLE_TEACHER)
        course_id = await _published_course(client, db, teacher)
        await _account(db, "revoke01@edms.local")
        await _invite(client, teacher, course_id, "revoke01@edms.local")
        await db.commit()
        listed = await client.get(f"{_COURSES}/{course_id}/invitations", headers=_bearer(teacher))
        invitation_id = listed.json()["data"][0]["invitation_id"]

        r = await client.post(f"/api/et/invitations/{invitation_id}/revoke", headers=_bearer(teacher))

        assert r.status_code == 204, r.text
        row = await db.scalar(select(EtInvitation).where(EtInvitation.invitation_id == invitation_id))
        await db.refresh(row)
        assert row.status == INVITATION_REVOKED
        assert row.revoked_at is not None
        after = await client.get(f"{_COURSES}/{course_id}/invitations", headers=_bearer(teacher))
        assert after.json()["data"] == [], "撤回後自待加入清單移除"

    async def test_課程關閉時仍可撤回邀請(self, client, db) -> None:
        """🔴 **SA 裁示 2026-09-16：撤回不受課程關閉影響。**

        這是本 issue 唯一偏離 ET 模組「讀照舊、寫全停」慣例的地方。`FR-ET-US12-06` 只
        點名「再次寄送」，而撤回與重寄方向相反——重寄讓**更多人**進來，撤回讓**某人
        不能**進來。

        教師發現邀請寄錯人（例如打錯 Email 寄到外部單位）時，若課程剛好到期自動關閉
        而撤回被擋，那條錯誤連結會一直有效到再開課為止，且再開課當下立刻可用。

        **本測試存在的唯一理由**：日後有人依慣例把關閉守門補到 `revoke()` 上時，要有
        東西會紅。少了它，那個行為改變不會被任何測試發現。
        """
        teacher = await _user(db, "t_rv02", ROLE_TEACHER)
        course_id = await _published_course(client, db, teacher)
        await _account(db, "revoke02@edms.local")
        await _invite(client, teacher, course_id, "revoke02@edms.local")
        await db.commit()
        listed = await client.get(f"{_COURSES}/{course_id}/invitations", headers=_bearer(teacher))
        invitation_id = listed.json()["data"][0]["invitation_id"]
        await db.execute(update(EtCourse).where(EtCourse.course_id == course_id).values(status=COURSE_CLOSED))
        await db.commit()

        r = await client.post(f"/api/et/invitations/{invitation_id}/revoke", headers=_bearer(teacher))

        assert r.status_code == 204, "撤回是止血動作，關閉期間必須仍可執行"

    async def test_他人不可撤回別人課程的邀請(self, client, db) -> None:
        owner = await _user(db, "t_rv03", ROLE_TEACHER)
        other = await _user(db, "t_rv03b", ROLE_TEACHER)
        course_id = await _published_course(client, db, owner)
        await _account(db, "revoke03@edms.local")
        await _invite(client, owner, course_id, "revoke03@edms.local")
        await db.commit()
        listed = await client.get(f"{_COURSES}/{course_id}/invitations", headers=_bearer(owner))
        invitation_id = listed.json()["data"][0]["invitation_id"]

        r = await client.post(f"/api/et/invitations/{invitation_id}/revoke", headers=_bearer(other))

        assert r.status_code == 403, r.text


class TestRevokedLinkMessage:
    """已撤回連結的專用訊息（AC 5 / `FR-ET-US12-05` / `ET-MSG-ET03-104`）。

    ## 這組測試是成對的，不可只留一條

    SA 於 2026-09-16 裁示把「已撤回」自 `ET_INVITE_001` 分流出來，接受的是**持有有效
    token 者可知其狀態**——不是「任何人拿亂數 token 都能問出它曾否存在」。

    所以 `test_已撤回回006` 驗它**會**出現，`test_查無token仍回001` 驗它**不會**被放寬
    成「找不到有效邀請」的通用分支。少了後者，`ET_INVITE_006` 很容易在日後重構時被
    擴大到整個 `invitation is None` 的路徑上，那就成了存在性 oracle 的放大版。
    """

    async def test_已撤回連結回006(self, client, db) -> None:
        teacher = await _user(db, "t_rl01", ROLE_TEACHER)
        course_id = await _published_course(client, db, teacher)
        student = await _account(db, "revlink01@edms.local")
        await _invite(client, teacher, course_id, "revlink01@edms.local")
        await db.commit()
        token = await _token_for(db, "revlink01@edms.local")
        listed = await client.get(f"{_COURSES}/{course_id}/invitations", headers=_bearer(teacher))
        await client.post(
            f"/api/et/invitations/{listed.json()['data'][0]['invitation_id']}/revoke", headers=_bearer(teacher)
        )
        await db.commit()

        r = await client.post(_ACCEPT, json={"token": token}, headers=_bearer(student))

        assert r.status_code == 410, r.text
        assert r.json()["error_code"] == "ET_INVITE_006"

    async def test_查無token仍回001(self, client, db) -> None:
        """🔴 從未存在過的 token **不可**得到「已撤回」。

        分流若放寬到 `invitation is None`，攻擊者就能用亂數 token 列舉「哪些曾經存在」。
        """
        student = await _user(db, "s_rl02")
        await db.commit()

        r = await client.post(_ACCEPT, json={"token": "this-token-never-existed-at-all"}, headers=_bearer(student))

        assert r.status_code == 404, r.text
        assert r.json()["error_code"] == "ET_INVITE_001", "查無 ≠ 已撤回"

    async def test_已加入的token不回006(self, client, db) -> None:
        """已消耗（`JOINED`）**不分流**——那是另一種終態，且 spec 只要求撤回有專用訊息。

        ⚠️ 已加入者再點連結**回 200 + `already_joined=true`**，不是錯誤（US8 AC 8：不重複
        加入、直接導向）。本條驗的是它沒有被誤導向 `ET_INVITE_006`。
        """
        teacher = await _user(db, "t_rl03", ROLE_TEACHER)
        course_id = await _published_course(client, db, teacher)
        student = await _account(db, "revlink03@edms.local")
        await _invite(client, teacher, course_id, "revlink03@edms.local")
        await db.commit()
        token = await _token_for(db, "revlink03@edms.local")
        first = await client.post(_ACCEPT, json={"token": token}, headers=_bearer(student))
        assert first.status_code == 200, first.text
        await db.commit()

        r = await client.post(_ACCEPT, json={"token": token}, headers=_bearer(student))

        assert r.status_code == 200, r.text
        assert r.json()["already_joined"] is True, "已加入者直接導向，不是錯誤"


class TestInviteWriteRaces:
    """撤回 / 重寄的原子性（Security Review M-1 / M-2）。

    兩支寫入原本都是「先查後改」——而**同一個檔案**的 `consume_pending` docstring 早就
    寫明那是 TOCTOU（`🔴 條件必須寫在 WHERE 裡，不可先查後改`），還附了 EvalPlanQual
    的完整說明。本組測試釘住修正後的行為。
    """

    async def test_已加入者不可被撤回(self, client, db) -> None:
        """撤回輸掉與 `accept` 的競態時回 404，**不可把 `JOINED` 蓋成 `REVOKED`**。

        真的蓋掉的話：學員已入課、`ET_ENROLLMENT` 已建立，教師卻收到 204 且該列自清單
        消失——他不會知道要改用 US9 的「移除學員」。
        """
        teacher = await _user(db, "t_wr01", ROLE_TEACHER)
        course_id = await _published_course(client, db, teacher)
        student = await _account(db, "race01@edms.local")
        await _invite(client, teacher, course_id, "race01@edms.local")
        await db.commit()
        token = await _token_for(db, "race01@edms.local")
        listed = await client.get(f"{_COURSES}/{course_id}/invitations", headers=_bearer(teacher))
        invitation_id = listed.json()["data"][0]["invitation_id"]
        accepted = await client.post(_ACCEPT, json={"token": token}, headers=_bearer(student))
        assert accepted.status_code == 200, accepted.text
        await db.commit()

        r = await client.post(f"/api/et/invitations/{invitation_id}/revoke", headers=_bearer(teacher))

        assert r.status_code == 404, r.text
        row = await db.scalar(select(EtInvitation).where(EtInvitation.invitation_id == invitation_id))
        await db.refresh(row)
        assert row.status == INVITATION_JOINED, "已加入的狀態不可被撤回覆蓋"

    async def test_已撤回者不可再重寄(self, client, db) -> None:
        """🔴 重寄**不得憑空造出新列**。

        原實作用 `upsert_pending(course_id, email)`，而 `ET_INVITATION` 沒有該組合的唯一
        鍵——找不到 `PENDING` 列時它會**新建一列**，於是剛被撤回的對象會重新拿到一條
        有效連結，清單上也多出一列（違反 data-model 的「再次寄送不建新紀錄」）。
        """
        teacher = await _user(db, "t_wr02", ROLE_TEACHER)
        course_id = await _published_course(client, db, teacher)
        await _account(db, "race02@edms.local")
        await _invite(client, teacher, course_id, "race02@edms.local")
        await db.commit()
        listed = await client.get(f"{_COURSES}/{course_id}/invitations", headers=_bearer(teacher))
        invitation_id = listed.json()["data"][0]["invitation_id"]
        await client.post(f"/api/et/invitations/{invitation_id}/revoke", headers=_bearer(teacher))
        await db.commit()

        r = await client.post(f"/api/et/invitations/{invitation_id}/resend", headers=_bearer(teacher))

        assert r.status_code == 404, r.text
        total = await db.scalar(
            select(func.count(EtInvitation.invitation_id)).where(EtInvitation.course_id == course_id)
        )
        assert total == 1, "不可新建列——已撤回者不該因重寄而復活"
