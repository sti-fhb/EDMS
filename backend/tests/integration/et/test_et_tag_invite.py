"""發布課程時依受訓單位標籤自動帶入學員（US3 FR-ET-US3-12 前半 / #247 追加）。

實測回饋：課程掛了「護理師」標籤發布出去，具該標籤的學員卻沒被帶進課程——受訓單位
標籤在發布流程裡等於沒有作用。本檔釘住補上後的行為。
"""

import pytest
from sqlalchemy import select, update

from app.core.auth import create_access_token
from app.core.operator import OperatorInfo
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.catalog.models import EtTag
from app.et.constants import ROLE_STUDENT, ROLE_TEACHER, SOURCE_TAG_DEFAULT
from app.et.enrollment.tag_invite import EtTagInviteRepository
from app.et.progress.models import EtEnrollment
from app.et.roles.models import EtUserRole
from tests.integration.et._tag_pairs import all_roles_id, all_units_id, new_tag, pair_course, pair_user, tag_id

pytestmark = pytest.mark.integration

_repo = EtTagInviteRepository()


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str, role: str = ROLE_STUDENT) -> str:
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
    db.add(EtUserRole(user_id=user_id, role=role, is_active=True, created_user="SYSTEM", created_date=now, deleted=0))
    await db.flush()
    return user_id


async def _new_tag(db, name: str) -> int:
    return await new_tag(db, name)


async def _tag_course(db, course_id: int, role_id: int) -> None:
    """#538 之前「課程只掛職位」＝現在的 `(全單位, 職位)`。"""
    await pair_course(db, course_id, role_id)


async def _tag_user(db, user_id: str, role_id: int) -> None:
    """#538 之前「使用者只掛職位」＝現在的 `(單位未指定, 職位)`。"""
    await pair_user(db, user_id, role_id)


async def _course(client, teacher: str, name: str = "採血作業教育") -> int:
    r = await client.post("/api/et/courses", json={"course_name": name}, headers=_bearer(teacher))
    assert r.status_code == 201, r.text
    return r.json()["course_id"]


async def _enrolled(db, course_id: int) -> list[EtEnrollment]:
    rows = await db.scalars(select(EtEnrollment).where(EtEnrollment.course_id == course_id, EtEnrollment.deleted == 0))
    return list(rows)


class TestTargetResolution:
    async def test_只帶入掛該標籤且具學員角色者(self, client, db) -> None:
        teacher = await _user(db, "t_tag01", ROLE_TEACHER)
        nurse = await _user(db, "s_tag01")
        clerk = await _user(db, "s_tag02")
        cid = await _course(client, teacher)
        nurse_tag = await _new_tag(db, "護理師_tag01")
        clerk_tag = await _new_tag(db, "行政_tag01")
        await _tag_course(db, cid, nurse_tag)
        await _tag_user(db, nurse, nurse_tag)
        await _tag_user(db, clerk, clerk_tag)

        assert await _repo.target_user_ids(db, cid) == [nurse]

    async def test_全體標籤展開為所有學員(self, client, db) -> None:
        """`IS_ALL` 不看使用者有沒有實際掛上那個標籤。

        否則「全體」就只是一個名字叫全體的普通標籤——沒有人會特地去幫每位使用者掛它。
        """
        teacher = await _user(db, "t_tag02", ROLE_TEACHER)
        a = await _user(db, "s_tag03")
        b = await _user(db, "s_tag04")
        cid = await _course(client, teacher)
        await _tag_course(db, cid, await all_roles_id(db))

        targets = await _repo.target_user_ids(db, cid)

        assert a in targets and b in targets

    async def test_未掛標籤之課程不帶入任何人(self, client, db) -> None:
        teacher = await _user(db, "t_tag03", ROLE_TEACHER)
        await _user(db, "s_tag05")
        cid = await _course(client, teacher)

        assert await _repo.target_user_ids(db, cid) == []

    async def test_停用之學員角色不帶入(self, client, db) -> None:
        """角色指派可被管理者停用（`load_et_roles` 只取 `IS_ACTIVE=true`）。"""
        teacher = await _user(db, "t_tag04", ROLE_TEACHER)
        inactive = await _user(db, "s_tag06")
        cid = await _course(client, teacher)
        tag_id = await _new_tag(db, "護理師_tag04")
        await _tag_course(db, cid, tag_id)
        await _tag_user(db, inactive, tag_id)
        await db.execute(update(EtUserRole).where(EtUserRole.user_id == inactive).values(is_active=False))
        await db.flush()

        assert await _repo.target_user_ids(db, cid) == []


class TestBulkEnroll:
    async def test_批次帶入寫入標籤來源(self, client, db) -> None:
        teacher = await _user(db, "t_tag05", ROLE_TEACHER)
        student = await _user(db, "s_tag07")
        cid = await _course(client, teacher)
        tag_id = await _new_tag(db, "護理師_tag05")
        await _tag_course(db, cid, tag_id)
        await _tag_user(db, student, tag_id)

        created = await _repo.bulk_enroll(db, cid, [student], operator=OperatorInfo(user_id=teacher))

        assert created == 1
        rows = await _enrolled(db, cid)
        assert len(rows) == 1
        assert rows[0].join_source == SOURCE_TAG_DEFAULT
        assert rows[0].is_removed is False

    async def test_已在課程中者不重複建列(self, client, db) -> None:
        """課程可重複觸發（再開課、標籤異動）——`UQ_ET_ENROLLMENT_USER_COURSE` 是
        全表唯一，不 upsert 會直接撞鍵。"""
        teacher = await _user(db, "t_tag06", ROLE_TEACHER)
        student = await _user(db, "s_tag08")
        cid = await _course(client, teacher)
        op = OperatorInfo(user_id=teacher)

        assert await _repo.bulk_enroll(db, cid, [student], operator=op) == 1
        assert await _repo.bulk_enroll(db, cid, [student], operator=op) == 0

        assert len(await _enrolled(db, cid)) == 1

    async def test_被移除之學員不會被標籤帶回來(self, client, db) -> None:
        """#247 SA Q1 裁示 C 的延伸。

        若標籤帶入把 `IS_REMOVED` 翻回 false，教師移除完只要有人再發布一次就前功盡棄，
        **而且沒有任何人會發現**。要讓被移除者回來須由教師明確重新邀請（`ET-8`）。
        """
        teacher = await _user(db, "t_tag07", ROLE_TEACHER)
        student = await _user(db, "s_tag09")
        cid = await _course(client, teacher)
        op = OperatorInfo(user_id=teacher)
        await _repo.bulk_enroll(db, cid, [student], operator=op)
        await db.execute(
            update(EtEnrollment)
            .where(EtEnrollment.user_id == student, EtEnrollment.course_id == cid)
            .values(is_removed=True, removed_at=utcnow())
        )
        await db.flush()

        created = await _repo.bulk_enroll(db, cid, [student], operator=op)

        assert created == 0
        rows = await _enrolled(db, cid)
        assert len(rows) == 1
        assert rows[0].is_removed is True, "被移除狀態必須原樣保留"

    async def test_空清單不炸(self, client, db) -> None:
        teacher = await _user(db, "t_tag08", ROLE_TEACHER)
        cid = await _course(client, teacher)

        assert await _repo.bulk_enroll(db, cid, [], operator=OperatorInfo(user_id=teacher)) == 0


class TestOwnerIsNeverEnrolledIntoOwnCourse:
    """#520：課程擁有者不得被標籤帶入**自己的**課程。

    ## 排除做在 `bulk_enroll_returning`——三條路徑的唯一匯流點

    | 路徑 | 呼叫端 | 本檔是否涵蓋 |
    |---|---|---|
    | 發布時依課程標籤帶入 | `course/publish_service` | ✅ 本組 |
    | 已發布課程新增標籤（`FR-ET-US8-04`）| `course/service.add_tags` | ✅ 本組 |
    | 貼標追溯（`FR-ET-US8-05`）| `roles/assign_service` | `test_et_tag_backfill.py` |

    ⚠️ **`target_user_ids` 仍然會回出擁有者**——這是刻意的。那支的語意是「掛這些標籤
    的學員有誰」，擁有者確實掛著；排除是**帶入時**的規則，不是解析時的。兩者混在一起
    會讓「他掛了這個標籤嗎」這個問題在不同呼叫端得到不同答案。
    """

    async def test_擁有者不會被帶入自己的課程(self, client, db) -> None:
        """🔴 擁有者身上有 `ET_STUDENT` 角色（建立帳號時自動授予，#89），所以他本來就在
        標籤帶入的母體裡——那正是 #520 的成因。"""
        teacher = await _user(db, "t_own10", ROLE_TEACHER)
        db.add(
            EtUserRole(
                user_id=teacher,
                role=ROLE_STUDENT,
                is_active=True,
                created_user="SYSTEM",
                created_date=utcnow(),
                deleted=0,
            )
        )
        await db.flush()
        cid = await _course(client, teacher)
        tag_id = await _new_tag(db, "護理師_own10")
        await _tag_course(db, cid, tag_id)
        await _tag_user(db, teacher, tag_id)

        created = await _repo.bulk_enroll_returning(db, cid, [teacher], operator=OperatorInfo(user_id=teacher))

        assert created == [], "擁有者被帶入了自己的課程（#520）"
        assert await _enrolled(db, cid) == []

    async def test_同一次帶入仍把其他學員加進去(self, client, db) -> None:
        """🔴 與上一條**成對**：少了它，把 `bulk_enroll_returning` 改成「一律不加入」
        也會通過上一條，而那會讓整個標籤帶入功能靜默失效。"""
        teacher = await _user(db, "t_own11", ROLE_TEACHER)
        student = await _user(db, "s_own11")
        db.add(
            EtUserRole(
                user_id=teacher,
                role=ROLE_STUDENT,
                is_active=True,
                created_user="SYSTEM",
                created_date=utcnow(),
                deleted=0,
            )
        )
        await db.flush()
        cid = await _course(client, teacher)

        created = await _repo.bulk_enroll_returning(db, cid, [teacher, student], operator=OperatorInfo(user_id=teacher))

        assert created == [student], "擁有者應被濾掉、其他學員應照常加入"

    async def test_擁有者在他人課程仍可被帶入(self, client, db) -> None:
        """🔴 第三條成對斷言：排除的判準是「他是**這門課**的擁有者」，不是「他是教師」。

        教師修別人開的課是合法的。
        """
        owner = await _user(db, "t_own12", ROLE_TEACHER)
        other_teacher = await _user(db, "t_oth12", ROLE_TEACHER)
        db.add(
            EtUserRole(
                user_id=other_teacher,
                role=ROLE_STUDENT,
                is_active=True,
                created_user="SYSTEM",
                created_date=utcnow(),
                deleted=0,
            )
        )
        await db.flush()
        cid = await _course(client, owner)

        created = await _repo.bulk_enroll_returning(db, cid, [other_teacher], operator=OperatorInfo(user_id=owner))

        assert created == [other_teacher], "他人課程的帶入被誤擋了"


_SONGSHAN = "國防醫學院三軍總醫院松山分院"
_TSGH = "國防醫學院三軍總醫院"
_MSB = "國防部軍醫局"


class TestPairMatching:
    """#538：課程與使用者皆為 `(單位, 職位)` 配對，判定規則沿用 #437。

    ```
    帶入 ⟺ ∃ 課程配對 (cu, cp)、∃ 使用者配對 (uu, up)：
            (cu 為全單位 OR cu = uu) AND (cp 為全體 OR cp = up)
    ```

    單位與職位一律用 migration seed 的資料——那正是正式機上會有的值，且「全單位」「全體」
    以 `IS_ALL` 判定，不以名稱判定。
    """

    @pytest.mark.parametrize(
        ("course_unit", "course_role", "expected"),
        [
            (_SONGSHAN, "護理師", True),  # 完全相符
            (_SONGSHAN, "全體", True),  # 松山分院全員
            ("全單位", "護理師", True),  # 所有單位的護理師
            ("全單位", "全體", True),  # 全部學員
            (_SONGSHAN, "行政人員", False),  # 職位不符
            (_TSGH, "護理師", False),  # 單位不符——不展開階層：三總不涵蓋松山分院
        ],
    )
    async def test_六組單筆配對之帶入(self, client, db, course_unit, course_role, expected) -> None:
        """#437 的六組驗收範例，改以「是否被帶入課程」驗證。使用者為 `(松山分院, 護理師)`。"""
        teacher = await _user(db, "t_pr01", ROLE_TEACHER)
        nurse = await _user(db, "s_pr01")
        cid = await _course(client, teacher)
        await pair_user(db, nurse, await tag_id(db, "護理師"), await tag_id(db, _SONGSHAN))
        await pair_course(db, cid, await tag_id(db, course_role), await tag_id(db, course_unit))

        assert (nurse in await _repo.target_user_ids(db, cid)) is expected

    async def test_多筆配對不帶入交叉組合(self, client, db) -> None:
        """#437 否決「單位集 ∧ 職位集」的理由：課程開給「軍醫局的護理師」與「三總的行政人員」
        時，**軍醫局的行政人員**與**三總的護理師**不得被帶入。"""
        teacher = await _user(db, "t_pr02", ROLE_TEACHER)
        cid = await _course(client, teacher)
        nurse, clerk = await tag_id(db, "護理師"), await tag_id(db, "行政人員")
        msb, tsgh = await tag_id(db, _MSB), await tag_id(db, _TSGH)
        await pair_course(db, cid, nurse, msb)
        await pair_course(db, cid, clerk, tsgh)
        want_a = await _user(db, "s_pr02a")
        want_b = await _user(db, "s_pr02b")
        cross_a = await _user(db, "s_pr02c")
        cross_b = await _user(db, "s_pr02d")
        await pair_user(db, want_a, nurse, msb)
        await pair_user(db, want_b, clerk, tsgh)
        await pair_user(db, cross_a, clerk, msb)
        await pair_user(db, cross_b, nurse, tsgh)

        assert await _repo.target_user_ids(db, cid) == sorted([want_a, want_b])

    async def test_帶入只包含相符者_不是任何人相符就全帶(self, client, db) -> None:
        """🔴 反向探針：DM 的同類查詢曾因關聯失效退化成「只要**存在任何人**相符即為真」，
        所有人都通過（#437 差異 3）。ET 的主路徑正是那個方向（由課程找人），而判錯的後果
        是把人加進課程並寄出通知信。

        造一個相符、一個不相符、一個身上沒有任何配對的學員——結果必須**恰好**是相符那一位。
        """
        teacher = await _user(db, "t_pr03", ROLE_TEACHER)
        cid = await _course(client, teacher)
        nurse, tsgh = await tag_id(db, "護理師"), await tag_id(db, _TSGH)
        await pair_course(db, cid, nurse, tsgh)
        match = await _user(db, "s_pr03a")
        other = await _user(db, "s_pr03b")
        await _user(db, "s_pr03c")  # 沒有任何配對
        await pair_user(db, match, nurse, tsgh)
        await pair_user(db, other, await tag_id(db, "行政人員"), await tag_id(db, _MSB))

        assert await _repo.target_user_ids(db, cid) == [match]

    async def test_單位未指定者只匹配全單位(self, client, db) -> None:
        """#538 導入前的既有指派單位為 NULL：仍符合 `(全單位, 護理師)`，不符合 `(三總, 護理師)`。"""
        teacher = await _user(db, "t_pr04", ROLE_TEACHER)
        nurse_tag = await tag_id(db, "護理師")
        legacy = await _user(db, "s_pr04")
        await pair_user(db, legacy, nurse_tag)  # 單位未指定
        any_unit = await _course(client, teacher, "全單位課")
        tsgh_only = await _course(client, teacher, "三總課")
        await pair_course(db, any_unit, nurse_tag)
        await pair_course(db, tsgh_only, nurse_tag, await tag_id(db, _TSGH))

        assert await _repo.target_user_ids(db, any_unit) == [legacy]
        assert await _repo.target_user_ids(db, tsgh_only) == []

    async def test_某單位全體只帶入該單位的人(self, client, db) -> None:
        """`(三總, 全體)` 是 #538 的新語意：三總所有學員。⚠️ 與 `(全單位, 全體)` 不同——
        **身上沒有任何配對的人不算**（他不屬於三總）。"""
        teacher = await _user(db, "t_pr05", ROLE_TEACHER)
        cid = await _course(client, teacher)
        tsgh = await tag_id(db, _TSGH)
        await pair_course(db, cid, await all_roles_id(db), tsgh)
        inside = await _user(db, "s_pr05a")
        outside = await _user(db, "s_pr05b")
        await _user(db, "s_pr05c")  # 沒有任何配對
        await pair_user(db, inside, await tag_id(db, "行政人員"), tsgh)
        await pair_user(db, outside, await tag_id(db, "行政人員"), await tag_id(db, _MSB))

        assert await _repo.target_user_ids(db, cid) == [inside]


class TestNewPairsOnPublishedCourse:
    """FR-ET-US8-04：已發布課程新增配對時，**只對新配對**的人補邀請。"""

    async def test_只解析新配對的人(self, client, db) -> None:
        teacher = await _user(db, "t_np01", ROLE_TEACHER)
        cid = await _course(client, teacher)
        nurse, clerk = await tag_id(db, "護理師"), await tag_id(db, "行政人員")
        tsgh = await tag_id(db, _TSGH)
        await pair_course(db, cid, nurse, tsgh)  # 既有配對
        await pair_course(db, cid, clerk, tsgh)  # 本次新增
        old_member = await _user(db, "s_np01a")
        new_member = await _user(db, "s_np01b")
        await pair_user(db, old_member, nurse, tsgh)
        await pair_user(db, new_member, clerk, tsgh)

        assert await _repo.target_user_ids_for_pairs(db, cid, [(tsgh, clerk)]) == [new_member]

    async def test_新增全單位全體時展開為全部學員(self, client, db) -> None:
        teacher = await _user(db, "t_np02", ROLE_TEACHER)
        cid = await _course(client, teacher)
        everyone = await _user(db, "s_np02")  # 沒有任何配對
        await pair_course(db, cid, await all_roles_id(db))

        pair = (await all_units_id(db), await all_roles_id(db))
        assert everyone in await _repo.target_user_ids_for_pairs(db, cid, [pair])


class TestGenericValueByFlag:
    """⭐ 通用值（「全單位」「全體」）以 `IS_ALL` 判定，**不以名稱判定**（#538）。

    DM 以 `TAG_NAME` 辨識「全單位」：把某個具體單位改名為「全單位」即等於擴權（#437 follow-up 1）。
    ET 的 DP03 擋得住「改名成通用值的名字」（名稱全表唯一、通用值不可改名），但判定邏輯若改成比
    名稱，**DB 層的任何改名**（直接 SQL、日後放寬改名規則）都會靜默改變帶入範圍。
    """

    async def test_全單位改了名字仍是通用值(self, client, db) -> None:
        teacher = await _user(db, "t_gv01", ROLE_TEACHER)
        nurse_tag = await tag_id(db, "護理師")
        legacy = await _user(db, "s_gv01")
        await pair_user(db, legacy, nurse_tag)  # 單位未指定——只會匹配課程端的通用單位
        cid = await _course(client, teacher)
        await pair_course(db, cid, nurse_tag)  # (全單位, 護理師)
        await db.execute(update(EtTag).where(EtTag.tag_id == await all_units_id(db)).values(tag_name="不限單位"))
        await db.flush()

        assert await _repo.target_user_ids(db, cid) == [legacy], "判定依 IS_ALL，名稱改了不得影響"

    async def test_具體單位取了像通用值的名字也不擴權(self, client, db) -> None:
        """反方向：一個**非** `IS_ALL` 的單位，就算名字叫「全單位」也只是一個普通單位。"""
        teacher = await _user(db, "t_gv02", ROLE_TEACHER)
        nurse_tag = await tag_id(db, "護理師")
        legacy = await _user(db, "s_gv02")
        await pair_user(db, legacy, nurse_tag)
        # 先把 seed 的「全單位」改名騰出名字，再讓一個具體單位頂替這個名字
        await db.execute(update(EtTag).where(EtTag.tag_id == await all_units_id(db)).values(tag_name="不限單位"))
        impostor = await new_tag(db, "全單位", tag_type="UNIT")
        cid = await _course(client, teacher)
        await pair_course(db, cid, nurse_tag, impostor)

        assert await _repo.target_user_ids(db, cid) == []
