"""密碼運算的非阻塞包裝與併發閘（#214）。

`password_policy` 的 `hash_password` / `verify_password` 採 bcrypt（passlib），是**同步
CPU 運算**、本機實測單次約 185 ms。原本各 service 直接在 async 端點內呼叫，等於讓 event
loop 停擺——實測同步做 8 次雜湊時，最大心跳間隔達 1574 ms，期間全站（含登入、ET / DM
全部 API、`/health`）皆不前進；而部署要求 `--workers 1`（限流與冷卻狀態存於行程記憶體，
見 `docs/ref/deployment-client-ip.md`），沒有第二個行程可以吸收。

移到專用 `ThreadPoolExecutor` 後，同一負載的最大心跳間隔降至 16 ms、牆鐘 471 ms
（bcrypt 原生實作在運算期間釋放 GIL，實測 4 執行緒約 3.45 倍加速）。

## 併發閘：門檻的依據是「DB 連線池」，不是 CPU

只做非阻塞化會留下一個空窗：請求在**等待 bcrypt 期間仍握著 DB 連線**——`get_db` 的
session 自第一次查詢起持有連線直到請求結束，而**四個呼叫點全部在雜湊之前至少查過一次
DB**（登入查帳號、重設查 token 與歷史、設定密碼查 token〔US2 驗證與 US4 啟用共用同一段〕、
改密碼查使用者）。註冊自 #212 起完全不做密碼運算，已不在此列。
因此：

- 能進到本閘的請求數，其**物理上界就是連線池容量**（`DB_POOL_SIZE + DB_MAX_OVERFLOW`）
- 門檻若設得比連線池大，閘**永遠不會觸發**（死碼）；真正的排隊點會退回連線池，第 N+1
  個請求卡在 `pool.connect()` 直到 `pool_timeout`（預設 30 秒）後 500，而且因為連線池
  是全 app 共用，**DM / ET 的查詢會一起死**

⚠️ **本閘的射程僅止於「密碼類請求對連線池的貢獻上限」**（目前 7 / 15），不代表連線池耗盡
已被解決：非密碼流量（DM / ET 查詢、排程）本身就可能把池占滿，此時閘完全不會介入——那是
獨立的容量規劃問題。本閘要防的是「密碼運算成為池耗盡的放大器」。

所以門檻由連線池容量推導，並刻意**只取一半**：另一半留給與密碼無關的模組，使密碼運算
的洪峰不會把整個池吃光。`test_core_password_hashing.py` 有不變量測試釘住此關係。

## 分艙：認證路徑永遠保有餘裕

閘位若不分身分，匿名的 `hash_password_async`（註冊）就能把配額吃光，使**登入與已登入者
改密碼一律 503**——攻擊者用完全匿名的流量即可剝奪已認證使用者的能力。故 `verify_password_async`
（登入、驗舊密碼）可用全額，而 `hash_password_async` 只能用 75%，保證認證路徑至少有
25% 的閘位可用。

## 為何不用「全域速率上限」

全域每分鐘 N 次的門檻必須依硬體猜一個數字（N × 185 ms 才是實際 CPU 佔用），且撞到時
全站一律 429、不管當下是否真的飽和。以連線池推導的併發閘則對準真正的瓶頸。
"""

import asyncio
import logging
import math
import os
import time
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.password_policy import hash_password, verify_password

logger = logging.getLogger(__name__)


def _available_cpus() -> int:
    """可用 CPU 數。優先用 `sched_getaffinity`（POSIX，尊重 cpuset）。

    ⚠️ 兩者皆**不看 cgroup CPU quota**（如 Docker `--cpus=1`、K8s `limits.cpu`）：
    quota 低於核心數時實際吞吐量會低於推導值，排隊時間相應變長。非阻塞化的主要收益
    （event loop 不再停擺）不受影響，但「加速多少」與可用核心數成正比。
    """
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0))
    return os.cpu_count() or 1


# 工作執行緒數：bcrypt 為 CPU-bound，超過核心數只會增加競爭。上限 4 兼顧小型容器。
_WORKERS = min(4, _available_cpus())

# 連線池容量——本閘門檻的物理上界（見模組 docstring）
_POOL_CAPACITY = settings.DB_POOL_SIZE + settings.DB_MAX_OVERFLOW

# 啟動即擋：容量過小時本閘會退化——容量 1 時門檻等於容量（閘變死碼），容量 2 時兩個艙壁
# 各自的保留額度歸零（分艙失效）。且失效方式是**靜默**的：正式環境不跑不變量測試，沒有
# 任何訊號。比照 config 對 TRUSTED_PROXY_COUNT 的既有作法，把「不受支援」升級為 fail-fast。
if _POOL_CAPACITY < 4:
    raise RuntimeError(
        f"DB_POOL_SIZE + DB_MAX_OVERFLOW = {_POOL_CAPACITY}，密碼運算併發閘需要 >= 4 才能運作"
        "（見 app/core/password_hashing.py 的門檻推導）"
    )

# 總門檻：取連線池的一半（另一半留給非密碼類請求），且至少容納所有 worker 各一件工作
# （避免門檻過低使 worker 閒置），最後夾在「連線池容量 - 1」以下確保閘一定先於連線池觸發。
# 以 pool=15 / workers=4 為例 → 7。
_MAX_INFLIGHT = max(1, min(max(_WORKERS, _POOL_CAPACITY // 2), _POOL_CAPACITY - 1))

# 對稱艙壁：兩類各自的上限皆為總門檻的 75%，故任一類最多只能吃掉 75%，另一類恆保有 25%。
# 單向保留（只限制雜湊類）曾被 review 指出是不對稱的：verify 流量可把總數推到上限，
# 使註冊 / 啟用 / 重設 / 改密碼全滅——帳號救援路徑沒有任何保留額度。以 7 為例 → 各 5，
# 兩者合計 10 > 7，故總門檻仍是最終約束，而任一方最多 5、另一方恆有 2。
_HASH_MAX_INFLIGHT = max(1, math.floor(_MAX_INFLIGHT * 0.75))
_VERIFY_MAX_INFLIGHT = _HASH_MAX_INFLIGHT

# 卸除時回給前端的建議重試秒數。刻意不隨即時負載變動（避免成為負載探測器）。
# ⚠️ 客戶端應自行加抖動：同一時刻被卸除的請求若都在 N 秒後同步重試，會形成重試風暴。
_RETRY_AFTER_SEC = 3

# 卸除日誌節流間隔（秒）：卸除通常成批發生，逐筆記錄會造成 log 洪災。
_SHED_LOG_INTERVAL_SEC = 5.0

# 專用 pool：與其他 to_thread 使用者（如 DM 的檔案 I/O，用預設 executor）隔離，使上界明確。
# lifespan 會於關機時顯式 shutdown(cancel_futures=True)——`concurrent.futures` 的 atexit
# hook 會等佇列中**所有**工作跑完，佇列滿時可達數十秒，可能撞上容器的 SIGKILL。
_executor = ThreadPoolExecutor(max_workers=_WORKERS, thread_name_prefix="pwdhash")

_KIND_HASH = "hash"
_KIND_VERIFY = "verify"

_inflight: dict[str, int] = {_KIND_HASH: 0, _KIND_VERIFY: 0}
_last_shed_log = 0.0


def _log_shed(kind: str) -> None:
    """記錄卸除（節流）。

    卸除若沒有任何訊號，正式環境的「使用者註冊不了」只會變成一通客服電話而非一條告警：
    503 目前只走 `main.app_error_handler` 的 `logger.debug`，而專案未設定 logging、
    root level 為 WARNING → 那行永遠不會輸出。
    """
    global _last_shed_log
    now = time.monotonic()
    if now - _last_shed_log < _SHED_LOG_INTERVAL_SEC:
        return
    _last_shed_log = now
    logger.warning(
        "密碼運算併發閘卸除 kind=%s hash_inflight=%s verify_inflight=%s limits=%s/%s/%s",
        kind,
        _inflight[_KIND_HASH],
        _inflight[_KIND_VERIFY],
        _HASH_MAX_INFLIGHT,
        _VERIFY_MAX_INFLIGHT,
        _MAX_INFLIGHT,
    )


@asynccontextmanager
async def _gate(kind: str) -> AsyncIterator[None]:
    """取得一個閘位；自身艙壁或總門檻已滿則卸除（503 / COMMON_503）。

    檢查與遞增之間沒有 await，故在 asyncio 單執行緒下為原子操作、不需鎖（與
    `core/cooldown.py` 同一理由；worker 執行緒不觸碰計數）。`finally` 遞減對正常回傳、
    同步例外與 `CancelledError` 三種路徑皆生效，閘位不會漏光。

    ⚠️ 已知落差：executor 的工作**無法取消**。請求被 cancel 時閘位立即釋放，但已被 worker
    撿起的 bcrypt 會在背景跑完，故閘計數在取消發生時會**低估**實際負載。目前的 stack 不會
    因客戶端斷線而取消請求（Starlette 的 BaseHTTPMiddleware 只讓 receive 回 http.disconnect、
    uvicorn 僅標記 disconnected），故此路徑主要發生於行程關閉；**若日後加入 request timeout
    或斷線即取消的行為，必須重新評估本閘**。
    """
    own_limit = _HASH_MAX_INFLIGHT if kind == _KIND_HASH else _VERIFY_MAX_INFLIGHT
    if _inflight[kind] >= own_limit or _inflight[_KIND_HASH] + _inflight[_KIND_VERIFY] >= _MAX_INFLIGHT:
        _log_shed(kind)
        raise AppError(
            status_code=503,
            detail="系統忙碌中，請稍後再試",
            error_code="COMMON_503",
            retry_after=_RETRY_AFTER_SEC,
        )
    _inflight[kind] += 1
    try:
        yield
    finally:
        _inflight[kind] -= 1


async def _exec(fn: Callable[..., Any], *args: Any) -> Any:
    """於專用執行緒池執行一次 CPU 運算（呼叫方須先持有閘位）。

    ⚠️ 傳入的 `fn` 必須是純函式：`loop.run_in_executor` 不像 `asyncio.to_thread` 會複製
    contextvars，任何依賴 `get_client_ip()` 等 request-scoped 狀態的 callable 在此會取到空值。
    """
    return await asyncio.get_running_loop().run_in_executor(_executor, fn, *args)


async def _run(fn: Callable[..., Any], *args: Any, kind: str) -> Any:
    """取閘位 + 執行一次運算（單次運算的便利包裝）。"""
    async with _gate(kind):
        return await _exec(fn, *args)


async def hash_password_async(plain: str) -> str:
    """`hash_password` 的非阻塞版；72-byte 上限之 AppError 照原樣跨執行緒傳回。"""
    return await _run(hash_password, plain, kind=_KIND_HASH)


async def verify_password_async(plain: str, hashed: str) -> bool:
    """`verify_password` 的非阻塞版（認證艙）。"""
    return await _run(verify_password, plain, hashed, kind=_KIND_VERIFY)


async def is_reused_async(password: str, recent_hashes: list[str]) -> bool:
    """檢查密碼是否與最近使用過的任一雜湊相符（防重用）；命中即短路。

    **一次入場、逐筆執行**：整個迴圈只取一次閘位，但每筆各自 `run_in_executor`，讓 worker
    在筆與筆之間釋放。兩個極端都要避免——

    - 整批塞進同一個執行緒工作：`HISTORY_COUNT` 上限 24（`param_rules`），單一請求會霸佔
      一個 worker 達 24 × 185 ms ≈ 4.4 秒，把登入等單次運算卡在同一佇列後面
    - 逐筆各自取閘：一次改密碼要通過最多 26 個閘門，成功率變成 `(1-p)^26`——單次卸除率
      23.7% 時完成率只剩 0.1%，且中途卸除會白燒掉前面幾次 bcrypt（負載越高白做越多）

    一次入場使入場判定回到「每請求一次」，公平且不白做工；閘位被持有較久則是該操作真實
    成本的誠實反映。
    """
    async with _gate(_KIND_HASH):
        for hashed in recent_hashes:
            if await _exec(verify_password, password, hashed):
                return True
    return False


async def warm_up() -> None:
    """啟動時預先完成 passlib 的 bcrypt backend 初始化（於 lifespan 呼叫）。

    兩個理由：

    1. passlib 1.7.4 讀 `bcrypt.__about__.__version__` 取版本，而 bcrypt 4.x 已移除該模組，
       故首次使用時會以 WARNING + exc_info 印出一段 `AttributeError` traceback。功能不受影響
       （passlib 自己 trap 住、版本標為 unknown），但專案沒有 logging 設定，該筆走
       `logging.lastResort` 直噴 stderr、無時間戳與 logger 名稱，在容器 log 裡長得像未捕捉的
       崩潰。移到啟動階段可讓維運知道它與「第一個使用者登入」無關。
    2. passlib 的 backend 是惰性初始化。改為多執行緒後，4 條 worker 可能同時首呼，而
       `_stub_requires_backend()` 的斷言檢查在鎖之外——窗口極窄但非零，會拋
       `AssertionError: failed to replace lazy loader`。啟動時單執行緒跑一次即關閉此窗口。
    """
    await hash_password_async("warm-up-not-a-real-password")


def shutdown() -> None:
    """關機時收斂執行緒池（於 lifespan 的 finally 呼叫）。

    `concurrent.futures` 的 atexit hook 會等佇列中**所有**工作跑完；佇列滿時可達數十秒，
    可能撞上容器的 SIGKILL。`cancel_futures=True` 丟棄尚未開始的工作，只等進行中的跑完。

    ⚠️ **不可逆、行程級一次性**：關閉後任何 `_exec` 都會拋 `RuntimeError: cannot schedule
    new futures after shutdown`。測試若要跑真實 lifespan，必須 monkeypatch 本函式
    （見 `tests/unit/test_main_lifespan.py`），否則會把單例池關掉、汙染後續測試。
    """
    _executor.shutdown(wait=False, cancel_futures=True)
