"""SCHET002 第 5 批（孤兒影片檔清理）在 handler 層的接線（#775 code review MEDIUM）。

第 5 批失敗不得讓整個 job 被記成失敗——前四批（到期關閉、結清作答、加急提醒、文件變動
通知）已各自 commit。前四批在此全以假物件取代：本檔只驗接線，不碰 DB 與檔案系統。
"""

from types import SimpleNamespace

import pytest

from app.et.schedules import handlers

pytestmark = pytest.mark.unit


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def commit(self) -> None:
        return None


class _Schedule:
    async def close_expired_courses(self, _db):
        return 1

    async def settle_stale_attempts(self, _db):
        return 2

    async def send_urgent_reminds(self, _db):
        return 3


class _DocChanges:
    async def run(self, _db):
        return SimpleNamespace(notified=0, scanned_docs=0, skipped_docs=0, baselined=0)


@pytest.fixture
def stubbed(monkeypatch):
    monkeypatch.setattr(handlers, "AsyncSessionLocal", _Session)
    monkeypatch.setattr(handlers, "EtScheduleService", _Schedule)
    monkeypatch.setattr(handlers, "EtDocChangeNotifyService", _DocChanges)


async def test_第5批拋錯時_job_照樣完成並記下失敗(stubbed, monkeypatch, caplog) -> None:
    class _Boom:
        async def run(self, _db):
            raise RuntimeError("boom")

    monkeypatch.setattr(handlers, "EtOrphanVideoSweeper", _Boom)
    caplog.set_level("INFO")

    await handlers.daily_job()  # 不得往外拋

    assert "孤兒影片檔清理失敗" in caplog.text
    # 正向錨點：前四批的結果照常寫進完成 log
    assert "到期關閉 1 門" in caplog.text


async def test_第5批中止時_完成_log_帶出原因(stubbed, monkeypatch, caplog) -> None:
    class _Aborted:
        async def run(self, _db):
            return SimpleNamespace(scanned=5, deleted=0, aborted="白名單為空但目錄內有影片檔")

    monkeypatch.setattr(handlers, "EtOrphanVideoSweeper", _Aborted)
    caplog.set_level("INFO")

    await handlers.daily_job()

    assert "孤兒影片檔清理中止（白名單為空但目錄內有影片檔）" in caplog.text
