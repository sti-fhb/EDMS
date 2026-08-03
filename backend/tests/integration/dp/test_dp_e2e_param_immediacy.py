"""T054 參數即時性端到端整合測試（SC-008）。

驗證跨服務即時性：US5 維護服務（ParamAdminService）寫入後，各模組實際讀取路徑
SRVDP001（ParamService）**即時反映**最新啟用中清單項——無快取延遲。此為模組業務
下拉 / 產碼 / 檢核所依賴的契約（既有 params 測試多在同一服務內驗，此檔串接寫→讀兩服務）。
另確認 DETAIL_LOCK 之碼建立後不可改（SC-008 後段）。
"""

import pytest

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dp.params.models import DpParamDetail, DpParamMaster
from app.dp.params.schemas import ParamDetailCreate, ParamDetailUpdate
from app.dp.params.service import ParamAdminService, ParamService

pytestmark = pytest.mark.integration

_OP = OperatorInfo(user_id="admin01")


async def _make_master(db, param_id, *, param_type="LIST", detail_lock=False, details=()):
    now = utcnow()
    db.add(
        DpParamMaster(
            param_id=param_id,
            param_name="即時性測試",
            param_type=param_type,
            detail_lock=detail_lock,
            created_user="seed",
            created_date=now,
        )
    )
    await db.flush()
    for key, value, sort_order, is_enabled in details:
        db.add(
            DpParamDetail(
                param_id=param_id,
                param_key=key,
                param_name=value or key,
                param_value=value,
                sort_order=sort_order,
                is_enabled=is_enabled,
                created_user="seed",
                created_date=now,
            )
        )
    await db.flush()


async def test_maintenance_write_immediately_reflected_in_srvdp001(db):
    """US5 寫入（改值 / 停用 / 新增）→ SRVDP001 讀取即時反映，無快取延遲（SC-008）。"""
    await _make_master(
        db, "E2E_IMM", param_type="LIST", details=[("A", "aval", 1, True), ("B", "bval", 2, True)]
    )
    read = ParamService()
    admin = ParamAdminService()

    # 初始：SRVDP001 讀到 A / B
    keys = {item.key for item in await read.get_param_list(db, "E2E_IMM")}
    assert keys == {"A", "B"}
    assert await read.get_param_value(db, "E2E_IMM", "A") == "aval"

    # ① 改值 → SRVDP001 即時讀到新值
    await admin.update_detail(db, param_id="E2E_IMM", param_key="A", data=ParamDetailUpdate(param_value="aval2"), operator=_OP)
    assert await read.get_param_value(db, "E2E_IMM", "A") == "aval2"

    # ② 停用 B → SRVDP001 啟用清單即時排除、單值讀回 None
    await admin.update_detail(db, param_id="E2E_IMM", param_key="B", data=ParamDetailUpdate(is_enabled=False), operator=_OP)
    keys_after = {item.key for item in await read.get_param_list(db, "E2E_IMM", enabled_only=True)}
    assert keys_after == {"A"}
    assert await read.get_param_value(db, "E2E_IMM", "B") is None

    # ③ 新增 C → SRVDP001 即時納入
    await admin.create_detail(
        db, param_id="E2E_IMM", data=ParamDetailCreate(param_key="C", param_name="新項", param_value="cval"), operator=_OP
    )
    keys_final = {item.key for item in await read.get_param_list(db, "E2E_IMM", enabled_only=True)}
    assert keys_final == {"A", "C"}
    assert await read.get_param_value(db, "E2E_IMM", "C") == "cval"


async def test_detail_lock_code_immutable(db):
    """DETAIL_LOCK 清單之碼建立後不可新增 / 變更（SC-008；DP_PARAM_002）。"""
    await _make_master(db, "E2E_LOCKED", param_type="LIST", detail_lock=True, details=[("FIXED", "固定", 1, True)])
    with pytest.raises(AppError) as exc:
        await ParamAdminService().create_detail(
            db, param_id="E2E_LOCKED", data=ParamDetailCreate(param_key="NEW", param_name="新碼"), operator=_OP
        )
    assert exc.value.status_code == 403 and exc.value.error_code == "DP_PARAM_002"