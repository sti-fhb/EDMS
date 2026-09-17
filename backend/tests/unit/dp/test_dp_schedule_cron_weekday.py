"""`CronTrigger.from_crontab` 的 day-of-week 語意（#332）。

這是一條**特徵測試**：它不驗我們的商業邏輯，驗的是我們依賴的那條語意仍然成立。

排程引擎以 `CronTrigger.from_crontab` 驅動（`app/dp/schedules/scheduler.py`），而
**APScheduler 的 day-of-week 以週一為 0**，不做標準 crontab（週日為 0）的轉換。所有
週排程的 cron 值都建立在這條語意上；若日後升級 APScheduler 改了它，全部週排程會整批
平移一天，而且不會有任何東西報錯——只會「那份週報怎麼星期二才來」。

前端 `frontend/src/dp/schedules/cron.ts` 的星期表同樣依賴這條語意，兩側必須一致。

不需固定基準日：`next_run` 取的是「現在起」的下次觸發，而 `0 10 * * N` 的下次觸發
落在哪一個星期幾是恆定的，與今天是星期幾無關。
"""

import pytest

from app.dp.schedules.scheduler import next_run, validate_cron

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("dow", "expected_weekday", "label"),
    [(0, 0, "週一"), (1, 1, "週二"), (2, 2, "週三"), (6, 6, "週日")],
)
def test_day_of_week以週一為零(dow: int, expected_weekday: int, label: str) -> None:
    """dow=0 是週一，不是週日。

    這條若紅了，代表 APScheduler 換成了標準 crontab 語意——此時**所有週排程的 cron 值
    都要跟著改**，不是改這條測試。
    """
    fire = next_run(f"0 10 * * {dow}")

    assert fire is not None
    assert fire.weekday() == expected_weekday, f"dow={dow} 應觸發於{label}，實際落在 {fire:%Y-%m-%d}"
    assert (fire.hour, fire.minute) == (10, 0)


def test_dow為七直接被拒而非視為週日() -> None:
    """標準 crontab 接受 `7` 為週日，APScheduler 不接受（max 6）。

    這是「它不是標準 crontab」最短的旁證，也是管理者在後台輸入 `0 10 * * 7` 會拿到
    422 而非靜默跑在週日的原因。
    """
    with pytest.raises(ValueError):
        validate_cron("0 10 * * 7")
