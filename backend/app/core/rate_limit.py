"""速率限制（T015）。

行程內記憶體滑動視窗，防自動化程式對登入 / 忘記密碼 / 密碼變更端點暴力嘗試
（research §10）。按「來源 IP + 帳號」限流，超限回 429。EDMS 預設單一實例，
行程內計數即足、不引入 Redis；帳號鎖定（5 次錯誤）為第二層防線（見 DP_USER）。
"""

import ipaddress
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
# 模組層的裸容器，`tests/_process_singletons.py` 的反射重置掃不到（該檔列為已知盲區）。不加進 `RESETTERS`：
# 每個請求結束即由 `limit_concurrent_exports` 的 `finally` 遞減、歸零即移除，不跨請求累積。
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

    def __init__(
        self, window_seconds: float, max_keys: int = _DEFAULT_MAX_KEYS, *, rejects_when_full: bool = False
    ) -> None:
        if window_seconds <= 0 or max_keys <= 0:
            raise ValueError("window_seconds、max_keys 必須為正數")
        self._window = window_seconds
        self._max_keys = max_keys
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._since_sweep = 0
        # 觸頂時 log 要講哪一種後果。本類別只知道自己「沒記錄」，**後果由擁有者決定**：
        # 直接使用者（註冊路徑）照常放行＝保護失效；`SlidingWindowRateLimiter` 則拋 429＝過度阻擋。
        # 兩者方向相反，訊息混用會讓排查的人往反方向找（#198）。
        self._rejects_when_full = rejects_when_full

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
                # 🔴 觸頂必留痕（2026-10-14 Security MEDIUM-1），而且**要講對是哪一種後果**（#198）：
                # 兩個擁有者的行為刻意相反，症狀也相反——訊息寫錯方向會讓排查的人去找不存在的問題。
                #
                # ⚠️ 本類別的飽和門檻比 `core/cooldown.py` 低約一個量級，因為視窗長得多：
                # cooldown 保留 3,600 秒 → 填滿 100k 需 27.8 key/s（約 28 個 IP）；
                # 本 counter 若以 86,400 秒視窗使用 → 僅需 1.16 key/s（**約 2～3 個 IP 持續一天**）。
                # 記憶體上界約 104 MB（100k × deque+str+float 實測）——⚠️ 那是**單一實例**的數字，
                # 而全庫有 41 個 `SlidingWindowRateLimiter` 各帶預設 100k（匿名可達的有 login／
                # register／forgot／reset／verify／resend／activate 共 7 個）。部署估算要乘上實例數。
                #
                # ⛔ key 由使用者可控的值組成（`login:acct:a@b.c`），**一律不得寫進 log**。
                if self._rejects_when_full:
                    logger.warning(
                        "限流器 key 空間已滿（上限 %s）：新 key 一律拒絕（fail-closed），"
                        "此後尚未進入字典的來源全部回 429 event=limiter_key_space_full",
                        self._max_keys,
                    )
                else:
                    logger.warning(
                        "計數器 key 空間已滿（上限 %s）：本次不記錄、照常放行（fail-open），"
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
        # `rejects_when_full=True`：本類別觸頂是 fail-closed（拋 429），與 counter 直接使用者相反。
        self._counter = SlidingWindowCounter(window_seconds, max_keys, rejects_when_full=True)

    @property
    def _hits(self) -> dict[str, deque[float]]:
        """內部桶（代理至 `self._counter._hits`），供測試觀察。

        測試間的狀態重置已統一由 `tests/_process_singletons.py` 直接清 `SlidingWindowCounter`（#654），
        不經本屬性；原本分散於 6 個測試檔的 `_hits.clear()` / `.pop()` 已移除。
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


def ip_bucket(ip: str) -> str:
    """把來源 IP 收斂成限流分桶鍵：**IPv6 取 /64 前綴，IPv4 原樣**（#198）。

    **為什麼 IPv6 要收斂**：一個 /64 是 VPS、行動網路、家用固網的標配配額。攻擊者每個請求
    換一個來源位址就落在新桶，**不需偽造任何 header**，效果等同 #23 修正前的漏洞。而第二層
    防線「帳號鎖定 5 次」擋的是單一帳號暴力，**對密碼噴灑（同一密碼掃大量帳號）不會觸發**，
    所以 IP 維度是唯一控制。

    ⛔ **為什麼 IPv4 刻意不一起收斂**（SA 2026-10-29 裁示）——看到「IPv6 收了、IPv4 沒收」
    請勿判定為漏做而順手補上：

    - IPv4 沒有「隨手換一個位址」這件事。取得一個 /24 的成本與取得一個 /64 差好幾個量級，
      **威脅結構根本不同**
    - 而 /24 的代價是**確定會發生**的：院內網路、行動網路都是共用出口 NAT，收到 /24 等於
      把 NAT 後方整批使用者當成同一個人，誤擋的是真使用者且他們無從得知原因
    - ⇒ 用一個確定的誤擋，換一個成本結構上不成立的攻擊，不划算

    ⚠️ **本函式只用於限流分桶。** `DP_AUDIT_LOG.SOURCE_IP` 必須存**完整位址**——鑑識需要精確
    來源，不隨分桶收斂（`tests/unit/test_core_rate_limit.py` 有反向守門 + 正向錨點）。

    ## 已知邊界（刻意不處理，**不是漏做**）

    ⚠️ 「一個 /64 ＝ 一個人」這個前提對**行動網路**（每支手機一個 /64）、**VPS**（每台一個）、
    **家用固網**（一戶一個）成立，但對**企業／院內 LAN 不成立**——IPv6 沒有 NAT，一個 VLAN
    就是一個 /64，幾十到幾百台主機共用同一個前綴。走 IPv6 進來的整個科室會共用一份配額
    （login 門檻 10/min）。⛔ 走 IPv4 的使用者**本來就**共用 NAT 出口那一桶，不受本變更影響。
    若上線後出現成批的 `COMMON_429`，先查來源是不是 IPv6：
    `SELECT count(*) FROM "DP_AUDIT_LOG" WHERE "SOURCE_IP" LIKE '%:%';`

    下列 IPv6 轉換／隧道前綴會**塌成單桶**（該前綴下全體共用一份配額）或**散開**，
    目前部署（Cloudflare Tunnel → nginx → app）**均不可達**，故不加分支處理：

    | 輸入 | 結果 | 為何目前不可達 |
    |---|---|---|
    | `64:ff9b::<IPv4>`（NAT64／SIIT）| 塌成 `64:ff9b::/64` | 正常拓樸中它是目的位址、不是來源 |
    | `2001:0::/32`（Teredo）| 塌成同一 server 一桶 | Teredo 已淘汰 |
    | `::1` / `::` / `::<IPv4>` | 塌成 `::/64` | 僅在 `TRUSTED_PROXY_COUNT` 設過小時出現（既有已知塌縮）|
    | `2002::/16`（6to4）| 一個 IPv4 可散出 2^16 個桶 | 6to4 已淘汰 |

    ⇒ 日後若導入 NAT64／SIIT-DC 使後端看到 IPv4-embedded 來源位址，**本分桶會塌成單桶**，
    須同步處理。

    Args:
        ip: 來源位址字串，或取不到時的 fallback（如 `"unknown"`）。

    Returns:
        分桶鍵。IPv6 回 `網路位址/64`；IPv4 與無法解析者原樣回傳。
    """
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        # `"unknown"` 等 fallback 字串原樣當桶：限流不得因為來源取不到而炸掉。
        return ip
    if isinstance(parsed, ipaddress.IPv6Address):
        if parsed.ipv4_mapped is not None:
            # `::ffff:1.2.3.4` 是 IPv4 位址的 IPv6 表示法。照 /64 收會把**整個 IPv4 空間**
            # 併成同一桶（前綴都是 `::ffff:0:0/64`），等於全站共用一份配額。
            return str(parsed.ipv4_mapped)
        if parsed.scope_id is not None:
            # zone id（`fe80::1%eth0`）屬本機語意、不是來源的一部分，入口即清除。
            # ⚠️ 不清會**分裂成兩個桶**：`strict=False` 只在 host bits ≠ 0 時重建位址（順便丟掉
            # scope），全 0 時沿用原物件 ⇒ `fe80::1%eth0` → `fe80::/64`，而 `fe80::%eth0`
            # → `fe80::%eth0/64`。同一條鏈兩個桶。
            # 另一半理由：下一行的 `ip_network()` **在 try 之外**，今天不拋只是因為 CPython 的
            # `IPv6Network` 剛好容忍 scope。這裡先清掉，日後有人改寫前綴運算時不會變成
            # 匿名端點上的未捕捉例外（→ 500）。
            parsed = ipaddress.IPv6Address(int(parsed))
        return str(ipaddress.ip_network(f"{parsed}/64", strict=False))
    return str(parsed)


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
        limiter.hit(f"{scope}:ip:{ip_bucket(ip)}")

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
