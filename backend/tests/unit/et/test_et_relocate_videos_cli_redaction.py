"""影片目錄遷移 CLI 執行錯誤時印出的訊息去識別化（#905 B10）。"""

import asyncpg.exceptions as pg_exc
import pytest
from sqlalchemy.exc import DBAPIError

from app.et.material import relocate_videos

pytestmark = pytest.mark.unit

_ID = "A123456789"


class _FailingSession:
    async def __aenter__(self):
        orig = pg_exc.InvalidTextRepresentationError(f'invalid input syntax for type integer: "{_ID}"')
        raise DBAPIError.instance(statement="SELECT 1", params=(_ID,), orig=orig, dbapi_base_err=Exception) from orig

    async def __aexit__(self, *exc_info) -> None:
        return None


async def test_cli_error_message_masks_db_value(monkeypatch, capsys):
    monkeypatch.setattr(relocate_videos, "AsyncSessionLocal", _FailingSession)

    assert await relocate_videos._amain([]) == 2
    out = capsys.readouterr().out
    assert _ID not in out
    assert "invalid input syntax for type integer" in out
