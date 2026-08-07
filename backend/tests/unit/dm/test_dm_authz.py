"""DM 授權工具單元測試（純邏輯，不需 DB）。"""

import pytest

from app.core.exceptions import AppError
from app.dm.roles.authz import (
    DM_ADMIN,
    DM_EDITOR,
    ensure_not_self_admin_removal,
    ensure_reviewer_not_author,
    has_any_dm_role,
    has_role,
)


def test_has_any_dm_role():
    assert has_any_dm_role({DM_EDITOR}) is True
    assert has_any_dm_role({"ET_STUDENT"}) is False  # ET 角色不算 DM 角色
    assert has_any_dm_role(set()) is False


def test_has_role_union():
    roles = {DM_EDITOR, "DM_REVIEWER"}
    assert has_role(roles, DM_EDITOR) is True
    assert has_role(roles, "DM_REVIEWER") is True
    assert has_role(roles, DM_ADMIN) is False


def test_ensure_reviewer_not_author_rejects_self():
    with pytest.raises(AppError) as e:
        ensure_reviewer_not_author("u1", "u1")
    assert e.value.error_code == "DM_REVIEW_001" and e.value.status_code == 422


def test_ensure_reviewer_not_author_allows_other():
    ensure_reviewer_not_author("reviewer", "author")  # 不拋錯


def test_self_admin_removal_blocked():
    """operator 對自己儲存後不含 DM_ADMIN → 擋下（DM_ROLE_001）。"""
    with pytest.raises(AppError) as e:
        ensure_not_self_admin_removal("admin1", "admin1", {DM_EDITOR})
    assert e.value.error_code == "DM_ROLE_001" and e.value.status_code == 403


def test_self_admin_keep_allowed():
    """operator 對自己保留 DM_ADMIN → 允許。"""
    ensure_not_self_admin_removal("admin1", "admin1", {DM_ADMIN, DM_EDITOR})


def test_admin_removing_others_allowed():
    """管理者移除他人之 DM_ADMIN → 允許（僅擋自我移除）。"""
    ensure_not_self_admin_removal("admin1", "admin2", {DM_EDITOR})
