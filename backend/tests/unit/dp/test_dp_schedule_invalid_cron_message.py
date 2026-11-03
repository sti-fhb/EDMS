"""cron 不合法時的錯誤訊息（#902）。

原本把 APScheduler 的例外原文接進訊息，DP06 畫面因此顯示「Error validating expression
'7': the last value (7) is higher than the maximum value (6)」。改為固定中文句，例外原文
只進 log。

例外原文含使用者輸入值，故「訊息不含原文」與「訊息不含輸入值」分開斷言：只比對原文的
其中一段，換個輸入就可能漏。
"""

import logging
from types import SimpleNamespace

import pytest

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.dp.schedules.scheduler import validate_cron
from app.dp.schedules.schemas import ScheduleUpdate
from app.dp.schedules.service import ScheduleService

pytestmark = pytest.mark.unit

_INVALID_CRON = "0 10 * * 7"


class _FakeRepo:
    async def get(self, db, job_id):
        return SimpleNamespace(job_id=job_id, module="DP", cron_expr="0 8 * * *", is_enabled=True, description=None)


async def _allow(*_args, **_kwargs) -> None:
    return None


async def _update_with_invalid_cron(monkeypatch) -> AppError:
    service = ScheduleService(repository=_FakeRepo())
    monkeypatch.setattr(service, "_ensure_may_edit", _allow)
    data = ScheduleUpdate(job_name="帳號檢核", cron_expr=_INVALID_CRON, is_enabled=True)
    with pytest.raises(AppError) as excinfo:
        await service.update_job(None, job_id="SCHDP001", data=data, operator=OperatorInfo("u1"))
    return excinfo.value


def _library_message() -> str:
    with pytest.raises(ValueError) as excinfo:
        validate_cron(_INVALID_CRON)
    return str(excinfo.value)


async def test_不合法cron回422且訊息為固定中文句(monkeypatch) -> None:
    err = await _update_with_invalid_cron(monkeypatch)

    assert err.status_code == 422
    assert err.error_code == "DP_SCHED_002"
    # 正向錨點：訊息確實是給使用者看的修正說明，不是空字串或泛用句
    assert err.detail.startswith("cron 表達式不合法")
    assert "0 為週一" in err.detail


async def test_訊息不含套件例外原文與輸入值(monkeypatch) -> None:
    err = await _update_with_invalid_cron(monkeypatch)

    library_message = _library_message()
    assert library_message  # 前提：套件確實有原文可洩漏，否則下一條斷言沒有意義
    assert library_message not in err.detail
    assert "Error validating" not in err.detail
    assert _INVALID_CRON not in err.detail


async def test_例外原文寫入log(monkeypatch, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="app.dp.schedules.service"):
        await _update_with_invalid_cron(monkeypatch)

    records = [r for r in caplog.records if r.name == "app.dp.schedules.service"]
    assert len(records) == 1
    record = records[0]
    assert "SCHDP001" in record.getMessage()
    # 原文走 traceback（有遮罩兜底），不進訊息本體（沒有遮罩），見 sti-backend-logging.md
    assert record.exc_info is not None
    assert isinstance(record.exc_info[1], ValueError)
    assert str(record.exc_info[1]) == _library_message()
    assert _library_message() not in record.getMessage()
