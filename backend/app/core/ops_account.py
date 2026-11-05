"""廠商維運帳號識別（#927）。

院內交付後系統管理權交由院方；為避免院方更換管理員密碼後廠商無法維運，以 migration
建立固定 USER_ID 的維運帳號（`36af0d3943bf`），並在各處保護它不被停用、改名或拿掉預設角色。

放在 core 而非 DP：DM / ET 的角色指派服務也要判斷「目標是不是維運帳號」，而模組不得
import DP 的內部模組（見 sti-backend-boundaries）。**角色碼不放這裡**——DP 不得認識模組
角色碼，各模組的預設角色由模組自己定義（`dm/roles/authz.py`、`et/roles/assign_service.py`）。
"""

OPS_USER_ID = "edmsops"


def is_ops_account(user_id: str) -> bool:
    """是否為廠商維運帳號。"""
    return user_id == OPS_USER_ID
