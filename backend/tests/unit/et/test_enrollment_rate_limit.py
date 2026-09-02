"""ET04 邀請碼嘗試限流（US4 / #247）。

## 為何是 unit 而非 integration

限流器是純記憶體的滑動視窗，拿掉真 DB 也驗得了（`.claude/rules/sti-testing.md`
之取捨原則）。

而且用 integration 會**驗不出來**：`tests/integration/conftest.py` 的 `client`
override 對例外呼叫 `db.rollback()`，測試前置資料只 `flush()` 未 commit，因此
第一次失敗的請求（404）就會把 `DP_USER` / `ET_USER_ROLE` 一起回滾掉——後續請求
全部變成 401，永遠打不到限流門檻。單次失敗的測試看不出這件事，連打二十次才會。
"""

import pytest

from app.core.exceptions import AppError
from app.et.deps import EtContext
from app.et.enrollment.router import _ENROLL_RATE_MAX, rate_limit_by_user

pytestmark = pytest.mark.unit


def _ctx(user_id: str) -> EtContext:
    return EtContext(user_id=user_id, roles=frozenset({"STUDENT"}))


class TestEnrollRateLimit:
    async def test_門檻內放行超過則擋(self) -> None:
        """邀請碼只有 8 碼純數字（10^8），而任何已登入者都能打 preview 端點。

        200 / 404 的差異可直接判斷一組碼是否有效，且拿到有效碼即可加入——碼被枚舉
        出來等同繞過整個邀請門檻。
        """
        dep = rate_limit_by_user("test-scope-a")
        ctx = _ctx("brute_forcer")

        for _ in range(_ENROLL_RATE_MAX):
            await dep(ctx)

        with pytest.raises(AppError) as exc:
            await dep(ctx)
        assert exc.value.status_code == 429
        assert exc.value.error_code == "COMMON_429"

    async def test_不同使用者互不影響(self) -> None:
        """依**使用者**而非 IP 分桶。

        攻擊者是已登入帳號，使用者維度才對得上；IP 維度在此既會被同一 NAT 稀釋
        配額，又會讓同辦公室的其他人連坐。
        """
        dep = rate_limit_by_user("test-scope-b")
        for _ in range(_ENROLL_RATE_MAX):
            await dep(_ctx("noisy_user"))

        # 另一位使用者不該因此被擋
        await dep(_ctx("innocent_bystander"))

    async def test_門檻足夠一般使用者連續加入多門課(self) -> None:
        """開學時教師可能一次發數組碼，門檻不能低到擋住正常使用。"""
        assert _ENROLL_RATE_MAX >= 20
