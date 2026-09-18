"""Email 邀請：預覽與寄送即加入（US8 / #273、#362）。

`ET_ENROLL_003`「您已被移除出此課程，如需重新加入請聯繫教師」在 #247 交付時是一條
**死路**——「重新邀請」就是 US8 做的東西。本檔的
`test_被移除的學員可經_email_邀請回到課程` 是那句話唯一有對應操作的地方。

#362 取消「待加入」中間狀態後，本檔少了 accept / 清單 / 重寄 / 撤回四組測試。它們釘的
規則隨功能一起消失（沒有 token 就沒有一次性、沒有待加入列就沒有撤回），**不是**被移到
別處——見 `app/et/invitation/service.py` 模組 docstring 的取捨表。
"""

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.notify.models import DpEmailLog
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.constants import (
    ITEM_MATERIAL,
    ROLE_STUDENT,
    ROLE_TEACHER,
    SOURCE_EMAIL_INVITE,
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


async def _enrollments(db, course_id: int) -> list[EtEnrollment]:
    rows = await db.execute(
        select(EtEnrollment).where(EtEnrollment.course_id == course_id).order_by(EtEnrollment.user_id)
    )
    return list(rows.scalars().all())


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

    async def test_預覽的連結與實際寄出的相同(self, client, db) -> None:
        """#362：連結改為學習頁後人人相同，預覽給真值。

        原本這條驗的是**相反**的事——預覽不得含可用的 token（`/et/invite?token=…`）。
        那條規則的前提是「每人一個一次性 token、預覽當下還沒產生」，兩者都已隨 #362
        消失。現在遮起來反而讓教師看到一條與收件人實際收到的不一樣的連結。
        """
        teacher = await _user(db, "iv_t02", ROLE_TEACHER)
        await _account(db, "ivg@x.gov.tw", user_id="iv_g01")
        cid = await _published_course(client, db, teacher)

        preview = await client.post(
            f"{_COURSES}/{cid}/invitations/preview", json={"emails": "ivg@x.gov.tw"}, headers=_bearer(teacher)
        )
        await _invite(client, teacher, cid, "ivg@x.gov.tw")

        link = f"/et/courses/{cid}/learn"
        assert link in preview.json()["body"]
        assert "/et/invite?token=" not in preview.json()["body"], "邀請 token 已隨 #362 移除"
        sent = await db.scalar(
            select(DpEmailLog).where(
                DpEmailLog.recipient == "ivg@x.gov.tw", DpEmailLog.template_code == "COURSE_INVITE"
            )
        )
        assert link in sent.body, "預覽與實寄必須是同一條連結"

    async def test_預覽不加入任何人也不寄信(self, client, db) -> None:
        teacher = await _user(db, "iv_t03", ROLE_TEACHER)
        await _account(db, "ivh@x.gov.tw", user_id="iv_h01")
        cid = await _published_course(client, db, teacher)
        await client.post(
            f"{_COURSES}/{cid}/invitations/preview", json={"emails": "ivh@x.gov.tw"}, headers=_bearer(teacher)
        )
        assert await _enrollments(db, cid) == []
        logs = (await db.execute(select(DpEmailLog).where(DpEmailLog.template_code == "COURSE_INVITE"))).scalars().all()
        assert logs == []


class TestSendInvitations:
    """AC 6：寄出並直接加入課程。"""

    async def test_每筆_email_直接加入課程並寄信(self, client, db) -> None:
        """#362：邀請**即加入**，不再經「待加入」中間狀態。

        原行為是寫一列 `ET_INVITATION` PENDING、等對方點連結才建 `ET_ENROLLMENT`。
        裁示取消那一段的理由：邀請對象限**平台既有帳號**，被邀請者不需要任何動作就能
        在「我的課程」看到課程（`ET_ENROLLMENT` 已建列），所以「待加入」與「已加入」
        在學員端**沒有任何行為差異**，只在教師端多一個要記得去看的頁面——而教師看不到
        被邀請的人出現在學員清單裡，會以為邀請失敗。
        """
        teacher = await _user(db, "iv_t04", ROLE_TEACHER)
        await _account(db, "ivi@x.gov.tw", user_id="iv_i01")
        await _account(db, "ivj@x.gov.tw", user_id="iv_j01")
        cid = await _published_course(client, db, teacher)

        r = await _invite(client, teacher, cid, "ivi@x.gov.tw, ivj@x.gov.tw")

        assert r.status_code == 200, r.text
        # `joined` 與 `mail_failed` **刻意分開**：加入成功而信寄失敗現在是一個真實且
        # 無法補救的組合（待加入清單沒了，教師不能重寄）。合成一個數字會讓教師
        # 以為「沒寄出 ＝ 沒加入」，而那個人其實已經在課程裡了。
        assert r.json() == {"joined": 2, "mail_failed": []}

        rows = await _enrollments(db, cid)
        assert [row.user_id for row in rows] == ["iv_i01", "iv_j01"]
        assert all(row.join_source == SOURCE_EMAIL_INVITE for row in rows)
        assert all(row.is_removed is False for row in rows)

    async def test_每位收件人各收到一封帶自己姓名的信(self, client, db) -> None:
        """加入是主體，信是附帶——但信仍要逐人個人化（範本開頭為「{USER_NAME} 您好：」）。"""
        teacher = await _user(db, "iv_t05", ROLE_TEACHER)
        await _account(db, "ivk@x.gov.tw", user_id="iv_k01")
        await _account(db, "ivl@x.gov.tw", user_id="iv_l01")
        cid = await _published_course(client, db, teacher)

        await _invite(client, teacher, cid, "ivk@x.gov.tw, ivl@x.gov.tw")

        logs = (
            (
                await db.execute(
                    select(DpEmailLog).where(DpEmailLog.template_code == "COURSE_INVITE").order_by(DpEmailLog.recipient)
                )
            )
            .scalars()
            .all()
        )
        assert [log.recipient for log in logs] == ["ivk@x.gov.tw", "ivl@x.gov.tw"]
        assert "姓名iv_k01" in logs[0].body
        assert "姓名iv_l01" in logs[1].body

    async def test_重複邀請同一人不建第二列(self, client, db) -> None:
        """`UQ_ET_ENROLLMENT_USER_COURSE` 為全表唯一——再邀一次必須是 upsert。

        教師重複貼同一批 Email（想「補寄一次」）是最可能的操作，直接 INSERT 會讓他看到
        一個資料庫層級的錯誤。
        """
        teacher = await _user(db, "iv_t06", ROLE_TEACHER)
        await _account(db, "ivm@x.gov.tw", user_id="iv_m01")
        cid = await _published_course(client, db, teacher)
        await _invite(client, teacher, cid, "ivm@x.gov.tw")

        again = await _invite(client, teacher, cid, "ivm@x.gov.tw")

        assert again.status_code == 200, again.text
        assert again.json() == {"joined": 1, "mail_failed": []}
        rows = await _enrollments(db, cid)
        assert len(rows) == 1, "重複邀請不得建第二列"

    async def test_重複邀請不得改寫既有學員的加入日與來源(self, client, db) -> None:
        """🔴 `upsert_enrollment` 的 `DO UPDATE` 必須帶 `WHERE IS_REMOVED`。

        #362 之前這條路徑由**受邀者本人**對**自己那一列**執行（accept），撞鍵幾乎只可能
        是「他被移除過」。改成邀請即加入之後**教師一次可對 50 列執行**，而重貼整份名冊
        「補寄一次」是最可能的操作。

        少了那個 `WHERE`，名冊裡原本由標籤帶入、兩個月前就加入的人會被改成今天加入、
        來源改寫成 `EMAIL_INVITE`——ET03 以 `JOINED_AT` 排序、「加入日」欄位與任何依加入
        時點判讀的報表全部失真，**而且沒有任何訊號**（回應照樣說已加入、稽核照樣記）。

        兩位 code reviewer 獨立指出同一條，故本測試釘死它。
        """
        teacher = await _user(db, "iv_t14", ROLE_TEACHER)
        student = await _account(db, "ivq@x.gov.tw", user_id="iv_q01")
        cid = await _published_course(client, db, teacher)
        # 先以「標籤帶入」的身分在籍，且加入時點在過去
        long_ago = utcnow() - timedelta(days=60)
        db.add(
            EtEnrollment(
                user_id=student,
                course_id=cid,
                join_source="TAG_DEFAULT",
                joined_at=long_ago,
                completion_status="IN_PROGRESS",
                is_removed=False,
                created_user="SYSTEM",
                created_date=long_ago,
                deleted=0,
            )
        )
        await db.flush()

        r = await _invite(client, teacher, cid, "ivq@x.gov.tw")

        assert r.status_code == 200, r.text
        rows = await _enrollments(db, cid)
        assert len(rows) == 1
        await db.refresh(rows[0])
        assert rows[0].join_source == "TAG_DEFAULT", "已在籍者的來源不得被邀請改寫"
        assert rows[0].joined_at == long_ago, "已在籍者的加入日不得被邀請改寫"

    async def test_同一次貼上的重複_email_只加入一次(self, client, db) -> None:
        teacher = await _user(db, "iv_t07", ROLE_TEACHER)
        await _account(db, "ivn@x.gov.tw", user_id="iv_n01")
        cid = await _published_course(client, db, teacher)

        r = await _invite(client, teacher, cid, "IVN@x.gov.tw, ivn@x.gov.tw\nivn@X.gov.tw")

        assert r.json()["joined"] == 1
        logs = (await db.execute(select(DpEmailLog).where(DpEmailLog.template_code == "COURSE_INVITE"))).scalars().all()
        assert len(logs) == 1, "同一人不得收到三封"

    async def test_被移除的學員可經_email_邀請回到課程(self, client, db) -> None:
        """issue 約束 2：Email 邀請是**唯一**能讓被移除者回來的路徑。

        `UQ_ET_ENROLLMENT_USER_COURSE` 為全表唯一、他那一列還在，故必須 upsert；
        INSERT 會撞鍵並讓教師看到一個指向他看不見之列的資料庫錯誤。

        這是 #247 SA Q1 裁示 C 的教師端那一半——標籤帶入（`bulk_enroll_returning`）
        刻意用 `DO NOTHING` **不**把被移除者帶回，只有教師的明確重新邀請可以。
        #362 把觸發時點從「受邀者點連結」提前到「教師按下寄出」，該裁示本身不變。
        """
        teacher = await _user(db, "iv_t13", ROLE_TEACHER)
        invitee = await _user(db, "iv_s06")
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

        r = await _invite(client, teacher, cid, f"{invitee}@edms.local")

        assert r.status_code == 200, r.text
        rows = await _enrollments(db, cid)
        assert len(rows) == 1, "必須 upsert 既有列，不可新增第二列"
        assert rows[0].is_removed is False
        assert rows[0].removed_at is None
        assert rows[0].join_source == SOURCE_EMAIL_INVITE
        assert rows[0].completion_status == "IN_PROGRESS", "回鍋不得重置學習狀態"

    async def test_草稿課程不可邀請(self, client, db) -> None:
        teacher = await _user(db, "iv_t08", ROLE_TEACHER)
        created = await client.post(_COURSES, json={"course_name": "草稿課程"}, headers=_bearer(teacher))
        cid = created.json()["course_id"]
        await _account(db, "ivo@x.gov.tw", user_id="iv_o01")
        r = await _invite(client, teacher, cid, "ivo@x.gov.tw")
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_INVITE_004"

    async def test_非擁有者不可邀請(self, client, db) -> None:
        teacher = await _user(db, "iv_t09", ROLE_TEACHER)
        other = await _user(db, "iv_t10", ROLE_TEACHER)
        cid = await _published_course(client, db, teacher)
        await _account(db, "ivp@x.gov.tw", user_id="iv_p01")
        r = await _invite(client, other, cid, "ivp@x.gov.tw")
        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_COURSE_002"


class TestDisabledAccountIsRejected:
    """停用帳號不可被邀請（#347 第一項，隨 #362 一併處理）。

    `DP_USER.DELETED` **從來沒有任何 code path 會設成 1**，停用一律走 `STATUS`——所以
    `recipients_by_emails` 的 `DELETED = 0` 對停用者完全無效。

    #362 之前這個缺口的後果有限：停用者收到信也登不進來（`core/auth.py` 每請求查
    `STATUS`），他只會停在「待加入」清單上讓教師看見並撤回。取消待加入之後他會被**直接
    寫進 `ET_ENROLLMENT`**，而 ET03 清單與週報只濾 `IS_REMOVED` / `DELETED`——一個永遠
    不可能完課的帳號會永久坐在完訓率的分母裡，還會出現在具名 CSV 中。
    """

    async def _disabled(self, db, email: str, user_id: str) -> str:
        uid = await _account(db, email, user_id=user_id)
        await db.execute(update(DpUser).where(DpUser.user_id == uid).values(status="DISABLED"))
        await db.flush()
        return uid

    async def test_停用帳號一律擋下且不加入任何人(self, client, db) -> None:
        teacher = await _user(db, "dis_t01", ROLE_TEACHER)
        await _account(db, "active@x.gov.tw", user_id="dis_a01")
        await self._disabled(db, "left@x.gov.tw", "dis_d01")
        cid = await _published_course(client, db, teacher)

        r = await _invite(client, teacher, cid, "active@x.gov.tw, left@x.gov.tw")

        assert r.status_code == 422, r.text
        body = r.json()
        assert body["error_code"] == "ET_INVITE_008"
        assert body["disabled_emails"] == ["left@x.gov.tw"], "須指出是哪幾筆"
        # 全批擋下：不可只加入正常的那幾位（教師會以為全部都寄出去了）
        assert await _enrollments(db, cid) == []

    async def test_與查無帳號分碼(self, client, db) -> None:
        """🔴 不可共用 `ET_INVITE_005`。

        「請管理者建帳號」對一個**已經有帳號**的人是錯的指示，教師照做會得到一個重複
        帳號。兩者的下一步完全相反，故必須分碼。
        """
        teacher = await _user(db, "dis_t02", ROLE_TEACHER)
        await self._disabled(db, "left2@x.gov.tw", "dis_d02")
        cid = await _published_course(client, db, teacher)

        r = await _invite(client, teacher, cid, "left2@x.gov.tw")

        assert r.json()["error_code"] == "ET_INVITE_008"
        assert "尚未建立" not in r.json()["error_message"], "不可說成查無帳號"

    async def test_鎖定中的帳號仍可被邀請(self, client, db) -> None:
        """⚠️ 只擋「停用」，**不擋「鎖定中」**。

        `LOCKED_UNTIL` 是連續登入失敗的暫時性鎖，幾分鐘後自動解除。因為某人剛才打錯
        密碼就拒絕教師邀請他，教師完全無從理解——故判定用 `is_account_disabled()`
        而非 `is_account_usable()`。少了這條，日後有人「順手改成更嚴格」不會被發現。
        """
        teacher = await _user(db, "dis_t03", ROLE_TEACHER)
        locked = await _account(db, "locked@x.gov.tw", user_id="dis_l01")
        await db.execute(
            update(DpUser).where(DpUser.user_id == locked).values(locked_until=utcnow() + timedelta(minutes=15))
        )
        await db.flush()
        cid = await _published_course(client, db, teacher)

        r = await _invite(client, teacher, cid, "locked@x.gov.tw")

        assert r.status_code == 200, r.text
        assert r.json()["joined"] == 1


class TestInviteAudit:
    """把人加進課程必須**逐人**可追溯（Security Review MEDIUM-2）。"""

    async def test_每位受邀者各一列稽核且不含個資(self, client, db) -> None:
        """「把某人加進課程」不需要他同意，他卻會因此出現在具名的問卷結果與完訓統計裡。

        事後問「誰把我加進去的」，彙總列（`target_id = 課程`）答不出來。同模組的**移除**
        學員早就是逐人一列——減人可追溯、加人不可追溯，那個不對稱正好反了。

        ⚠️ 稽核**必須在加入迴圈結束後才寫**：`log_action` 會取一把全平台單一 key 的交易級
        advisory lock，在逐筆迴圈裡呼叫會讓整批的 DB 往返與寄信都在持鎖狀態下進行，
        期間所有寫稽核的動作（含登入）全平台排隊。本條只驗結果，持鎖窗由 code review 守。
        """
        teacher = await _user(db, "aud_t01", ROLE_TEACHER)
        await _account(db, "auda@x.gov.tw", user_id="aud_a01")
        await _account(db, "audb@x.gov.tw", user_id="aud_b01")
        cid = await _published_course(client, db, teacher)

        await _invite(client, teacher, cid, "auda@x.gov.tw, audb@x.gov.tw")

        logs = (
            (
                await db.execute(
                    select(DpAuditLog).where(DpAuditLog.func_name == "ET-ENROLLMENT").order_by(DpAuditLog.log_id)
                )
            )
            .scalars()
            .all()
        )
        assert [log.target_id for log in logs] == [f"{cid}:aud_a01", f"{cid}:aud_b01"]
        for log in logs:
            assert "@" not in (log.description or ""), "description 不得含 Email"
            assert "姓名" not in (log.description or ""), "description 不得含姓名"


class TestUnknownEmailIsRejected:
    """SA 裁示：Email 邀請只收既有 EDMS 使用者。

    教師是用貼的，打錯一個字就會把課程資訊寄給系統外的陌生人——而寄信結果只記「排入
    佇列」，退信不會反映在任何地方。#362 移除待加入清單後，連事後查看的位置都沒有了，
    所以這道檢核同時是「邀請即加入」得以成立的前提（見 service 模組 docstring）。
    """

    async def test_寄送時查無帳號一律擋下且不加入任何人(self, client, db) -> None:
        teacher = await _user(db, "un_t01", ROLE_TEACHER)
        await _account(db, "known@x.gov.tw", user_id="un_k01")
        cid = await _published_course(client, db, teacher)

        r = await _invite(client, teacher, cid, "known@x.gov.tw, typo@x.gov.tw")

        assert r.status_code == 422
        body = r.json()
        assert body["error_code"] == "ET_INVITE_005"
        assert body["unknown_emails"] == ["typo@x.gov.tw"], "須指出是哪幾筆"
        # 全批擋下：不可只加入有帳號的那幾位（教師會以為全部都寄出去了）
        assert await _enrollments(db, cid) == []

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
