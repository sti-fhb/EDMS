"""outbox 遮罩政策（#50）單元測試：FAILED 逾時效遮罩的時效判定 + SCHDP001 批次容錯。

SA 裁示（2026-11-02）：FAILED 超過「該信件範本對應的 TTL 參數」後遮罩。本檔以 fake repository /
param service 驗「每支範本用對參數、cutoff 算對」；UPDATE 條件本身（STATUS / 空 BODY / 已遮罩）
由 integration 測試對真 DB 驗。
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.dp.notify import redaction
from app.dp.notify.redaction import (
    ONE_TIME_LINK_TEMPLATES,
    REDACTED_BODY,
    redact_after_sent,
    redact_expired_failed,
    redact_expired_failed_mails,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


class _FakeParams:
    def __init__(self, values: dict[tuple[str, str], int]):
        self._values = values
        self.reads: list[tuple[str, str]] = []

    async def get_int_param(self, db, param_id, key, default):
        self.reads.append((param_id, key))
        return self._values.get((param_id, key), default)


class _RecordingRepo:
    def __init__(self, rowcount: int = 1):
        self.calls: list[dict] = []
        self._rowcount = rowcount

    async def redact_failed_created_before(self, db, **kw):
        self.calls.append(kw)
        return self._rowcount


async def test_each_template_uses_its_own_ttl_param():
    """四支範本各自以對應的時效參數算 cutoff；EMAIL_CHANGE_VERIFY 用獨立參數。"""
    repo = _RecordingRepo()
    params = _FakeParams({("LOGIN", "RESET_TOKEN_TTL_MIN"): 45, ("LOGIN", "EMAIL_CHANGE_TTL_MIN"): 90})

    total = await redact_expired_failed(None, now=_NOW, repository=repo, params=params)

    cutoffs = {(c["module"], c["template_code"]): _NOW - c["cutoff"] for c in repo.calls}
    assert cutoffs == {
        ("DP", "PWD_RESET"): timedelta(minutes=45),
        ("DP", "EMAIL_CHANGE_VERIFY"): timedelta(minutes=90),
        ("DP", "ACCOUNT_VERIFY"): timedelta(minutes=45),
        ("DP", "ACCOUNT_INVITE"): timedelta(minutes=45),
    }
    assert all(c["redacted_body"] == REDACTED_BODY and c["now"] == _NOW for c in repo.calls)
    assert total == 4
    # 共用參數只讀一次
    assert sorted(params.reads) == [("LOGIN", "EMAIL_CHANGE_TTL_MIN"), ("LOGIN", "RESET_TOKEN_TTL_MIN")]


async def test_missing_param_falls_back_to_sender_default():
    """參數讀不到時用 30 分鐘——與寄信端 `_DEFAULT_TTL_MIN` 相同，兩邊一致。"""
    repo = _RecordingRepo()
    await redact_expired_failed(None, now=_NOW, repository=repo, params=_FakeParams({}))
    assert {_NOW - c["cutoff"] for c in repo.calls} == {timedelta(minutes=30)}


def test_ttl_mapping_matches_sender_params():
    """固定時效對照表內容（每列註明寄信端出處）。

    ⚠️ 本條只比對寫死的期望值，**與寄信端程式沒有連動**：寄信端改讀別的參數時本條不會紅。
    改對照表或改寄信端讀的參數時，須人工核對另一邊（出處見 `redaction.ONE_TIME_LINK_TEMPLATES` 註解）。
    """
    assert ONE_TIME_LINK_TEMPLATES == {
        ("DP", "PWD_RESET"): ("LOGIN", "RESET_TOKEN_TTL_MIN"),  # forgot_service
        ("DP", "EMAIL_CHANGE_VERIFY"): ("LOGIN", "EMAIL_CHANGE_TTL_MIN"),  # email_change_service
        ("DP", "ACCOUNT_VERIFY"): ("LOGIN", "RESET_TOKEN_TTL_MIN"),  # register / verify_service
        ("DP", "ACCOUNT_INVITE"): ("LOGIN", "RESET_TOKEN_TTL_MIN"),  # users/service._invite_ttl_min
    }
    assert redaction._DEFAULT_TTL_MIN == 30


@pytest.mark.parametrize(
    ("module", "code", "expected"),
    [
        ("DP", "ACCOUNT_INVITE", True),
        ("DP", "ACCOUNT_VERIFY", True),
        ("DP", "PWD_EXPIRY_REMIND", False),
        ("ET", "ACCOUNT_INVITE", False),
    ],
)
def test_redact_after_sent_keyed_by_module_and_code(module, code, expected):
    assert redact_after_sent(module, code) is expected


class _FakeSession:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


async def test_schdp001_batch_commits_and_returns_count(monkeypatch):
    async def fake_redact(db, *, now):
        return 3

    monkeypatch.setattr(redaction, "redact_expired_failed", fake_redact)
    db = _FakeSession()
    assert await redact_expired_failed_mails(db) == 3
    assert db.committed and not db.rolled_back


async def test_schdp001_batch_failure_rolls_back_without_raising(monkeypatch):
    """本批失敗不往外拋（否則 SCHDP001 彙總 log 整條不寫）。"""

    async def boom(db, *, now):
        raise RuntimeError("db down")

    monkeypatch.setattr(redaction, "redact_expired_failed", boom)
    db = _FakeSession()
    assert await redact_expired_failed_mails(db) == 0
    assert db.rolled_back and not db.committed
