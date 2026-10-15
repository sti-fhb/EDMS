"""速率限制（T015）純單元測試：滑動視窗 + IP dependency（注入 now，不連 DB）。"""

import pytest

from app.core.exceptions import AppError
from app.core.rate_limit import SlidingWindowCounter, SlidingWindowRateLimiter, rate_limit_by_ip
from app.core.request_context import set_client_ip

pytestmark = pytest.mark.unit


def test_init_rejects_non_positive_args():
    """建構子拒絕非正數門檻 / 視窗（防限流器被誤設為失效或永久拒絕）。"""
    with pytest.raises(ValueError, match="必須為正數"):
        SlidingWindowRateLimiter(max_requests=0, window_seconds=60)
    with pytest.raises(ValueError, match="必須為正數"):
        SlidingWindowRateLimiter(max_requests=1, window_seconds=0)


def test_allows_within_limit():
    """視窗內未達上限皆放行。"""
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        limiter.hit("k", now=100.0)  # 同一瞬間 3 次剛好達上限、皆放行


def test_rejects_over_limit():
    """達上限後再一次 → 429 COMMON_429。"""
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        limiter.hit("k", now=100.0)
    with pytest.raises(AppError) as exc:
        limiter.hit("k", now=100.0)
    assert exc.value.status_code == 429
    assert exc.value.error_code == "COMMON_429"


def test_window_slides_allows_again():
    """視窗滑動後（舊時間戳過期）重新放行。"""
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)
    limiter.hit("k", now=100.0)
    limiter.hit("k", now=100.0)
    with pytest.raises(AppError):
        limiter.hit("k", now=130.0)  # 仍在視窗內（100~160）→ 拒
    limiter.hit("k", now=161.0)  # 前兩筆（100）已滑出視窗 → 放行


def test_keys_are_independent():
    """不同 key 各自獨立計數。"""
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    limiter.hit("a", now=100.0)
    limiter.hit("b", now=100.0)  # 不受 a 影響
    with pytest.raises(AppError):
        limiter.hit("a", now=100.0)


def test_rejected_hit_not_counted():
    """被拒的請求不佔用配額：視窗滑動後仍以原始有效筆數計算。"""
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    limiter.hit("k", now=100.0)
    for _ in range(5):
        with pytest.raises(AppError):
            limiter.hit("k", now=120.0)  # 連續被拒，不應累加
    # 首筆（100）滑出後應立即放行，證明被拒的 5 次未被記錄
    limiter.hit("k", now=161.0)


def test_sweep_reclaims_stale_keys():
    """一次性 key 於視窗過期後應被 sweep 回收，outer dict 不無限成長。"""
    limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60)
    # 觸發一次 sweep 前先塞遠早於視窗的一次性 key，sweep 時應全數清掉
    for i in range(1500):
        limiter.hit(f"acct:user{i}", now=100.0 + i * 0.001)
    # 再前進到讓上述所有時間戳都滑出視窗，並持續 hit 直到跨過 sweep 週期
    for i in range(1500):
        limiter.hit(f"acct:late{i}", now=100_000.0 + i * 0.001)
    # 早期一次性 key 應已被 sweep 回收（不再殘留），outer dict 有界（遠小於 3000 總 key）
    assert not any(k.startswith("acct:user") for k in limiter._hits)
    assert len(limiter._hits) < 3000


def test_max_keys_hard_cap_fail_closed():
    """達 outer dict 硬上限且無可回收桶時，新 key 一律拒絕（界定記憶體上界）。"""
    limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60, max_keys=3)
    # 3 個各自仍在視窗內的 key 填滿字典
    for i in range(3):
        limiter.hit(f"k{i}", now=100.0)
    # 第 4 個新 key：sweep 無可回收（全在視窗內）→ fail-closed 429
    with pytest.raises(AppError) as exc:
        limiter.hit("k3", now=100.0)
    assert exc.value.status_code == 429
    # 既有 key 仍可正常計數（未被硬上限誤擋）
    limiter.hit("k0", now=100.0)


async def test_rate_limit_by_ip_dependency():
    """IP dependency 依 get_client_ip 組 key，超限拋 429。"""
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    dep = rate_limit_by_ip(limiter, scope="login")
    set_client_ip("1.2.3.4")
    try:
        await dep()  # 首次放行
        with pytest.raises(AppError) as exc:
            await dep()
        assert exc.value.status_code == 429
    finally:
        set_client_ip(None)


async def test_rate_limit_by_ip_unknown_client():
    """無 client IP（get_client_ip 回 None）時以 fallback key 計數，不拋錯。"""
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    dep = rate_limit_by_ip(limiter, scope="login")
    set_client_ip(None)
    await dep()
    with pytest.raises(AppError):
        await dep()


async def test_scope_prefix_isolates_endpoints():
    """同一 IP、不同 scope 各自獨立配額（scope 前綴防污染）。"""
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    login_dep = rate_limit_by_ip(limiter, scope="login")
    forgot_dep = rate_limit_by_ip(limiter, scope="forgot-password")
    set_client_ip("1.2.3.4")
    try:
        await login_dep()
        await forgot_dep()  # 不同 scope，不受 login 影響
        with pytest.raises(AppError):
            await login_dep()
    finally:
        set_client_ip(None)


async def test_dependency_resolves_in_fastapi_app():
    """回歸測試：dependency 掛上真實 FastAPI 路由能正常解析（非 422），並實際限流。"""
    import httpx
    from fastapi import Depends, FastAPI

    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    app = FastAPI()

    @app.get("/ping", dependencies=[Depends(rate_limit_by_ip(limiter, scope="ping"))])
    async def ping():
        return {"ok": True}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.get("/ping")
        second = await client.get("/ping")
    assert first.status_code == 200  # 非 422：dependency 正確解析、未被當成 query 參數
    assert second.status_code == 429


# ── SlidingWindowCounter（#234 抽出）────────────────────────────────────────
# ⚠️ 本組刻意直接測 counter 而非只靠 limiter 間接帶到：三個性質與 limiter **方向相反**
#   （不拋、fail-open、上限由呼叫端決定），靠 limiter 的測試一條都驗不到。
#   2026-10-14 code review MEDIUM-4 指出此缺口。


def test_counter_count_不新增_key():
    """`count` 必須無副作用。

    原本的 `_hits` 是 defaultdict——照抄 `self._hits[key]` 會在 `max_keys` 檢查**之前**
    憑空建桶，等於讓任何人以不重複的 key 繞過記憶體上界。
    """
    counter = SlidingWindowCounter(window_seconds=60)
    assert counter.count("nobody", now=100.0) == 0
    assert "nobody" not in counter._hits, "count 不得建立 key"


def test_counter_視窗過期後歸零():
    """滾動視窗：時間推進超過 window 後，舊紀錄不再計入。

    #234 的「每日上限」靠的就是這個性質，而整合測試從不推進時間
    （`now` 無法自 router 注入），少了本條則「滾動」這個承諾零覆蓋。
    """
    counter = SlidingWindowCounter(window_seconds=60)
    for i in range(3):
        assert counter.try_record("k", now=100.0 + i)
    assert counter.count("k", now=150.0) == 3
    # 邊界：now=161 時 cutoff=101，第三筆（102）仍在視窗內 ⇒ 還剩 1。
    # 這一條順便釘住「滑出是逐筆的、不是整桶丟掉」。
    assert counter.count("k", now=161.0) == 1
    assert counter.count("k", now=163.0) == 0, "全部滑出後歸零（額度於 24 小時後釋放）"


def test_counter_key_空間滿時_fail_open():
    """與 limiter **刻意相反**：滿時回 False 而不拋，呼叫端照常放行。

    拋 429 會讓 `/register` 多出一種回應（新的列舉面）；fail-closed 則讓大量不同 Email
    的嘗試把表塞滿、反而使正常註冊被拒（以 DoS 換 DoS）。
    """
    counter = SlidingWindowCounter(window_seconds=60, max_keys=2)
    assert counter.try_record("a", now=100.0)
    assert counter.try_record("b", now=100.0)
    assert counter.try_record("c", now=100.0) is False, "滿時回 False"
    assert counter.count("c", now=100.0) == 0, "未被記錄 ⇒ 不佔額度，呼叫端視為未達上限"
