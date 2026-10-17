"""DM 授權工具單元測試（純邏輯，不需 DB）。"""

import pytest

from app.core.exceptions import AppError
from app.dm.roles.authz import (
    DM_ADMIN,
    DM_EDITOR,
    DM_VIEWER,
    can_download_obsolete_file,
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


# ── 廢止附件下載權（#615）────────────────────────────────────────
#
# 🔴 這組釘的是「唯一真相」：`review/center_service.prepare_obsolete_file` 的 403 與
# `detail/service` 回給前端的 `can_download_attachment` 都呼叫同一支。兩邊各寫一份正是
# #615 要修的毛病——顯示條件比後端寬，使用者看到一顆按下去回 403 的鈕。

_REVIEWER_ID = "rv01"


def test_廢止附件_管理者可下載():
    assert can_download_obsolete_file({DM_ADMIN}, assigned_reviewer=_REVIEWER_ID, user_id="other") is True


def test_廢止附件_該送審的指定審核者可下載():
    """⚠️ 不可用 is_admin 近似而誤擋他——後端是允許的（SA 裁示 Q1=C）。"""
    assert can_download_obsolete_file({DM_VIEWER}, assigned_reviewer=_REVIEWER_ID, user_id=_REVIEWER_ID) is True


def test_廢止附件_無關閱覽者不可下載():
    assert can_download_obsolete_file({DM_VIEWER}, assigned_reviewer=_REVIEWER_ID, user_id="someone") is False


def test_廢止附件_別場送審的審核者不可下載():
    """只對**該送審**的指定審核者放行；他是別件的審核者不算。"""
    assert can_download_obsolete_file({"DM_REVIEWER"}, assigned_reviewer=_REVIEWER_ID, user_id="rv99") is False


def test_廢止附件_發起人本人也不可下載():
    """附件屬稽核佐證公文、最小揭露——發起人本人亦不在允許名單（SA 裁示 Q1=C）。"""
    assert can_download_obsolete_file({DM_EDITOR}, assigned_reviewer=_REVIEWER_ID, user_id="applicant") is False


def test_廢止附件_無指定審核者時不因_None_而放行():
    """⚠️ `assigned_reviewer` 為 None 時不得與任何 user_id 相等而意外放行。"""
    assert can_download_obsolete_file({DM_VIEWER}, assigned_reviewer=None, user_id="anyone") is False
