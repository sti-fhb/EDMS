"""DM 模組啟動接線（US1）。

把 DM 提供之各判定閘 / 轉接層 checker 於啟動期註冊進平台 core 之聚合閘，供 DP 呼叫。
於 `main.py` module-level 呼叫一次（比照既有 include_router 接線；未註冊模組閘一律 fail-closed）。
"""

from app.core.module_admin import module_admin_gate
from app.core.module_roles import module_role_gate
from app.dm.roles.gate import dm_has_any_role, dm_is_module_admin

_MODULE = "DM"


def register_dm_module() -> None:
    """註冊 DM 之模組判定閘 checker（§1 is_module_admin / §4 has_any_role）。

    冪等：重複呼叫僅覆蓋同一 checker（供測試重入）。§3 assign provider 之註冊於 Phase 2 追加。
    """
    module_role_gate.register(_MODULE, dm_has_any_role)
    module_admin_gate.register(_MODULE, dm_is_module_admin)
