"""DM 角色授權共用工具（T015）。

DM 4 角色（DM_ADMIN / DM_EDITOR / DM_REVIEWER / DM_VIEWER）複選、互不互斥、權限取聯集。
提供角色判定 + 「指定審核者排除本人」（US5）+ 「管理者自我保護」（US1）共用檢核。
"""

from collections.abc import Iterable

from app.core.exceptions import AppError

DM_ADMIN = "DM_ADMIN"
DM_EDITOR = "DM_EDITOR"
DM_REVIEWER = "DM_REVIEWER"
DM_VIEWER = "DM_VIEWER"

DM_ROLES = frozenset({DM_ADMIN, DM_EDITOR, DM_REVIEWER, DM_VIEWER})


def has_any_dm_role(roles: Iterable[str]) -> bool:
    """是否具任一 DM 角色（存取閘：無則拒絕進入 DM）。"""
    return bool(set(roles) & DM_ROLES)


def has_role(roles: Iterable[str], role: str) -> bool:
    """是否具指定角色。"""
    return role in set(roles)


def ensure_reviewer_not_author(reviewer_id: str, author_id: str) -> None:
    """指定審核者排除本人（US5 送簽）：審核者＝撰寫者時拒絕。

    Raises:
        AppError: 審核者為撰寫者本人（422 DM_REVIEW_001）。
    """
    if reviewer_id == author_id:
        raise AppError(status_code=422, detail="指定審核者不可為文件撰寫者本人", error_code="DM_REVIEW_001")


def ensure_not_self_admin_removal(operator_id: str, target_id: str, roles_after: Iterable[str]) -> None:
    """管理者自我保護（US1）：operator 不可移除自己之 DM_ADMIN。

    當 operator 對自己（target）儲存後之角色集不含 DM_ADMIN 時視為自我移除管理者。

    Raises:
        AppError: 移除自己之管理者角色（403 DM_ROLE_001；DP 端映射 DP-MSG-DP06-001）。
    """
    if operator_id == target_id and DM_ADMIN not in set(roles_after):
        raise AppError(status_code=403, detail="無法停用自己之管理者角色", error_code="DM_ROLE_001")
