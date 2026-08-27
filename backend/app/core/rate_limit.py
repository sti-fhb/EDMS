"""速率限制（T015）。

行程內記憶體滑動視窗，防自動化程式對登入 / 忘記密碼 / 密碼變更端點暴力嘗試
（research §10）。按「來源 IP + 帳號」限流，超限回 429。EDMS 預設單一實例，
行程內計數即足、不引入 Redis；帳號鎖定（5 次錯誤）為第二層防線（見 DP_USER）。
"""

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

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

# 每處理 N 次 hit 掃描一次全桶、清除視窗外「已老化」空桶（key 由使用者可控的帳號組成，
# 須主動回收，不能只靠被動觸碰同一 key）。注意：sweep 僅回收已過期桶，視窗內工作集大小
# 另由 _MAX_KEYS 硬上限界定（見下）。
_SWEEP_EVERY = 1000

# outer dict 硬上限：達上限時先 sweep 回收，仍滿則 fail-closed 拒新 key，
# 取得真正的記憶體上界（縱深防禦，即使上游 IP 來源被偽造亦不致無限成長）。
_DEFAULT_MAX_KEYS = 100_000


class SlidingWindowRateLimiter:
    """行程內滑動視窗限流器（單一實例、非分散式）。

    以 key（如 `login:ip:1.2.3.4` / `login:acct:a@b.c`）分桶記錄請求時間戳，
    視窗內請求數達上限即拒。`hit` 為同步、無 await（asyncio 單執行緒下對單一 key
    的讀改寫不會被其他協程插斷），故不需鎖；前提為應用以單一 process 運行。
    """

    def __init__(self, max_requests: int, window_seconds: float, max_keys: int = _DEFAULT_MAX_KEYS) -> None:
        if max_requests <= 0 or window_seconds <= 0 or max_keys <= 0:
            raise ValueError("max_requests、window_seconds、max_keys 必須為正數")
        self._max = max_requests
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

    def hit(self, key: str, *, now: float | None = None) -> None:
        """記錄一次請求；視窗內達上限則拋 AppError(429)。

        Args:
            key: 限流分桶鍵（含 scope + 維度，如 `login:ip:...`）。
            now: 目前單調時間（秒）；預設 time.monotonic()，測試可注入以決定性驗證。

        Raises:
            AppError: 視窗內請求數已達上限（429 / COMMON_429）。被拒的請求不佔配額。
        """
        current = time.monotonic() if now is None else now

        self._since_sweep += 1
        if self._since_sweep >= _SWEEP_EVERY:
            self._sweep(current)
            self._since_sweep = 0

        # 硬上限：新 key 會使字典超界時，先立即回收；仍滿則 fail-closed 拒絕，界定記憶體上界
        if key not in self._hits and len(self._hits) >= self._max_keys:
            self._sweep(current)
            if len(self._hits) >= self._max_keys:
                raise AppError(status_code=429, detail="操作過於頻繁，請稍後再試", error_code="COMMON_429")

        bucket = self._hits[key]
        cutoff = current - self._window
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= self._max:
            raise AppError(status_code=429, detail="操作過於頻繁，請稍後再試", error_code="COMMON_429")
        bucket.append(current)


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
