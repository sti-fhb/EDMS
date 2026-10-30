"""速率限制（T015）。

行程內記憶體滑動視窗，防自動化程式對登入 / 忘記密碼 / 密碼變更端點暴力嘗試
（research §10）。按「來源 IP + 帳號」限流，超限回 429。EDMS 預設單一實例，
行程內計數即足、不引入 Redis；帳號鎖定（5 次錯誤）為第二層防線（見 DP_USER）。
"""

import logging
import time
from collections import Counter, defaultdict, deque
from collections.abc import AsyncGenerator, Awaitable, Callable

from fastapi import Depends

from app.core.auth import JwtPayload, get_jwt_payload
from app.core.exceptions import AppError
from app.core.request_context import get_client_ip

# research §10 預設門檻（如 10 次 / 分鐘）；實際套用門檻由各端點於套用時決定。
# TODO(#16): 若未來需免重新部署即可調門檻（如戰時降限），改讀 DP_PARAM。
LOGIN_RATE_MAX = 10
RATE_WINDOW_SECONDS = 60

# 註冊端點專用門檻（#44）。與登入解耦：在此之前註冊沿用 LOGIN_RATE_MAX，任何人為了排查
# 登入問題而放寬登入門檻，會連帶把匿名建帳號一起放寬且無人察覺——本常數切斷該隱性連動。
#
# 值取 30（**較登入寬鬆**）的理由：自助註冊是本系統的主要入口，而 IP 維度無法區分
# 「一個攻擊者狂送」與「一批使用者各送一次」。內部平台的使用者常共用同一對外 IP
# （教室 / 辦公室 NAT），批次到職時 40 人同時註冊屬正常尖峰；門檻若收在 5，每分鐘只有
# 5 人進得去，其餘看到「操作過於頻繁」而無從自救（訊息不指向真正原因）。
#
# 同一 Email 的重複註冊**不靠本門檻**把關：register 成功即由 600 秒寄信冷卻
# （VerifySendCooldown，#74）鎖住該 Email，較本門檻的 60 秒視窗嚴格得多。帳號維度的
# hit 僅剩「失敗請求（422 / 409 皆不 record 冷卻）」一段殘餘作用，而探測某 Email 狀態
# 只需一個請求，收緊到 5 或放寬到 30 皆無實質差別，故不為此另設較嚴的帳號維度門檻。
#
# ⚠️ 原本記在此處的代價（「放寬到 30 使打飽 event loop 所需的 IP 數從 58 降到約 10」）
# **已不再成立，兩個前提都被後續變更移除**：#214 把 bcrypt 移出 event loop（並加併發閘），
# #212 讓註冊端點完全不做密碼運算。註冊現在是匿名者「無前提即可觸發 bcrypt」的**零個**入口
# ——密碼運算已全數移到需持有效 token 的設定密碼端點（見 SET_PASSWORD_RATE_MAX）。
# 保留這段是因為「安全門檻的理由過期」比「沒有理由」更危險：若日後有人把任何密碼運算加回
# 註冊路徑，30 這個值必須連帶重新推導。
REGISTER_RATE_MAX = 30

# 設定密碼端點門檻（#212）：/verify-email（US2 自助註冊驗證）與 /activate-account（US4 邀請啟用）。
#
# 為何不沿用 LOGIN_RATE_MAX（10）：#212 之後這兩個端點承載的是**會重試的互動式表單**——
# 密碼太弱、兩次不一致、超過 72 bytes 都各佔一個名額（限流是 dependency，在 handler 之前執行），
# 使用者填錯兩次就燒掉 3/10。而 REGISTER_RATE_MAX 的 NAT 論述逐字適用於此：批次到職 40 人
# 同時點連結設密碼時，一個對外 IP 每分鐘只有 10 次機會（含重試）。
#
# 放寬不增加 CPU 曝險：這兩個端點的 bcrypt 必須先通過「token 有效 + KIND 相符 + 未逾期 +
# 兩次一致 + 複雜度」，即每次雜湊都需要一個寄到攻擊者能收信的信箱的有效 token，且 token 成功
# 即被消費（列刪除）。真正的 CPU 防線是 password_hashing 的併發閘（#214），不是本門檻。
#
# 兩個端點共用同一常數是刻意的：#212 之後它們是同一段程式碼（activation.activate_with_new_password），
# 只差 expected_kind，門檻不同會是意外而非決定。
SET_PASSWORD_RATE_MAX = 30

# 匯出端點門檻（#833 B4）：每位使用者 / 每個 IP 每分鐘。比照 ET 週報匯出（`et/reports/router.py`）。
# 匯出一次就整批撈資料、組 CSV，全程佔住一條 DB 連線，而連線池只有 15 條、後端只有一個 worker；
# 正常使用不會連打。IP 維度放寬到不誤傷同一 NAT 出口的同事，擋的是多開帳號繞過使用者維度。
EXPORT_USER_RATE_MAX = 10
EXPORT_IP_RATE_MAX = 60

# 每人同時進行中的匯出上限，全部匯出端點共用（#833 security review M-1，2026-10-30 使用者裁示）。
# 上面兩個門檻算的是「每分鐘幾次」，擋不住同一秒送出一批：三支 DM 匯出各 10 次就是 30 條連線，
# 超過連線池的 15 條。前端每個匯出按鈕在進行中會停用，正常使用一次只有一支。
# ⚠️ 只限單一帳號，不設全站上限（使用者裁示）：多位管理者同時匯出時不互相擋。
EXPORT_MAX_CONCURRENT_PER_USER = 1
_exports_in_flight: Counter[str] = Counter()

# 每處理 N 次 hit 掃描一次全桶、清除視窗外「已老化」空桶（key 由使用者可控的帳號組成，
# 須主動回收，不能只靠被動觸碰同一 key）。注意：sweep 僅回收已過期桶，視窗內工作集大小
# 另由 _MAX_KEYS 硬上限界定（見下）。
_SWEEP_EVERY = 1000

# outer dict 硬上限：達上限時先 sweep 回收，仍滿則 fail-closed 拒新 key，
# 取得真正的記憶體上界（縱深防禦，即使上游 IP 來源被偽造亦不致無限成長）。
_DEFAULT_MAX_KEYS = 100_000

logger = logging.getLogger(__name__)


class SlidingWindowCounter:
    """滑動視窗計數器：**只數，不判上限、不拋例外**。

    與下方 `SlidingWindowRateLimiter` 共用同一份視窗 / 回收邏輯（後者組合本類別），
    分開是因為三個性質**刻意相反**，不是風格差異：

    | | 本類別 | SlidingWindowRateLimiter |
    |---|---|---|
    | 上限 | 由呼叫端**於請求時**決定（如讀 DP_PARAM）| 建構時固定 |
    | 達上限 | 呼叫端自理（註冊路徑需**靜默**）| 拋 429 |
    | key 空間滿 | **fail-open**（不記、照常放行）| fail-closed（拒新 key）|

    ⛔ **三者都不要「順手統一」。** 達上限拋 429 會讓 `/register` 多出一種回應，
    等於把 #345 / #346 關掉的列舉面從另一個角度打開；key 空間滿時 fail-closed 則會
    讓大量不同 Email 的嘗試把表塞滿、反而使正常註冊被拒（以 DoS 換 DoS）。
    fail-open 的取捨比照 `core/cooldown.py`（該檔檔頭有同樣的既有裁示）。
    """

    def __init__(self, window_seconds: float, max_keys: int = _DEFAULT_MAX_KEYS) -> None:
        if window_seconds <= 0 or max_keys <= 0:
            raise ValueError("window_seconds、max_keys 必須為正數")
        self._window = window_seconds
        self._max_keys = max_keys
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._since_sweep = 0

    def _sweep(self, now: float) -> None:
        """清除所有已滑出視窗而變空的桶，回收使用者可控 key 佔用的記憶體。"""
        cutoff = now - self._window
        empty: list[str] = []
        for key, bucket in self._hits.items():
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if not bucket:
                empty.append(key)
        for key in empty:
            del self._hits[key]

    def _tick(self, now: float) -> None:
        self._since_sweep += 1
        if self._since_sweep >= _SWEEP_EVERY:
            self._sweep(now)
            self._since_sweep = 0

    def count(self, key: str, *, now: float | None = None) -> int:
        """視窗內目前的請求數。**無副作用**：不新增 key、不記錄。

        ⚠️ 刻意用 `self._hits.get(key)` 而非 `self._hits[key]`——後者是 defaultdict，
        會在 `max_keys` 檢查**之前**憑空建桶，等於讓任何人以不重複的 key 繞過記憶體上界。
        """
        current = time.monotonic() if now is None else now
        self._tick(current)
        bucket = self._hits.get(key)
        if bucket is None:
            return 0
        cutoff = current - self._window
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        return len(bucket)

    def try_record(self, key: str, *, now: float | None = None) -> bool:
        """記錄一次；成功回 True。key 空間已滿且為新 key 時回 **False 而不拋**。"""
        current = time.monotonic() if now is None else now
        self._tick(current)
        if key not in self._hits and len(self._hits) >= self._max_keys:
            self._sweep(current)
            if len(self._hits) >= self._max_keys:
                # 🔴 觸頂必留痕（2026-10-14 Security MEDIUM-1）。fail-open 代表「這個 key 從此
                # 記不進表 ⇒ count 恆 0 ⇒ 呼叫端的上限對它完全失效」，而那是**無聲**的：
                # 功能看起來一切正常，只是某一批 key 的保護消失了。
                #
                # ⚠️ 本類別的飽和門檻比 `core/cooldown.py` 低約一個量級，因為視窗長得多：
                # cooldown 保留 3,600 秒 → 填滿 100k 需 27.8 key/s（約 28 個 IP）；
                # 本 counter 若以 86,400 秒視窗使用 → 僅需 1.16 key/s（**約 2～3 個 IP 持續一天**）。
                # 記憶體上界約 104 MB（100k × deque+str+float 實測），部署估算時需納入。
                logger.warning(
                    "SlidingWindowCounter key 空間已滿（上限 %s），本次不記錄；"
                    "該 key 的上限保護自此失效 event=counter_key_space_full",
                    self._max_keys,
                )
                return False
        bucket = self._hits[key]
        cutoff = current - self._window
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        bucket.append(current)
        return True


class SlidingWindowRateLimiter:
    """行程內滑動視窗限流器（單一實例、非分散式）。

    以 key（如 `login:ip:1.2.3.4` / `login:acct:a@b.c`）分桶記錄請求時間戳，
    視窗內請求數達上限即拒。`hit` 為同步、無 await（asyncio 單執行緒下對單一 key
    的讀改寫不會被其他協程插斷），故不需鎖；前提為應用以單一 process 運行。

    視窗與回收邏輯委派 `SlidingWindowCounter`；本類別只加「上限判定 + 拋 429」。
    ⚠️ 委派後 sweep 觸發頻率約為原本的兩倍（`hit` 內 `count` 與 `try_record` 各 tick 一次）。
    那是回收成本的變化、不是行為變化：sweep 只刪已過期的空桶。
    """

    def __init__(self, max_requests: int, window_seconds: float, max_keys: int = _DEFAULT_MAX_KEYS) -> None:
        if max_requests <= 0 or window_seconds <= 0 or max_keys <= 0:
            raise ValueError("max_requests、window_seconds、max_keys 必須為正數")
        self._max = max_requests
        self._counter = SlidingWindowCounter(window_seconds, max_keys)

    @property
    def _hits(self) -> dict[str, deque[float]]:
        """內部桶。**測試用的清理點**（13 處 `_hits.clear()` / `.pop()` 分散於 6 個測試檔）。

        抽出 `SlidingWindowCounter` 後儲存下移一層，本屬性代理回去，使既有清理點不必跟著搬——
        它們清的是同一份 dict。少了這個代理，一次內部重構就要改 6 個無關檔案，
        而下一次重構再改一輪。
        """
        return self._counter._hits

    def hit(self, key: str, *, now: float | None = None) -> None:
        """記錄一次請求；視窗內達上限則拋 AppError(429)。

        Args:
            key: 限流分桶鍵（含 scope + 維度，如 `login:ip:...`）。
            now: 目前單調時間（秒）；預設 time.monotonic()，測試可注入以決定性驗證。

        Raises:
            AppError: 視窗內請求數已達上限，或 key 空間已滿（429 / COMMON_429）。
                被拒的請求不佔配額。後者為 fail-closed，界定記憶體上界。
        """
        current = time.monotonic() if now is None else now
        if self._counter.count(key, now=current) >= self._max:
            raise AppError(status_code=429, detail="操作過於頻繁，請稍後再試", error_code="COMMON_429")
        if not self._counter.try_record(key, now=current):
            raise AppError(status_code=429, detail="操作過於頻繁，請稍後再試", error_code="COMMON_429")


def rate_limit_by_ip(limiter: SlidingWindowRateLimiter, scope: str) -> Callable[[], Awaitable[None]]:
    """產生「依來源 IP 限流」的 FastAPI dependency。

    IP 取自 `get_client_ip()`（由 main.py client_ip_middleware 設定，與稽核日誌 IP 一致）。
    該 IP 預設為不可偽造的連線對端；僅在部署方設定 `TRUSTED_PROXY_COUNT` 時才採信
    X-Forwarded-For 的固定段位（#23，見 app/core/client_ip.py）。
    scope 前綴使不同端點的計數互不污染。

    Args:
        limiter: 共用的限流器實例。
        scope: 端點識別（如 "login"），組入 key 前綴。

    Returns:
        無參數的 async dependency；FastAPI 直接解析（不需注入 Request）。

    Raises:
        AppError: 該 IP 於 scope 內超過限流門檻時（429 / COMMON_429）。
    """

    async def _dependency() -> None:
        ip = get_client_ip() or "unknown"
        limiter.hit(f"{scope}:ip:{ip}")

    return _dependency


def rate_limit_by_user(limiter: SlidingWindowRateLimiter, scope: str) -> Callable[..., Awaitable[None]]:
    """產生「依登入者限流」的 FastAPI dependency（#833 B4）。

    以 token 的 `sub` 分桶，認證失敗的請求在 `get_jwt_payload` 就被擋下、不佔名額。
    ET 端點請用 `app/et/deps.rate_limit_by_et_user`（依賴 `EtContext`，同時把關 ET 角色）；
    本函式給沒有模組專屬 context 可依賴的端點。通常與 `rate_limit_by_ip` 一起掛，理由見該函式。

    ⚠️ 要排在模組權限閘**之後**（router-level 的閘，或在 route 的 `dependencies` 裡放在前面）。
    本函式只驗「已登入」，排在權限閘之前時，沒有權限的帳號每次 403 之前都已佔掉 IP 名額——
    自助註冊是開的，任何人都能用它把同一 NAT 出口的同事擋成 429。`tests/unit/test_core_export_rate_limit.py`
    的 `test_無權限者不佔名額` 守門。

    Raises:
        AppError: 該使用者於 scope 內超過門檻時（429 / COMMON_429）。
    """

    async def _dependency(payload: JwtPayload = Depends(get_jwt_payload)) -> None:
        limiter.hit(f"{scope}:user:{payload.sub}")

    return _dependency


async def limit_concurrent_exports(payload: JwtPayload = Depends(get_jwt_payload)) -> AsyncGenerator[None, None]:
    """同一人同時進行中的匯出達 `EXPORT_MAX_CONCURRENT_PER_USER` 即回 429（#833）。

    以 yield 依賴持有名額：FastAPI 0.139 在回應**整個送完**之後才執行 yield 之後的收尾
    （同 `core/db.get_db`），所以名額涵蓋查詢、組 CSV、送出的全程——正是佔住 DB 連線的那段。
    handler 拋錯或被取消（客戶端中途斷線）時由 `finally` 歸還。

    與 `upload_auth_precheck` 的同時上傳數一樣以行程內計數：後端固定單一 worker。

    Raises:
        AppError: 同一人已有匯出進行中（429 / COMMON_429）。
    """
    user = payload.sub
    if _exports_in_flight[user] >= EXPORT_MAX_CONCURRENT_PER_USER:
        raise AppError(status_code=429, detail="已有匯出正在進行，請待完成後再試", error_code="COMMON_429")
    _exports_in_flight[user] += 1
    try:
        yield
    finally:
        _exports_in_flight[user] -= 1
        if _exports_in_flight[user] <= 0:
            del _exports_in_flight[user]
