"""稽核驗鏈 CLI 輸出渲染單元測試（純函式，不需 DB）。

render_result 把 ChainVerifyResult 轉為（人可讀訊息, exit_code）；OK/EMPTY → 0、BROKEN → 1。
供 ops 例行稽核 / CI 判讀退出碼。
"""

from datetime import datetime, timezone

import pytest

from app.dp.audit.verify import ChainVerifyResult, render_result

pytestmark = pytest.mark.unit


def test_render_ok():
    msg, code = render_result(ChainVerifyResult(status="OK", total=12))
    assert code == 0
    assert "12" in msg
    assert "✅" in msg


def test_render_empty():
    msg, code = render_result(ChainVerifyResult(status="EMPTY", total=0))
    assert code == 0
    assert "0" in msg


def test_render_broken_includes_position():
    result = ChainVerifyResult(
        status="BROKEN",
        total=5,
        first_broken_log_id=42,
        first_broken_created_date=datetime(2026, 8, 3, 1, 2, 3, tzinfo=timezone.utc),
        first_broken_func_name="DP-USERS",
    )
    msg, code = render_result(result)
    assert code == 1
    assert "42" in msg
    assert "DP-USERS" in msg
    assert "❌" in msg


def test_ok_property():
    assert ChainVerifyResult(status="OK", total=1).ok is True
    assert ChainVerifyResult(status="EMPTY", total=0).ok is True
    assert ChainVerifyResult(status="BROKEN", total=1, first_broken_log_id=1).ok is False


async def test_cli_執行錯誤的訊息不帶出_SQL_綁定參數(monkeypatch, capsys):
    """#833 C2：CLI 原本 `print(exc)`，SQLAlchemy 例外的 `[parameters: …]` 會原樣印到終端與排程 log。"""
    from sqlalchemy.exc import DBAPIError

    from app.dp.audit import verify

    def _boom():
        raise DBAPIError(
            'SELECT * FROM "DP_AUDIT_LOG" WHERE "CREATED_USER" = $1', ("wang@example.com",), Exception("x")
        )

    monkeypatch.setattr(verify, "_cli_session", _boom)

    assert await verify._amain() == 2
    out = capsys.readouterr().out
    assert "驗鏈執行錯誤（非斷鏈）" in out
    assert "DBAPIError" in out, "仍要看得出失敗類型"
    assert "wang@example.com" not in out
    assert "[parameters:" not in out


async def test_cli_例外訊息為空時只印型別(monkeypatch, capsys):
    from app.dp.audit import verify

    def _boom():
        raise TimeoutError()

    monkeypatch.setattr(verify, "_cli_session", _boom)

    assert await verify._amain() == 2
    assert capsys.readouterr().out.strip() == "⚠️ 驗鏈執行錯誤（非斷鏈）：TimeoutError"
