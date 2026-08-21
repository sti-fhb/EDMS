"""ET 模組啟動接線（#185 T025）。

把 ET 提供之各判定閘 / 轉接層 checker 於啟動期註冊進平台 core 之聚合閘，供 DP 呼叫。
於 `main.py` module-level 呼叫一次（比照 `app/dm/bootstrap.py`；未註冊模組閘一律
fail-closed）。

**本函式是 DP #113（真授權閘）的解鎖條件**——DP 各後台端點目前採暫行案
（任何登入者可存取），正是因為 fail-closed 閘在無模組註冊時會 403 鎖死整個後台。
"""

from app.core.module_admin import module_admin_gate
from app.core.module_assign import module_assign_registry
from app.core.module_provisioning import module_provisioning_gate
from app.core.module_roles import module_role_gate
from app.et.provider import EtAssignProvider
from app.et.roles.gate import et_has_any_role, et_is_module_admin
from app.et.roles.provisioning import grant_default_student_role

_MODULE = "ET"


def register_et_module() -> None:
    """註冊 ET 之四個聚合閘 checker / provider（module-callbacks §1~§4）。

    冪等：重複呼叫僅覆蓋同一 checker / provider（供測試重入）。
    """
    module_role_gate.register(_MODULE, et_has_any_role)  # SRVET005 §4
    module_admin_gate.register(_MODULE, et_is_module_admin)  # SRVET001 §1
    module_provisioning_gate.register(_MODULE, grant_default_student_role)  # SRVET002 §2
    module_assign_registry.register(_MODULE, EtAssignProvider())  # SRVET003/004 §3/§3.1
