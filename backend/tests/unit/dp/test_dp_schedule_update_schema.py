"""`ScheduleUpdate.description` 輸入驗證（對齊 `DP_SCHEDULE.DESCRIPTION VARCHAR(200)`）。"""

import pytest
from pydantic import ValidationError

from app.dp.schedules.schemas import ScheduleUpdate

pytestmark = pytest.mark.unit

_BASE = {"job_name": "平台每日作業", "cron_expr": "0 8 * * *", "is_enabled": True}


def test_說明超過200字元被拒() -> None:
    with pytest.raises(ValidationError):
        ScheduleUpdate(**_BASE, description="字" * 201)


def test_說明剛好200字元可接受() -> None:
    assert ScheduleUpdate(**_BASE, description="字" * 200).description == "字" * 200


def test_說明去頭尾空白() -> None:
    assert ScheduleUpdate(**_BASE, description="  說明  ").description == "說明"


def test_未帶說明時不列入已設定欄位() -> None:
    # service 以 model_fields_set 區分「未帶（維持原值）」與「帶 null（清空）」
    assert "description" not in ScheduleUpdate(**_BASE).model_fields_set
    assert "description" in ScheduleUpdate(**_BASE, description=None).model_fields_set
