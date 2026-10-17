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


def can_download_obsolete_file(roles: Iterable[str], assigned_reviewer: str | None, user_id: str) -> bool:
    """廢止附件下載權（US8，SA 裁示 Q1=C）：僅 **DM_ADMIN** 或**該送審之指定審核者**。

    附件屬稽核佐證公文、非文件本體，採最小揭露——**發起人本人與一般閱覽者皆不可下載**。

    ## 🔴 唯一真相：顯示條件與授權必須呼叫同一支

    兩個呼叫端：

    - `dm/review/center_service.prepare_obsolete_file` —— 決定要不要擋成 403（**權威**）
    - `dm/detail/service.get_detail` —— 決定 `ObsoleteInfo.can_download_attachment`，
      前端據以渲染「下載廢止附件」鈕

    ⛔ **不要在任一端另寫一份判定。** #615 修的正是這個毛病：前端原本只看
    `has_attachment` 就渲染按鈕，比後端寬，於是閱覽者會同時看到「所有版本僅可預覽、
    不開放下載」的 banner 和一顆按下去回 403 的鈕。

    ### 什麼擋得住你、什麼擋不住（2026-10-17 變異實測）

    | 做法 | 會不會被擋 |
    |---|---|
    | 另寫一份**分岔**的判定 | ✅ `test_dm_obsolete_flow` 的授權測試會紅 |
    | 某一端**完全改用**自寫版、不再呼叫本函式 | ✅ 但靠的是 **ruff `F401`**（import 變孤立），不是測試 |
    | 另寫一份**行為相同**的判定（複製貼上）| 🔴 **沒有任何東西會紅**——實測 43 條全過 |

    最後一列是本函式存在的理由：複製當下不會壞，**壞在下一個人只改其中一邊**。
    真正的保險是這段文字與上面兩個呼叫端的註解，不是自動化。

    ⚠️ `assigned_reviewer` 可能為 `None`（未指派）——此時不得與任何 `user_id` 相等而意外放行。

    Args:
        roles:             使用者之 DM 角色集。
        assigned_reviewer: **該筆**廢止送審的指定審核者 USER_ID；未指派為 None。
        user_id:           目前使用者 USER_ID。

    Returns:
        可下載為 True。後端 403 仍為唯一權威，本函式只是讓前端**不要顯示按不動的鈕**。
    """
    return has_role(roles, DM_ADMIN) or (assigned_reviewer is not None and assigned_reviewer == user_id)


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
        AppError: 移除自己之管理者角色（403 DM_ROLE_001；DP 端映射 DP-MSG-DP02-001）。
    """
    if operator_id == target_id and DM_ADMIN not in set(roles_after):
        raise AppError(status_code=403, detail="無法停用自己之管理者角色", error_code="DM_ROLE_001")
