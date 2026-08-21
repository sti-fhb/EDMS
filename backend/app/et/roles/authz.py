"""ET 角色授權工具（T026）。

比照 `app/dm/roles/authz.py`：於存取閘（`app/et/deps.py`）注入之角色集上做**細粒度**
檢核。純函式、不碰 DB，故可完全以 unit test 驗證。

**受訓單位標籤不涉權限判定**——標籤僅供課程自動邀請使用（per et/spec.md
§跨模組共用規則：「標籤僅供邀請不涉權限」）。
"""

from app.et.constants import ROLE_ADMIN, ROLE_STUDENT, ROLE_TEACHER

# 對外重新匯出，供 gate / service 引用時不必再 import constants
ET_ADMIN = ROLE_ADMIN
ET_TEACHER = ROLE_TEACHER
ET_STUDENT = ROLE_STUDENT


def has_any_et_role(roles: frozenset[str]) -> bool:
    """是否具任一 ET 角色（module-callbacks §4 / SRVET005 之判定核心）。"""
    return bool(roles)


def has_role(roles: frozenset[str], required: str) -> bool:
    """是否具指定角色。"""
    return required in roles


def has_any_of(roles: frozenset[str], required: frozenset[str]) -> bool:
    """是否具 required 中任一角色（多重角色權限取聯集）。"""
    return bool(roles & required)


def is_admin(roles: frozenset[str]) -> bool:
    """是否為 ET 管理者（module-callbacks §1 / SRVET001 之判定核心）。"""
    return ET_ADMIN in roles


def can_manage_course(roles: frozenset[str]) -> bool:
    """是否可進行課程安排作業（教師或管理者）。

    課程之**擁有權**另行判定（`ET_COURSE.OWNER_ID`）——本函式僅判角色門檻，
    他人課程之唯讀限制由 service 層以 owner 比對處理。
    """
    return has_any_of(roles, frozenset({ET_ADMIN, ET_TEACHER}))
