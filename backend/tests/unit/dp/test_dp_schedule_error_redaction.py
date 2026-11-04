"""排程失敗寫進 DP_SCHEDULE_LOG 的錯誤訊息去識別化（#905 B10）。

ERROR_MSG 顯示在 DP 排程畫面，與 log 一樣不能帶出 DB 錯誤主訊息裡的值。
"""

from contextlib import asynccontextmanager

import asyncpg.exceptions as pg_exc
import pytest
from sqlalchemy.exc import DBAPIError

from app.dp.audit import verify
from app.dp.schedules import scheduler

pytestmark = pytest.mark.unit

_ID = "A123456789"


def _db_error() -> DBAPIError:
    orig = pg_exc.InvalidTextRepresentationError(f'invalid input syntax for type integer: "{_ID}"')
    try:
        raise DBAPIError.instance(statement="SELECT 1", params=(), orig=orig, dbapi_base_err=Exception) from orig
    except DBAPIError as exc:
        return exc


class _FakeRepo:
    def __init__(self) -> None:
        self.logs: list[dict] = []

    async def insert_log(self, db, **kwargs) -> None:
        self.logs.append(kwargs)

    async def update_last_run(self, db, **kwargs) -> None:
        return None


async def test_schedule_error_msg_masks_db_value(monkeypatch):
    """job 拋 DB 錯誤時，寫進 ERROR_MSG 的是遮罩後的訊息，錯誤種類仍看得出來。"""
    repo = _FakeRepo()

    async def _failing_job() -> None:
        raise _db_error()

    monkeypatch.setattr(scheduler, "_repo", repo)
    monkeypatch.setattr(scheduler, "_resolve_handler", lambda _ref: _failing_job)

    status = await scheduler.run_and_log(None, "SCHZT001", "app.dp.fake.run")

    assert status == "FAILED"
    error_msg = repo.logs[0]["error_msg"]
    assert _ID not in error_msg
    assert "invalid input syntax for type integer" in error_msg


async def test_verify_cli_masks_db_value(monkeypatch, capsys):
    """稽核驗證 CLI 執行錯誤時印出的訊息同樣遮掉 DB 錯誤裡的值。"""

    @asynccontextmanager
    async def _failing_session():
        raise _db_error()
        yield  # pragma: no cover — 讓函式成為 generator

    monkeypatch.setattr(verify, "_cli_session", _failing_session)

    assert await verify._amain() == 2
    out = capsys.readouterr().out
    assert _ID not in out
    assert "invalid input syntax for type integer" in out
