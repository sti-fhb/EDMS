"""ET 授權純函式與 `require_et_roles` dependency（T026；Security Review M3）。

`authz` 全為純函式、`require_et_roles` 之判定不碰 DB（角色集由上游 `get_et_context`
注入），故一律 unit。
"""

import pytest

from app.core.exceptions import AppError
from app.et.deps import EtContext, require_et_roles
from app.et.roles.authz import (
    ET_ADMIN,
    ET_STUDENT,
    ET_TEACHER,
    can_manage_course,
    has_any_et_role,
    has_any_of,
    has_role,
    is_admin,
)

pytestmark = pytest.mark.unit


class TestPureFunctions:
    def test_has_any_et_role(self) -> None:
        assert has_any_et_role(frozenset({ET_STUDENT})) is True
        assert has_any_et_role(frozenset()) is False

    def test_has_role(self) -> None:
        roles = frozenset({ET_TEACHER})
        assert has_role(roles, ET_TEACHER) is True
        assert has_role(roles, ET_ADMIN) is False

    def test_has_any_of_取聯集(self) -> None:
        roles = frozenset({ET_STUDENT})
        assert has_any_of(roles, frozenset({ET_ADMIN, ET_STUDENT})) is True
        assert has_any_of(roles, frozenset({ET_ADMIN, ET_TEACHER})) is False

    def test_is_admin(self) -> None:
        assert is_admin(frozenset({ET_ADMIN})) is True
        assert is_admin(frozenset({ET_TEACHER, ET_STUDENT})) is False

    def test_can_manage_course_教師或管理者(self) -> None:
        assert can_manage_course(frozenset({ET_TEACHER})) is True
        assert can_manage_course(frozenset({ET_ADMIN})) is True
        assert can_manage_course(frozenset({ET_STUDENT})) is False


class TestRequireEtRoles:
    """M3：端點層授權 dependency——讓漏授權變成「沒掛 dependency」而非「掛了沒比對」。"""

    async def test_具備所需角色時放行(self) -> None:
        dep = require_et_roles(ET_ADMIN)
        ctx = EtContext(user_id="U1", roles=frozenset({ET_ADMIN}))
        assert await dep(ctx=ctx) is ctx

    async def test_多個所需角色取聯集(self) -> None:
        dep = require_et_roles(ET_ADMIN, ET_TEACHER)
        ctx = EtContext(user_id="U2", roles=frozenset({ET_TEACHER}))
        assert await dep(ctx=ctx) is ctx

    async def test_不具所需角色時_403(self) -> None:
        """學員（每個帳號都有）不得因此通過管理者專屬端點。"""
        dep = require_et_roles(ET_ADMIN)
        ctx = EtContext(user_id="U3", roles=frozenset({ET_STUDENT}))
        with pytest.raises(AppError) as e:
            await dep(ctx=ctx)
        assert e.value.status_code == 403
        assert e.value.error_code == "ET_AUTH_001"

    async def test_未指定角色時一律拒絕(self) -> None:
        """`require_et_roles()` 無參數＝空集合，任何人皆不符——fail-closed。"""
        dep = require_et_roles()
        ctx = EtContext(user_id="U4", roles=frozenset({ET_ADMIN}))
        with pytest.raises(AppError):
            await dep(ctx=ctx)
