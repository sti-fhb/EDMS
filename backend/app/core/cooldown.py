"""重寄 / 註冊驗證信冷卻（#74）。

依 key（Email 維度）記錄「上次寄出驗證信」時間，強制兩次寄送間隔至少冷卻秒數，
防止使用者狂點重寄 / 重複註冊灌出多封驗證信（且舊連結會互相作廢、導致帳號開不了）。

行程內記憶體、單實例（EDMS 預設單一實例）；重啟即重置——冷卻屬防濫發 UX 機制，
非強一致安全防線（真正暴力另有 rate_limit.py 的 IP / 帳號限流兜底）。

check / record 分離是刻意設計：check 在呼叫送信服務**之前**擋、record 在**成功送信後**蓋章，
使註冊驗證失敗（如密碼太弱 422、Email 已驗證 409）不會誤觸冷卻，避免使用者被無謂鎖住。
冷卻秒數由呼叫端每次傳入（讀 DP_PARAM，免重新部署即可調）。

已知取捨：check 與 record 之間有 await（送信服務），同 Email 的併發請求可能都通過 check
而各送一封（極短競態窗）。冷卻屬防濫發 UX，非強一致：真正的高頻濫發由 router 層先行的
per-IP / per-帳號 SlidingWindowRateLimiter 兜底，故此窗可接受。
"""

import math
import time

from app.core.exceptions import AppError

_COOLDOWN_MSG = "操作過於頻繁，請稍後再試"
# 每處理 N 次 record 掃描一次全表、清除較舊紀錄（key 由使用者可控的 Email 組成，須主動回收）
_SWEEP_EVERY = 1000
# outer dict 硬上限：達上限先 sweep，仍滿則不再記錄（fail-open：不擋，交由 IP 限流兜底），界定記憶體上界
_DEFAULT_MAX_KEYS = 100_000
# 掃描回收保留上限：僅用於記憶體回收，不影響正常冷卻判定（實務冷卻 600 秒，1 小時已有 6 倍餘裕）。
#
# 由 86,400（1 天）下調至 3,600（#213 review）：`_MAX_KEYS` 達上限時本類是 **fail-open**（不擋，
# 交 IP 限流兜底），而穩態 key 數約等於「到達率 × 本保留期」。保留 1 天時只需約 1.16 key/秒
# （≈7 個來源 IP 各以 resend 的 10 次/分持續一天）即可把表推到十萬上限；保留 1 小時則需約
# 27.8 key/秒。
#
# ⚠️ **達到 27.8 key/秒所需的 IP 數，#345 之後減半**（原推導以 resend 的 10 次/分、每請求 1 把章
# 計 ≈167 個 IP）。改動後 `/register` 每個請求最多蓋 **2 把章**（acct + probe，靜默路徑亦蓋
# probe），且其門檻是 `REGISTER_RATE_MAX`＝**30 次/分** → 1 key/秒/IP → 約 **28 個 IP** 即可達標。
# 那離「實質不可達」有距離，原註解的結論已不成立，故此處改記真實數字而非沿用舊結論。
#
# ⚠️ 觸頂目前是**完全無聲**的（不記錄、不擋、不 log）。真要打到這個速率，攻擊者必須同時對
# 大量信箱送出真實驗證信並寫入 pending / outbox 列，噪音極大，故判定為「縱深防禦的餘裕被
# 砍半」而非立即可打的洞；但**若要調整，應優先補觸頂 WARN log**，而不是再下調保留期
# （保留期已只有冷卻的 6 倍）。追蹤見 #345 的 Security Review MEDIUM-1。
#
# 為何值得在意：fail-open 之後，任何尚未進表的 Email 其 `verify-send:acct:{email}` 永遠蓋不上章
# → `/register` 對同一 Email 的 600 秒防狂發完全消失（只剩 30 次/分的帳號維度限流）→ 可對指定
# 信箱灌 30 封驗證信/分鐘，且每次覆蓋都寫一筆稽核（append-only、鏈式雜湊、以交易級 advisory
# lock 序列化）。`core/rate_limit.py` 的 REGISTER_RATE_MAX 推導明文倚賴「同一 Email 由 600 秒
# 冷卻鎖住」，冷卻一 fail-open 該推導即失效。
_MAX_RETENTION_SEC = 3_600.0


class VerifySendCooldown:
    """驗證信寄送冷卻追蹤器（依 key 記錄上次寄送單調時間）。

    `check` 為同步、無 await（asyncio 單執行緒下對單一 key 的讀改寫不會被其他協程插斷），
    不需鎖；前提為應用以單一 process 運行。
    """

    def __init__(self, max_keys: int = _DEFAULT_MAX_KEYS) -> None:
        if max_keys <= 0:
            raise ValueError("max_keys 必須為正數")
        self._max_keys = max_keys
        self._last: dict[str, float] = {}
        self._since_sweep = 0

    def _sweep(self, now: float) -> None:
        """清除超過保留上限的舊紀錄，回收使用者可控 key 佔用的記憶體。

        O(n) 全表掃描，每 _SWEEP_EVERY 次 record 觸發一次。最壞情境（表達 _max_keys＝十萬）
        單次掃描為十萬筆整數比較（毫秒級），對單實例 event loop 的短暫佔用可接受；
        實務上 resend 冷卻的活躍 Email 數遠低於此上限。
        """
        cutoff = now - _MAX_RETENTION_SEC
        stale = [key for key, ts in self._last.items() if ts <= cutoff]
        for key in stale:
            del self._last[key]

    def check(self, key: str, cooldown_sec: float, *, now: float | None = None) -> None:
        """距上次送信未滿 cooldown_sec 則拒。無紀錄（未曾送信）或已滿冷卻 → 放行。

        Args:
            key: 冷卻分桶鍵（含 scope + Email，如 `verify-send:acct:a@b.c`）。
            cooldown_sec: 冷卻秒數（呼叫端讀 DP_PARAM 傳入）。
            now: 目前單調時間（秒）；預設 time.monotonic()，測試可注入以決定性驗證。

        Raises:
            AppError: 仍在冷卻內（429 / COMMON_429，帶 retry_after 剩餘秒數，向上取整至少 1）。
        """
        if retry_after := self.remaining(key, cooldown_sec, now=now):
            raise AppError(status_code=429, detail=_COOLDOWN_MSG, error_code="COMMON_429", retry_after=retry_after)

    def remaining(self, key: str, cooldown_sec: float, *, now: float | None = None) -> int:
        """剩餘冷卻秒數（向上取整、至少 1）；未在冷卻中回 0。**不拋例外。**

        `check` 的無副作用版本，供需要「知道在冷卻中、但不想回 429」的呼叫端使用——
        register 對**他人**蓋的 Email 章必須靜默（#346），回 429 會洩漏「該 Email 有未逾期的
        自助註冊待驗證列」。以例外當控制流可以達到同樣效果，但會讓那段讀起來像錯誤處理，
        而它其實是正常分支。

        `check` 改以本方法實作，兩者的時間比較因此只有一份。

        ⛔ **回傳值不得直接回給匿名呼叫端。** 它是秒數，而「`verify-send:acct:` 還剩幾秒」
        正是 #346 要隱藏的事實（該章只在真的寄出時蓋 ⇒ 剩餘秒數洩漏「有人剛對此 Email
        寄出驗證信」）。需要回 `retry_after` 時只能用**自己的** probe 章——那與該 Email
        的任何事實無關。目前唯一的呼叫端（register / resend）只取布林。
        """
        current = time.monotonic() if now is None else now
        last = self._last.get(key)
        if last is None:
            return 0
        elapsed = current - last
        return math.ceil(cooldown_sec - elapsed) if elapsed < cooldown_sec else 0

    def record(self, key: str, *, now: float | None = None) -> None:
        """蓋上「剛成功送出驗證信」時間戳（送信成功後呼叫，刷新冷卻起點）。"""
        current = time.monotonic() if now is None else now

        self._since_sweep += 1
        if self._since_sweep >= _SWEEP_EVERY:
            self._sweep(current)
            self._since_sweep = 0

        # 硬上限：新 key 會使字典超界時，先回收；仍滿則不記錄（不擋、交由 IP 限流兜底）
        if key not in self._last and len(self._last) >= self._max_keys:
            self._sweep(current)
            if len(self._last) >= self._max_keys:
                return

        self._last[key] = current
