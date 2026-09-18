"""`et drop invitation`（f1d93a5c7b04）之回填正確性（#362）。

測試**直接執行 migration 模組匯出的 `_BACKFILL`**，而非在測試裡重抄一份 SQL——重抄會
drift，屆時測試綠燈但實際 migration 是另一套邏輯（作法比照
`test_et_backfill_last_activity_migration.py`）。

## 為何非測不可

`tests/integration/conftest.py` 的 `alembic upgrade head` 會讓這段 SQL 被 PostgreSQL
實際 parse 與執行，所以**語法**有被驗到。但那時 `ET_INVITATION` 是空表，**回填語意一行
都沒被驗證**——migration docstring 花了四十行論證的三件事（`IS_REMOVED` 不救回、
`ORDER BY SENT_AT` 取最早、查無帳號自然略過）在那之前全部只是宣稱。

其中「`DO NOTHING` 在同一句 INSERT 內留下哪一列」更是**實測得來、非 SQL 標準保證**的
行為，這種結論最容易在日後被無聲改掉。

兩張表都以 `CREATE TEMP TABLE ... ON COMMIT DROP` 建立：PostgreSQL 的 temp schema 排在
`search_path` 之前，故 SQL 裡未加 schema 限定的表名會落在暫存表上，不會動到真實資料。

`ET_ENROLLMENT` 的暫存版**必須帶 `UQ_ET_ENROLLMENT_USER_COURSE` 具名唯一約束**——與上一支
回填測試刻意不建約束的取捨相反：那支靠 `MAX()`（對重複不敏感），本支的整個重點就是
`ON CONFLICT ON CONSTRAINT` 的行為，少了約束連 SQL 都跑不起來。
"""

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

_MIGRATION = (
    Path(__file__).resolve().parents[3] / "alembic" / "versions" / "20260918_1030_f1d93a5c7b04_et_drop_invitation.py"
)


def _ts(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, tzinfo=timezone.utc)


def _load_migration():
    """以路徑載入 migration 模組（alembic/versions 非 package，不能 import）。"""
    spec = importlib.util.spec_from_file_location("_mig_et_drop_invitation", _MIGRATION)
    assert spec and spec.loader, f"找不到 migration：{_MIGRATION}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def _create_temp_tables(db) -> None:
    await db.execute(
        text(
            'CREATE TEMP TABLE "ET_ENROLLMENT" ('
            '  "USER_ID" varchar(20),'
            '  "COURSE_ID" bigint,'
            '  "JOIN_SOURCE" varchar(30),'
            '  "JOINED_AT" timestamptz,'
            '  "COMPLETION_STATUS" varchar(20),'
            '  "IS_REMOVED" boolean DEFAULT false,'
            '  "REMOVED_AT" timestamptz,'
            '  "CREATED_USER" varchar(20),'
            '  "CREATED_DATE" timestamptz,'
            '  "DELETED" integer DEFAULT 0,'
            '  CONSTRAINT "UQ_ET_ENROLLMENT_USER_COURSE" UNIQUE ("USER_ID", "COURSE_ID")'
            ") ON COMMIT DROP"
        )
    )
    await db.execute(
        text(
            'CREATE TEMP TABLE "ET_INVITATION" ('
            '  "COURSE_ID" bigint,'
            '  "EMAIL" varchar(255),'
            '  "STATUS" varchar(20),'
            '  "SENT_AT" timestamptz,'
            '  "DELETED" integer DEFAULT 0'
            ") ON COMMIT DROP"
        )
    )
    await db.execute(
        text(
            'CREATE TEMP TABLE "DP_USER" ('
            '  "USER_ID" varchar(20),'
            '  "EMAIL" varchar(255),'
            '  "DELETED" integer DEFAULT 0'
            ") ON COMMIT DROP"
        )
    )


async def _invitation(db, *, course_id: int, email: str, status: str, sent_at: datetime, deleted: int = 0) -> None:
    await db.execute(
        text(
            'INSERT INTO "ET_INVITATION" ("COURSE_ID", "EMAIL", "STATUS", "SENT_AT", "DELETED")'
            " VALUES (:c, :e, :s, :t, :d)"
        ).bindparams(c=course_id, e=email, s=status, t=sent_at, d=deleted)
    )


async def _account(db, *, user_id: str, email: str, deleted: int = 0) -> None:
    await db.execute(
        text('INSERT INTO "DP_USER" ("USER_ID", "EMAIL", "DELETED") VALUES (:u, :e, :d)').bindparams(
            u=user_id, e=email, d=deleted
        )
    )


async def _run_backfill(db) -> None:
    mod = _load_migration()
    await db.execute(mod._BACKFILL.bindparams(source=mod._SOURCE_EMAIL_INVITE, completion=mod._COMPLETION_NOT_STARTED))


async def _rows(db) -> list[tuple]:
    result = await db.execute(
        text(
            'SELECT "USER_ID", "COURSE_ID", "JOIN_SOURCE", "JOINED_AT", "IS_REMOVED"'
            ' FROM "ET_ENROLLMENT" ORDER BY "USER_ID"'
        )
    )
    return list(result.all())


class TestBackfillPending:
    async def test_pending_補成選課列且加入時點取_sent_at(self, db) -> None:
        """`JOINED_AT` 取邀請寄出時點，不取 migration 執行時間。

        後者會讓所有回填的人看起來是同一秒加入的，且晚於他們實際收到信的日子。
        """
        await _create_temp_tables(db)
        await _account(db, user_id="u1", email="a@x.tw")
        await _invitation(db, course_id=7, email="a@x.tw", status="PENDING", sent_at=_ts(1))

        await _run_backfill(db)

        assert await _rows(db) == [("u1", 7, "EMAIL_INVITE", _ts(1), False)]

    async def test_joined_與_revoked_不回填(self, db) -> None:
        """前者的選課列在 accept 當下已建立；後者是教師明示不要那個人。"""
        await _create_temp_tables(db)
        await _account(db, user_id="u1", email="j@x.tw")
        await _account(db, user_id="u2", email="r@x.tw")
        await _invitation(db, course_id=7, email="j@x.tw", status="JOINED", sent_at=_ts(1))
        await _invitation(db, course_id=7, email="r@x.tw", status="REVOKED", sent_at=_ts(1))

        await _run_backfill(db)

        assert await _rows(db) == []

    async def test_查無帳號的_email_自然略過(self, db) -> None:
        """SA 裁示「只邀請既有帳號」是後來才加的，早期可能留有寄給系統外位址的 PENDING。"""
        await _create_temp_tables(db)
        await _invitation(db, course_id=7, email="nobody@x.tw", status="PENDING", sent_at=_ts(1))

        await _run_backfill(db)

        assert await _rows(db) == []

    async def test_軟刪除帳號不回填(self, db) -> None:
        """與執行期 `recipients_by_emails` 對齊（實務上恆真，但兩邊不一致是誤讀來源）。"""
        await _create_temp_tables(db)
        await _account(db, user_id="u1", email="gone@x.tw", deleted=1)
        await _invitation(db, course_id=7, email="gone@x.tw", status="PENDING", sent_at=_ts(1))

        await _run_backfill(db)

        assert await _rows(db) == []

    async def test_已軟刪除的邀請列不回填(self, db) -> None:
        await _create_temp_tables(db)
        await _account(db, user_id="u1", email="d@x.tw")
        await _invitation(db, course_id=7, email="d@x.tw", status="PENDING", sent_at=_ts(1), deleted=1)

        await _run_backfill(db)

        assert await _rows(db) == []


class TestBackfillConflicts:
    async def test_被移除的學員不會被回填救回(self, db) -> None:
        """🔴 `DO NOTHING` 的整個重點。

        `ET_INVITATION` 沒有記「移除發生在邀請之前還是之後」，而兩種順序要的結果相反。
        兩種錯法的代價不對稱：沒帶回的錯由教師一次點擊修好；帶回的錯是把已被移除的人
        放回課程且**無人會發現**。
        """
        await _create_temp_tables(db)
        await _account(db, user_id="u1", email="rm@x.tw")
        await db.execute(
            text(
                'INSERT INTO "ET_ENROLLMENT" ("USER_ID", "COURSE_ID", "JOIN_SOURCE", "JOINED_AT",'
                ' "COMPLETION_STATUS", "IS_REMOVED", "REMOVED_AT", "CREATED_USER", "CREATED_DATE", "DELETED")'
                " VALUES ('u1', 7, 'TAG_DEFAULT', :t, 'IN_PROGRESS', true, :t, 'SYSTEM', :t, 0)"
            ).bindparams(t=_ts(1))
        )
        await _invitation(db, course_id=7, email="rm@x.tw", status="PENDING", sent_at=_ts(5))

        await _run_backfill(db)

        assert await _rows(db) == [("u1", 7, "TAG_DEFAULT", _ts(1), True)], "被移除者必須維持移除"

    async def test_同人同課多筆_pending_只補一列且取最早那次(self, db) -> None:
        """`ET_INVITATION` 沒有 (COURSE_ID, EMAIL) 唯一約束，同一人同一課可能有多列。

        `DO NOTHING` 擋得住同一句 INSERT 內的重複，但**留下哪一列沒有保證**——沒有
        `ORDER BY` 時 `JOINED_AT` 會是那幾次邀請中任意一次的 `SENT_AT`。

        ⚠️ 較晚那筆刻意先插入：若排序失效，掃描順序最可能讓它勝出，本條就會紅。
        """
        await _create_temp_tables(db)
        await _account(db, user_id="u1", email="dup@x.tw")
        await _invitation(db, course_id=7, email="dup@x.tw", status="PENDING", sent_at=_ts(20))
        await _invitation(db, course_id=7, email="dup@x.tw", status="PENDING", sent_at=_ts(3))

        await _run_backfill(db)

        assert await _rows(db) == [("u1", 7, "EMAIL_INVITE", _ts(3), False)], "須取最早那次邀請的時點"

    async def test_已在籍者不受影響(self, db) -> None:
        await _create_temp_tables(db)
        await _account(db, user_id="u1", email="in@x.tw")
        await db.execute(
            text(
                'INSERT INTO "ET_ENROLLMENT" ("USER_ID", "COURSE_ID", "JOIN_SOURCE", "JOINED_AT",'
                ' "COMPLETION_STATUS", "IS_REMOVED", "CREATED_USER", "CREATED_DATE", "DELETED")'
                " VALUES ('u1', 7, 'TAG_DEFAULT', :t, 'IN_PROGRESS', false, 'SYSTEM', :t, 0)"
            ).bindparams(t=_ts(1))
        )
        await _invitation(db, course_id=7, email="in@x.tw", status="PENDING", sent_at=_ts(5))

        await _run_backfill(db)

        assert await _rows(db) == [("u1", 7, "TAG_DEFAULT", _ts(1), False)], "既有在籍列不得被改寫"

    async def test_大小寫不同的兩個帳號都會被加入(self, db) -> None:
        """`UQ_DP_USER_EMAIL` 為大小寫敏感，`A@x` 與 `a@x` 在 schema 上可並存。

        真的並存時兩個帳號都被加入是**對的**——教師邀的那個 Email 確實對應到這兩個人，
        少加任何一個都是錯的。本條把這個行為釘住，避免日後有人「順手去重」。
        """
        await _create_temp_tables(db)
        await _account(db, user_id="u1", email="Mix@x.tw")
        await _account(db, user_id="u2", email="mix@x.tw")
        await _invitation(db, course_id=7, email="mix@x.tw", status="PENDING", sent_at=_ts(1))

        await _run_backfill(db)

        assert [r[0] for r in await _rows(db)] == ["u1", "u2"]
