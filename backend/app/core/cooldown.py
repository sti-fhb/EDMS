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
# 掃描回收保留上限：遠大於實務冷卻（分鐘級），僅用於記憶體回收，不影響正常冷卻判定
_MAX_RETENTION_SEC = 86_400.0


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
        current = time.monotonic() if now is None else now
        last = self._last.get(key)
        if last is None:
            return
        elapsed = current - last
        if elapsed < cooldown_sec:
            retry_after = math.ceil(cooldown_sec - elapsed)
            raise AppError(status_code=429, detail=_COOLDOWN_MSG, error_code="COMMON_429", retry_after=retry_after)

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
