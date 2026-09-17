"""SCHET001 週報與每週未看提醒（T146 / T147 / US14 / #325）。

## 一律篩 `DP_EMAIL_LOG.STATUS='PENDING'`

params key 與範本佔位對不上時，平台 `_SafeFormatter` 拋 `KeyError` → 該封記為
`FAILED`、`queued_count=0`，**且不外拋**。只查「有沒有列」會讓「寄出一封空信」
看起來與成功無異。

## 收件人推導是本檔的重心

| 規則 | 漏掉的表徵 |
|---|---|
| 兼任教師＋管理者只收管理者版 | 同一人同一天收到兩封主旨相同的信 |
| 教師角色已停用者不收 | 已離職者持續每週收到含全班姓名的週報 |
| 名下無開放中課程者不收 | 收到一封課程列表為空的信 |
| 週提醒僅寄進度 0% 者 | 已開始 / 已完課者被催，造成提醒疲勞（客戶明確要求避免）|
"""

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.notify.models import DpEmailLog, DpNotifyTemplate
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.constants import ITEM_MATERIAL, ROLE_ADMIN, ROLE_STUDENT, ROLE_TEACHER, SOURCE_INVITATION_CODE
from app.et.progress.models import EtEnrollment
from app.et.roles.models import EtUserRole
from app.et.schedules.weekly_service import EtWeeklyReportService

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str, *roles: str) -> str:
    """建使用者並賦予任意多個 ET 角色（角色可多重指派）。"""
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
    for role in roles:
        db.add(
            EtUserRole(user_id=user_id, role=role, is_active=True, created_user="SYSTEM", created_date=now, deleted=0)
        )
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


async def _enroll(db, *, user_id: str, course_id: int) -> None:
    now = utcnow()
    db.add(
        EtEnrollment(
            user_id=user_id,
            course_id=course_id,
            join_source=SOURCE_INVITATION_CODE,
            joined_at=now,
            completion_status="NOT_STARTED",
            is_removed=False,
            created_user=user_id,
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()


async def _course(client, db, teacher: str, slug: str) -> dict:
    """該教師擁有的一門開放中課程（1 教材）。"""
    created = await client.post(
        _COURSES,
        json={
            "course_name": f"週報課程{slug}",
            "open_start_at": "2026-09-01T00:00:00Z",
            "open_end_at": "2027-09-30T00:00:00Z",
        },
        headers=_bearer(teacher),
    )
    assert created.status_code == 201, created.text
    cid = created.json()["course_id"]

    tag_id = await _tag(db, f"標籤{cid}")
    db.add(EtCourseTag(course_id=cid, tag_id=tag_id, created_user="SYSTEM", created_date=utcnow(), deleted=0))
    await db.flush()

    ch = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(teacher))
    assert ch.status_code == 201, ch.text
    item = await client.post(
        f"/api/et/chapters/{ch.json()['chapter_id']}/items",
        json={"item_type": ITEM_MATERIAL, "title": "教材"},
        headers=_bearer(teacher),
    )
    assert item.status_code == 201, item.text
    published = await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(teacher))
    assert published.status_code == 200, published.text
    return {"course_id": cid, "item_id": item.json()["item_id"]}


async def _mails(db, template_code: str) -> list[DpEmailLog]:
    """**只取 `PENDING`**——`FAILED` 代表渲染出空信，不可當成寄出成功。"""
    rows = await db.scalars(
        select(DpEmailLog).where(DpEmailLog.template_code == template_code, DpEmailLog.status == "PENDING")
    )
    return list(rows.all())


async def _recipients(db, template_code: str) -> set[str]:
    return {m.recipient for m in await _mails(db, template_code)}


class TestWeeklyReportRecipients:
    async def test_教師收到自己課程之週報(self, client, db) -> None:
        teacher = await _user(db, "wr_t1", ROLE_TEACHER)
        await _course(client, db, teacher, "r1")

        reports, _ = await EtWeeklyReportService().send_weekly(db)

        assert reports == 1
        assert await _recipients(db, "WEEKLY_REPORT") == {"wr_t1@edms.local"}

    async def test_教師週報內文不含他人課程與學員姓名(self, client, db) -> None:
        """只斷言收件人集合是不夠的——`_send_reports` 的集合運算若寫歪（例如把 `facts`
        全給每個 owner），收件人仍然只有他一個，但**信的內容多出別人的學員姓名**，
        而週報內文會隨轉寄離開任何存取控制。"""
        mine = await _user(db, "wr_m1", ROLE_TEACHER)
        theirs = await _user(db, "wr_o1", ROLE_TEACHER)
        my_course = await _course(client, db, mine, "own")
        their_course = await _course(client, db, theirs, "oth")
        my_student = await _user(db, "wr_s_mine", ROLE_STUDENT)
        their_student = await _user(db, "wr_s_theirs", ROLE_STUDENT)
        await _enroll(db, user_id=my_student, course_id=my_course["course_id"])
        await _enroll(db, user_id=their_student, course_id=their_course["course_id"])

        await EtWeeklyReportService().send_weekly(db)

        body = next(m.body for m in await _mails(db, "WEEKLY_REPORT") if m.recipient == "wr_m1@edms.local")
        assert "週報課程own" in body
        assert "測試wr_s_mine" not in body, "信件內文不得含任何學員姓名（含自己課程的）"
        assert "週報課程oth" not in body, "教師的週報不得含他人課程"
        assert "測試wr_s_theirs" not in body, "教師的週報不得含他人課程的學員姓名"

    async def test_管理者收到全域週報(self, client, db) -> None:
        teacher = await _user(db, "wr_t2", ROLE_TEACHER)
        await _user(db, "wr_a2", ROLE_ADMIN)
        await _course(client, db, teacher, "r2")

        await EtWeeklyReportService().send_weekly(db)

        assert await _recipients(db, "WEEKLY_REPORT") == {"wr_t2@edms.local", "wr_a2@edms.local"}

    async def test_兼任教師與管理者者只收一封(self, client, db) -> None:
        """SA Q3 裁示 A：全域版已完全涵蓋教師版。同一次排程對同一人寄兩封主旨相同的信，
        收件者會直接視為系統異常。"""
        both = await _user(db, "wr_both", ROLE_TEACHER, ROLE_ADMIN)
        await _course(client, db, both, "r3")

        reports, _ = await EtWeeklyReportService().send_weekly(db)

        assert reports == 1
        assert len(await _mails(db, "WEEKLY_REPORT")) == 1

    async def test_教師角色已停用者不收(self, client, db) -> None:
        """教師角色被停用是離職 / 轉調的第一步，而 `OWNER_ID` 是不變的——只看擁有者
        會讓已離職者持續收到含全班姓名的週報。該課程仍在管理者的全域週報內。"""
        teacher = await _user(db, "wr_t4", ROLE_TEACHER)
        await _user(db, "wr_a4", ROLE_ADMIN)
        await _course(client, db, teacher, "r4")
        await db.execute(update(EtUserRole).where(EtUserRole.user_id == teacher).values(is_active=False))
        await db.flush()

        await EtWeeklyReportService().send_weekly(db)

        assert await _recipients(db, "WEEKLY_REPORT") == {"wr_a4@edms.local"}

    async def test_DP帳號已停用者不收(self, client, db) -> None:
        """ET 角色列還在、但 `DP_USER.STATUS` 已非 `ACTIVE`。

        `disable_idle_accounts` 每日把閒置逾 90 天的帳號設為 `DISABLED`，而它**完全不碰
        `ET_USER_ROLE`**。`core/auth.py` 對非 `ACTIVE` 帳號一律 403——也就是說停用擋住了
        API、卻擋不住信：離職者的信箱會無限期每週收到全站統計與學員姓名，而郵件是當時
        唯一還通的管道。
        """
        teacher = await _user(db, "wr_t7", ROLE_TEACHER)
        disabled_admin = await _user(db, "wr_a7", ROLE_ADMIN)
        await _course(client, db, teacher, "r7")
        await db.execute(update(DpUser).where(DpUser.user_id == disabled_admin).values(status="DISABLED"))
        await db.flush()

        await EtWeeklyReportService().send_weekly(db)

        assert await _recipients(db, "WEEKLY_REPORT") == {"wr_t7@edms.local"}

    async def test_名下無開放中課程之教師不收(self, client, db) -> None:
        """沿用 `COURSE_INVITE_DIGEST` 的「空清單不寄信」——不寄一封列表為空的信。"""
        await _user(db, "wr_idle", ROLE_TEACHER)
        owner = await _user(db, "wr_t5", ROLE_TEACHER)
        await _course(client, db, owner, "r5")

        await EtWeeklyReportService().send_weekly(db)

        assert await _recipients(db, "WEEKLY_REPORT") == {"wr_t5@edms.local"}

    async def test_無任何開放中課程時完全不寄(self, client, db) -> None:
        await _user(db, "wr_a6", ROLE_ADMIN)
        await _user(db, "wr_t6", ROLE_TEACHER)

        reports, reminds = await EtWeeklyReportService().send_weekly(db)

        assert (reports, reminds) == (0, 0)


class TestWeeklyRemind:
    async def test_僅寄進度0百分比之學員(self, client, db) -> None:
        teacher = await _user(db, "wm_t1", ROLE_TEACHER)
        ctx = await _course(client, db, teacher, "m1")
        zero = await _user(db, "wm_zero", ROLE_STUDENT)
        started = await _user(db, "wm_started", ROLE_STUDENT)
        for u in (zero, started):
            await _enroll(db, user_id=u, course_id=ctx["course_id"])
        viewed = await client.post(f"/api/et/items/{ctx['item_id']}/viewed", headers=_bearer(started))
        assert viewed.status_code == 200, viewed.text

        _, reminds = await EtWeeklyReportService().send_weekly(db)

        assert reminds == 1
        assert await _recipients(db, "WEEKLY_REMIND") == {"wm_zero@edms.local"}

    async def test_一人多課彙整為一封(self, client, db) -> None:
        """FR-ET-US14-05 明訂「一人一信彙整」——逐課一封會讓同一人同時收到好幾封。"""
        teacher = await _user(db, "wm_t2", ROLE_TEACHER)
        first = await _course(client, db, teacher, "m2a")
        second = await _course(client, db, teacher, "m2b")
        student = await _user(db, "wm_multi", ROLE_STUDENT)
        await _enroll(db, user_id=student, course_id=first["course_id"])
        await _enroll(db, user_id=student, course_id=second["course_id"])

        _, reminds = await EtWeeklyReportService().send_weekly(db)

        assert reminds == 1
        mails = await _mails(db, "WEEKLY_REMIND")
        assert len(mails) == 1
        assert "週報課程m2a" in mails[0].body and "週報課程m2b" in mails[0].body

    async def test_已移除學員不寄(self, client, db) -> None:
        teacher = await _user(db, "wm_t3", ROLE_TEACHER)
        ctx = await _course(client, db, teacher, "m3")
        gone = await _user(db, "wm_gone", ROLE_STUDENT)
        await _enroll(db, user_id=gone, course_id=ctx["course_id"])
        await db.execute(update(EtEnrollment).where(EtEnrollment.user_id == gone).values(is_removed=True))
        await db.flush()

        _, reminds = await EtWeeklyReportService().send_weekly(db)

        assert reminds == 0

    async def test_已到期課程不寄提醒(self, client, db) -> None:
        from app.et.course.models import EtCourse

        teacher = await _user(db, "wm_t4", ROLE_TEACHER)
        ctx = await _course(client, db, teacher, "m4")
        student = await _user(db, "wm_late", ROLE_STUDENT)
        await _enroll(db, user_id=student, course_id=ctx["course_id"])
        await db.execute(
            update(EtCourse)
            .where(EtCourse.course_id == ctx["course_id"])
            .values(open_end_at=utcnow() - timedelta(days=1))
        )
        await db.flush()

        _, reminds = await EtWeeklyReportService().send_weekly(db)

        assert reminds == 0


class TestReportContent:
    async def test_週報內文含摘要與CSV下載連結(self, client, db) -> None:
        teacher = await _user(db, "rc_t1", ROLE_TEACHER)
        ctx = await _course(client, db, teacher, "c1")
        student = await _user(db, "rc_s1", ROLE_STUDENT)
        await _enroll(db, user_id=student, course_id=ctx["course_id"])

        await EtWeeklyReportService().send_weekly(db)

        body = (await _mails(db, "WEEKLY_REPORT"))[0].body
        assert "週報課程c1" in body
        assert "平均進度" in body and "完課率" in body and "距訖止" in body
        assert "/et/reports/weekly" in body
        # 首次統計無前次快照 → 與上週比較顯示「—」（AC 5）
        assert "與上週 —" in body
        # 信件內文**不得**出現任何學員姓名——它會隨轉寄離開所有存取控制
        assert "測試rc_s1" not in body


class TestTemplateDisabled:
    """AC 3（ET-17 / #353）：停用一支範本不得波及同一次執行的其他產出。

    ## 為什麼這不是「重複測平台的 IS_ACTIVE 檢查」

    「停用 → 不寄」的判斷在平台 `send_email` **一處**，測五個寄信點只是測同一行五次。
    本 class 驗的是 AC 3 的**後半句**——「但觸發事件照常運作」——而那一半在每個寄信點
    都不一樣，SCHET001 尤其特別：

    `send_weekly()` 在**同一次呼叫、同一個 session** 裡依序做兩件事：

    ```python
    facts = await self._collect(db, now)
    reports = await self._send_reports(db, facts)   # WEEKLY_REPORT
    reminds = await self._send_reminds(db, facts)   # WEEKLY_REMIND
    ```

    **順序耦合是真的風險**：若 `_send_reports` 因範本停用而拋錯，`_send_reminds` 連跑都
    不會跑——管理者停用了週報，學員的未看提醒跟著一起消失，而沒有任何地方會說。

    ## 統計快照為什麼不在本 class 驗

    `handlers.weekly_job` 對快照與寄信各開**獨立的 `AsyncSessionLocal`**
    （`handlers.py:46-50`），快照在寄信之前就已提交。寄信階段無論怎麼失敗都**不可能**
    回滾快照——那是結構保證，不是行為，寫成測試只會測到 session 的語意而非本模組的邏輯。
    真正會被寄信影響的是「同一次 `send_weekly` 內的另一種信」，也就是下面兩條。
    """

    @staticmethod
    async def _disable(db, template_code: str) -> None:
        """停用範本並**提交**前置資料。

        ⚠️ `commit()` 不是可有可無的。`_send_reports` 在「沒寄成」時會呼叫
        `await db.rollback()`（`weekly_service.py:153`），而整合測試的 session 以 savepoint
        併入外層交易——那個 rollback 會把**測試自己剛建的學員與選課列一起回滾掉**，
        於是後面的 `_send_reminds` 查不到任何人，`reminds` 變成 0。

        那會讓「停用週報連帶吃掉未看提醒」這個結論**看起來成立**，但它其實是測試環境
        的產物：正式環境裡 `_collect` 之前的資料早已提交，rollback 只丟掉未提交的工作。
        先 commit 把前置資料壓到 savepoint 之下，才量得到真正的耦合。
        """
        await db.execute(
            update(DpNotifyTemplate)
            .where(DpNotifyTemplate.module == "ET", DpNotifyTemplate.template_code == template_code)
            .values(is_enabled=False)
        )
        await db.commit()

    async def test_週報範本停用時未看提醒照常寄出(self, client, db) -> None:
        """停用 `WEEKLY_REPORT` → 週報 0 封，但**未看提醒不受影響**。"""
        teacher = await _user(db, "td_t1", ROLE_TEACHER)
        ctx = await _course(client, db, teacher, "td1")
        await _enroll(db, user_id=await _user(db, "td_s1", ROLE_STUDENT), course_id=ctx["course_id"])
        await self._disable(db, "WEEKLY_REPORT")

        reports, reminds = await EtWeeklyReportService().send_weekly(db)

        assert reports == 0, "範本已停用，不該寄出週報"
        assert await _mails(db, "WEEKLY_REPORT") == []
        assert reminds == 1, "停用週報不得連帶吃掉未看提醒——兩者在同一次呼叫裡依序執行"
        assert await _recipients(db, "WEEKLY_REMIND") == {"td_s1@edms.local"}

    async def test_未看提醒範本停用時週報照常寄出(self, client, db) -> None:
        """反向：停用 `WEEKLY_REMIND` → 提醒 0 封，週報不受影響。

        與上一條互為對照。只驗單向的話，把兩支寄信實作成「共用一個 early return」
        仍會讓其中一條綠。
        """
        teacher = await _user(db, "td_t2", ROLE_TEACHER)
        ctx = await _course(client, db, teacher, "td2")
        await _enroll(db, user_id=await _user(db, "td_s2", ROLE_STUDENT), course_id=ctx["course_id"])
        await self._disable(db, "WEEKLY_REMIND")

        reports, reminds = await EtWeeklyReportService().send_weekly(db)

        assert reminds == 0, "範本已停用，不該寄出未看提醒"
        assert await _mails(db, "WEEKLY_REMIND") == []
        assert reports == 1, "停用未看提醒不得連帶吃掉週報"
        assert await _recipients(db, "WEEKLY_REPORT") == {"td_t2@edms.local"}

    async def test_兩支範本皆停用時不拋例外(self, client, db) -> None:
        """整支 job 不得因「管理者把 ET 的週信全關了」而記成 FAILED。

        `weekly_job` 對 `send_weekly` 的例外沒有攔截——拋出去會讓該次排程在
        `DP_SCHEDULE` 的執行歷程記成 `FAILED`，管理者看到紅字後會去找一個不存在的 bug，
        而實際上系統完全照他的設定在運作。
        """
        teacher = await _user(db, "td_t3", ROLE_TEACHER)
        ctx = await _course(client, db, teacher, "td3")
        await _enroll(db, user_id=await _user(db, "td_s3", ROLE_STUDENT), course_id=ctx["course_id"])
        await self._disable(db, "WEEKLY_REPORT")
        await self._disable(db, "WEEKLY_REMIND")

        reports, reminds = await EtWeeklyReportService().send_weekly(db)

        assert (reports, reminds) == (0, 0)
