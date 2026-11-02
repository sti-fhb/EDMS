"""DP_AUDIT_LOG 資料庫層防竄改（#22）。

兩層各自獨立驗證：

1. **trigger**（migration 建立）：任何連線對 DP_AUDIT_LOG 下 UPDATE / DELETE / TRUNCATE 一律報錯，
   含資料表 owner 與 superuser。以測試連線本身（即執行 migration 的角色）直接下指令驗證。
2. **app 執行期角色**（`scripts/db-app-role.sql` 建立）：對 DP_AUDIT_LOG 只有 INSERT / SELECT，
   權限檢查在 trigger 之前就擋下（SQLSTATE 42501，而非 trigger 的 P0001）；其餘資料表可正常 DML。

第 2 組需在測試交易內 CREATE ROLE 再 SET ROLE，要求測試連線為 superuser——CI 的 PostgreSQL
service container（POSTGRES_USER）即是；本機測試帳號非 superuser 時自動略過，但在 CI（環境變數 `CI`）
上改為失敗——否則 CI 一旦換成非 superuser，這組測試會靜默變成 skipped、CI 仍是綠的。
角色、GRANT、預設權限都在 `db` fixture 的交易內建立，結束時隨 rollback 一併消失，不留在叢集上。
"""

import os
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dp.audit.service import AuditLogService

pytestmark = pytest.mark.integration

_SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "db-app-role.sql"
_INSUFFICIENT_PRIVILEGE = "42501"
_RAISE_EXCEPTION = "P0001"


async def _write_audit(db: AsyncSession) -> int:
    """經正式寫入路徑（log_action：advisory lock + 讀前列 hash + INSERT）寫一筆，回傳 LOG_ID。"""
    await AuditLogService().log_action(
        db,
        module="DP",
        func_name="DP-USERS",
        action_type="UPDATE",
        result="SUCCESS",
        operator_id="admin01",
        target_id="user001",
        after_value={"status": "DISABLED"},
    )
    return (await db.execute(text('SELECT max("LOG_ID") FROM "DP_AUDIT_LOG"'))).scalar_one()


async def _expect_sqlstate(db: AsyncSession, sql: str, sqlstate: str, params: dict | None = None) -> str:
    """在 savepoint 內執行預期失敗的 SQL，斷言 SQLSTATE，回傳錯誤訊息；外層交易不受影響。"""
    with pytest.raises(DBAPIError) as exc_info:
        async with db.begin_nested():
            await db.execute(text(sql), params or {})
    assert getattr(exc_info.value.orig, "sqlstate", None) == sqlstate, str(exc_info.value.orig)
    return str(exc_info.value.orig)


# ── 1. trigger：連 owner / superuser 也擋 ────────────────────────────────────


@pytest.mark.parametrize(
    "sql",
    [
        'UPDATE "DP_AUDIT_LOG" SET "DESCRIPTION" = \'x\'',
        'DELETE FROM "DP_AUDIT_LOG"',
        'TRUNCATE "DP_AUDIT_LOG"',
    ],
    ids=["update", "delete", "truncate"],
)
async def test_trigger_rejects_modification_even_for_table_owner(db, sql):
    """以執行 migration 的角色（資料表 owner；CI 上為 superuser）直接下指令仍被 trigger 擋下。"""
    await _write_audit(db)
    message = await _expect_sqlstate(db, sql, _RAISE_EXCEPTION)
    assert "append-only" in message


async def test_trigger_keeps_rows_intact_after_rejected_modification(db):
    """被擋下的 UPDATE / DELETE 不留下任何異動：列數與內容不變。"""
    log_id = await _write_audit(db)
    by_id = {"id": log_id}
    await _expect_sqlstate(
        db, 'UPDATE "DP_AUDIT_LOG" SET "RESULT" = \'FAIL\' WHERE "LOG_ID" = :id', _RAISE_EXCEPTION, by_id
    )
    await _expect_sqlstate(db, 'DELETE FROM "DP_AUDIT_LOG" WHERE "LOG_ID" = :id', _RAISE_EXCEPTION, by_id)

    row = (await db.execute(text('SELECT "RESULT" FROM "DP_AUDIT_LOG" WHERE "LOG_ID" = :id'), {"id": log_id})).one()
    assert row.RESULT == "SUCCESS"


async def test_trigger_allows_insert_and_select(db):
    """trigger 只擋改 / 刪；正式寫入路徑照常可用。"""
    first = await _write_audit(db)
    second = await _write_audit(db)
    assert second > first


# ── 2. app 執行期角色：權限層擋改刪 ─────────────────────────────────────────


def _role_script_body() -> str:
    """取出腳本的 DO 區塊（psql 專屬的 `\\set` / 變數行在 SQLAlchemy 下不能執行）。"""
    match = re.search(r"^DO \$body\$.*?^\$body\$;", _SCRIPT.read_text(encoding="utf-8"), re.S | re.M)
    assert match, f"{_SCRIPT} 找不到 DO $body$ … $body$; 區塊"
    return match.group(0)


async def _apply_role_script(db: AsyncSession, role: str) -> None:
    await db.execute(text("SELECT set_config('edms.app_role', :r, true)"), {"r": role})
    # 走 exec_driver_sql 原樣送出：DO 區塊內的 `::regclass` 等字樣不該經 text() 的綁定參數解析
    await (await db.connection()).exec_driver_sql(_role_script_body())


@pytest.fixture
async def app_role(db) -> str:
    """在測試交易內以腳本建立 app 角色，回傳角色名；需 superuser（建角色後還要 SET ROLE）。"""
    is_super = (await db.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user"))).scalar_one()
    if not is_super:
        if os.environ.get("CI"):
            pytest.fail("CI 的測試庫連線必須是 superuser，否則 app 角色權限（#22 驗收條件）無人守門")
        pytest.skip("需以 superuser 連測試庫（CI service container 即是）：測試內要 CREATE ROLE 再 SET ROLE")
    # 角色名為叢集層級；xdist 各 worker 交易未結束前同名會互等，故每次取唯一名稱
    role = f"edms_app_t{uuid.uuid4().hex[:12]}"
    await _apply_role_script(db, role)
    return role


async def _as_app_role(db: AsyncSession, role: str) -> None:
    await db.execute(text(f'SET LOCAL ROLE "{role}"'))


async def test_app_role_can_write_and_read_audit_log(db, app_role):
    """app 角色走正式寫入路徑可寫入稽核、可查詢（INSERT / SELECT 與 Identity 產號皆可用）。"""
    await _as_app_role(db, app_role)
    first = await _write_audit(db)
    second = await _write_audit(db)
    assert second > first


@pytest.mark.parametrize(
    "sql",
    [
        'UPDATE "DP_AUDIT_LOG" SET "DESCRIPTION" = \'x\'',
        'DELETE FROM "DP_AUDIT_LOG"',
        'TRUNCATE "DP_AUDIT_LOG"',
    ],
    ids=["update", "delete", "truncate"],
)
async def test_app_role_denied_modifying_audit_log(db, app_role, sql):
    """app 角色對 DP_AUDIT_LOG 改 / 刪 / 清空 → 權限不足（42501），在 trigger 之前就被擋。"""
    await _write_audit(db)
    await _as_app_role(db, app_role)
    await _expect_sqlstate(db, sql, _INSUFFICIENT_PRIVILEGE)


async def test_app_role_has_dml_on_other_tables(db, app_role):
    """一般資料表 SELECT / INSERT / UPDATE / DELETE 皆可（app 正常運作所需）。"""
    await _as_app_role(db, app_role)
    await db.execute(text('SELECT count(*) FROM "DP_USER"'))
    await db.execute(text('UPDATE "DP_USER" SET "USER_NAME" = "USER_NAME" WHERE false'))
    await db.execute(text('DELETE FROM "DP_USER" WHERE false'))


async def test_app_role_cannot_change_schema_or_version(db, app_role):
    """不可 DDL、不可改 alembic_version、不可 TRUNCATE 一般資料表——schema 只由 migration 動。"""
    await _as_app_role(db, app_role)
    await _expect_sqlstate(db, 'CREATE TABLE "ZZ_APP_ROLE_PROBE" (id int)', _INSUFFICIENT_PRIVILEGE)
    await _expect_sqlstate(db, "UPDATE alembic_version SET version_num = version_num", _INSUFFICIENT_PRIVILEGE)
    await _expect_sqlstate(db, 'TRUNCATE "DP_USER"', _INSUFFICIENT_PRIVILEGE)


async def test_app_role_gets_dml_on_tables_created_later_by_owner(db, app_role):
    """預設權限：owner 之後（新 migration）建立的資料表，app 角色不必重跑腳本即可 DML。"""
    await db.execute(text('CREATE TABLE "ZZ_APP_ROLE_LATER" (id int GENERATED ALWAYS AS IDENTITY, v int)'))
    await _as_app_role(db, app_role)
    await db.execute(text('INSERT INTO "ZZ_APP_ROLE_LATER" (v) VALUES (1)'))
    await db.execute(text('UPDATE "ZZ_APP_ROLE_LATER" SET v = 2'))
    await db.execute(text('DELETE FROM "ZZ_APP_ROLE_LATER"'))


async def _has_privilege(db: AsyncSession, role: str, table: str, privilege: str) -> bool:
    return (
        await db.execute(text("SELECT has_table_privilege(:r, :t, :p)"), {"r": role, "t": table, "p": privilege})
    ).scalar_one()


async def test_role_script_converges_drifted_privileges(db, app_role):
    """腳本冪等且會收斂：事後被多給的權限，重跑腳本即收回（部署文件要求每次都能放心重跑）。"""
    drift = [
        ('"DP_AUDIT_LOG"', "UPDATE"),
        ('"DP_AUDIT_LOG"', "DELETE"),
        ('"DP_USER"', "TRUNCATE"),
        ("alembic_version", "INSERT"),
    ]
    for table, privilege in drift:
        await db.execute(text(f'GRANT {privilege} ON {table} TO "{app_role}"'))
        assert await _has_privilege(db, app_role, table, privilege)

    await _apply_role_script(db, app_role)

    for table, privilege in drift:
        assert not await _has_privilege(db, app_role, table, privilege), f"{privilege} ON {table} 未被收回"
    assert await _has_privilege(db, app_role, '"DP_AUDIT_LOG"', "INSERT")
    assert await _has_privilege(db, app_role, '"DP_USER"', "UPDATE")


async def test_role_script_refuses_owner(db, app_role):
    """把 app_role 誤填成資料表 owner 時拒絕執行，不會把 owner 的屬性改掉。"""
    owner_sql = """SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = '"DP_AUDIT_LOG"'::regclass"""
    owner = (await db.execute(text(owner_sql))).scalar_one()
    with pytest.raises(DBAPIError, match="不可與資料表 owner 相同"):
        async with db.begin_nested():
            await _apply_role_script(db, owner)


async def test_role_script_refuses_superuser(db, app_role):
    """app_role 是 superuser 時拒絕執行（不會替它降級，也不會把它當 app 角色授權）。"""
    su = f"edms_su_t{uuid.uuid4().hex[:12]}"
    await db.execute(text(f'CREATE ROLE "{su}" SUPERUSER'))
    with pytest.raises(DBAPIError, match="superuser"):
        async with db.begin_nested():
            await _apply_role_script(db, su)


async def test_role_script_refuses_role_with_memberships(db, app_role):
    """app 角色是其他角色的成員（如 pg_write_all_data）時拒絕：成員關係會繞過本腳本的 REVOKE。"""
    await db.execute(text(f'GRANT pg_write_all_data TO "{app_role}"'))
    with pytest.raises(DBAPIError, match="成員"):
        async with db.begin_nested():
            await _apply_role_script(db, app_role)


async def test_role_script_refuses_role_owning_a_schema(db, app_role):
    """app 角色擁有 schema（可 DROP 其下任何表，GRANT 管不到）時拒絕。"""
    await db.execute(text(f'CREATE SCHEMA "zz_{app_role}" AUTHORIZATION "{app_role}"'))
    with pytest.raises(DBAPIError, match="擁有資料庫物件"):
        async with db.begin_nested():
            await _apply_role_script(db, app_role)
