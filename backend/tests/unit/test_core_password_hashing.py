"""密碼運算非阻塞包裝與併發閘（#214）。

bcrypt（passlib）為同步 CPU 運算、本機實測單次約 185 ms，原本直接在 async 端點內呼叫，
等於讓 event loop 停擺——實測同步做 8 次雜湊時最大心跳間隔達 1574 ms，期間全站（含登入、
ET / DM 全部 API 與 /health）皆不前進，且部署要求 --workers 1，沒有第二個行程可吸收。

移到專用 ThreadPoolExecutor 後同一負載的最大心跳間隔降至 16 ms。併發閘則防止請求在等待
期間持續佔用 DB 連線（get_db 的 session 覆蓋整個請求，連線池僅 5 + 10 溢位）。

測試策略：能走公開 API 的就走公開 API；需要製造「閘位已滿」狀態的，以 _gate 佔位並
monkeypatch 門檻常數——不自行組裝私有參數，把對實作內部的耦合壓到最小。
"""

import asyncio
import logging
import time

import pytest

from app.core import password_hashing
from app.core.exceptions import AppError
from app.core.password_hashing import (
    hash_password_async,
    is_reused_async,
    verify_password_async,
)
from app.core.password_policy import hash_password, verify_password

pytestmark = pytest.mark.unit

_PWD = "Abcd1234"
_HASH = password_hashing._KIND_HASH
_VERIFY = password_hashing._KIND_VERIFY


async def _hold(kind: str, release: asyncio.Event) -> None:
    """佔住一個閘位直到 release 被設定（用於製造「閘位已滿」的狀態）。"""
    async with password_hashing._gate(kind):
        await release.wait()


async def _occupy(kind: str, count: int) -> tuple[asyncio.Event, list[asyncio.Task]]:
    release = asyncio.Event()
    tasks = [asyncio.create_task(_hold(kind, release)) for _ in range(count)]
    await asyncio.sleep(0.02)  # 讓它們都取得閘位
    assert password_hashing._inflight[kind] == count
    return release, tasks


async def _free(release: asyncio.Event, tasks: list[asyncio.Task]) -> None:
    release.set()
    await asyncio.gather(*tasks)


# --- 正確性：async 版與同步版等價 ---


async def test_hash_async_produces_verifiable_hash():
    """async 版產生的雜湊可被同步版驗證（同一演算法、同一設定）。"""
    hashed = await hash_password_async(_PWD)
    assert verify_password(_PWD, hashed) is True


async def test_verify_async_matches_sync_result():
    """async 驗證結果與同步版一致（正確 / 錯誤密碼皆然）。"""
    hashed = hash_password(_PWD)
    assert await verify_password_async(_PWD, hashed) is True
    assert await verify_password_async("Wrong9999", hashed) is False


async def test_is_reused_async_checks_all_history():
    """歷史比對逐筆執行、命中即短路（每筆各自送 executor，worker 在筆與筆之間釋放）。"""
    recent = [hash_password("Old11111"), hash_password("Old22222"), hash_password("Old33333")]
    assert await is_reused_async("Old22222", recent) is True
    assert await is_reused_async("Brand5678", recent) is False


async def test_hash_async_keeps_max_bytes_guard():
    """72 bytes 上限的不變量不因搬到執行緒而失效（AppError 需跨執行緒傳回）。"""
    with pytest.raises(AppError) as err:
        await hash_password_async("A" * 73)
    assert err.value.status_code == 422
    assert err.value.error_code == "DP_PWD_004"


# --- 核心目標：event loop 不再被阻塞 ---


async def test_event_loop_stays_responsive_during_hashing(monkeypatch):
    """多個雜湊同時進行時 event loop 仍在轉。

    以 5 ms 心跳計數作為 loop 存活指標；門檻取寬鬆的 10 次，避免 CI 負載造成 flaky——
    真正要證明的是「不再是 0」。門檻常數在此顯式放寬，使本測試不與部署的連線池設定耦合
    （連線池容量 8 時 _HASH_MAX_INFLIGHT 會降到 3，第 4 個雜湊會被卸除而假失敗）。
    """
    monkeypatch.setattr(password_hashing, "_MAX_INFLIGHT", 8)
    monkeypatch.setattr(password_hashing, "_HASH_MAX_INFLIGHT", 8)

    beats = 0
    stop = False

    async def _heartbeat() -> None:
        nonlocal beats
        while not stop:
            await asyncio.sleep(0.005)
            beats += 1

    hb = asyncio.create_task(_heartbeat())
    await asyncio.gather(*(hash_password_async(f"Abcd123{i}") for i in range(4)))
    stop = True
    await hb

    assert beats >= 10, f"event loop 在雜湊期間僅前進 {beats} 次心跳，疑似仍被阻塞"


async def test_sync_version_does_block_the_loop():
    """對照組（改前基準）：同步呼叫在同一心跳量測下幾乎完全停擺。

    與上一條成對，把 issue AC 要求的「改前 / 改後數據」變成常駐測試而非一次性量測。
    4 次 bcrypt 約 740 ms，期間心跳應為 0（協程拿不到執行機會）；給 2 次寬容度防排程抖動。
    """
    beats = 0
    stop = False

    async def _heartbeat() -> None:
        nonlocal beats
        while not stop:
            await asyncio.sleep(0.005)
            beats += 1

    hb = asyncio.create_task(_heartbeat())
    await asyncio.sleep(0.02)
    baseline = beats
    for i in range(4):
        hash_password(f"Abcd123{i}")  # 同步、刻意阻塞
    blocked_beats = beats - baseline
    stop = True
    await hb

    assert blocked_beats <= 2, f"預期同步雜湊期間心跳停擺，實際前進 {blocked_beats} 次"


# --- 門檻推導與不變量 ---


def test_threshold_must_stay_below_connection_pool_capacity():
    """不變量：門檻必須低於連線池容量，否則閘永遠不會觸發（成為死碼）。

    能進到閘的請求都已至少查過一次 DB、握著一條連線（get_db 的 session 持有到請求結束），
    所以計數的物理上界就是連線池容量。門檻若不低於容量，排隊點會退回連線池：第 N+1 個請求
    卡在 pool.connect() 直到 pool_timeout（預設 30 秒）後 500，且連線池全 app 共用 →
    DM / ET 一起死。兩個旋鈕分屬常數與環境變數，只靠人記得不算保證。
    """
    assert password_hashing._MAX_INFLIGHT < password_hashing._POOL_CAPACITY, (
        f"門檻 {password_hashing._MAX_INFLIGHT} 未低於連線池容量 {password_hashing._POOL_CAPACITY}，閘不會觸發"
    )


def test_bulkhead_limits_leave_headroom_for_the_other_side():
    """不變量：任一艙的上限都低於總門檻，故另一艙恆有保留額度。"""
    assert password_hashing._HASH_MAX_INFLIGHT < password_hashing._MAX_INFLIGHT
    assert password_hashing._VERIFY_MAX_INFLIGHT < password_hashing._MAX_INFLIGHT


# --- 卸除行為 ---


async def test_gate_sheds_when_own_bulkhead_is_full(monkeypatch):
    """自身艙壁滿 → 立即卸除（503 / COMMON_503），而非讓請求持續排隊佔資源。"""
    monkeypatch.setattr(password_hashing, "_HASH_MAX_INFLIGHT", 1)
    release, tasks = await _occupy(_HASH, 1)
    try:
        with pytest.raises(AppError) as err:
            await hash_password_async(_PWD)
        assert err.value.status_code == 503
        assert err.value.error_code == "COMMON_503"
    finally:
        await _free(release, tasks)

    assert await hash_password_async(_PWD)  # 閘位釋放後恢復


async def test_shed_response_carries_retry_after(monkeypatch):
    """卸除的 503 需帶 retry_after，前端才能給倒數而非讓使用者連點。"""
    monkeypatch.setattr(password_hashing, "_HASH_MAX_INFLIGHT", 0)
    with pytest.raises(AppError) as err:
        await hash_password_async(_PWD)
    assert err.value.retry_after is not None and err.value.retry_after >= 1


async def test_gate_sheds_when_total_threshold_reached(monkeypatch):
    """總門檻是最終約束：兩艙合計達上限時，即使自身艙壁未滿也卸除。"""
    monkeypatch.setattr(password_hashing, "_MAX_INFLIGHT", 2)
    monkeypatch.setattr(password_hashing, "_VERIFY_MAX_INFLIGHT", 5)
    monkeypatch.setattr(password_hashing, "_HASH_MAX_INFLIGHT", 5)
    release, tasks = await _occupy(_VERIFY, 2)
    try:
        with pytest.raises(AppError) as err:
            await hash_password_async(_PWD)
        assert err.value.error_code == "COMMON_503"
    finally:
        await _free(release, tasks)


async def test_bulkheads_are_symmetric(monkeypatch):
    """對稱艙壁：任一類用滿自身上限時，另一類仍有閘位。

    單向保留（只限制雜湊類）曾被 review 指出不對稱——verify 流量可把總數推到上限，
    使註冊 / 啟用 / 重設 / 改密碼全滅，帳號救援路徑毫無保留額度。
    """
    monkeypatch.setattr(password_hashing, "_MAX_INFLIGHT", 4)
    monkeypatch.setattr(password_hashing, "_HASH_MAX_INFLIGHT", 3)
    monkeypatch.setattr(password_hashing, "_VERIFY_MAX_INFLIGHT", 3)
    hashed = hash_password(_PWD)

    # 方向一：雜湊類用滿 → 認證路徑仍可用
    release, tasks = await _occupy(_HASH, 3)
    try:
        with pytest.raises(AppError):
            await hash_password_async(_PWD)
        assert await verify_password_async(_PWD, hashed) is True
    finally:
        await _free(release, tasks)

    # 方向二：認證類用滿 → 雜湊類仍可用
    release, tasks = await _occupy(_VERIFY, 3)
    try:
        with pytest.raises(AppError):
            await verify_password_async(_PWD, hashed)
        assert await hash_password_async(_PWD)
    finally:
        await _free(release, tasks)


async def test_gate_releases_slot_after_failure(monkeypatch):
    """運算拋錯時閘位必須釋放，否則連續失敗會把閘位漏光、系統永久 503。"""
    monkeypatch.setattr(password_hashing, "_HASH_MAX_INFLIGHT", 1)

    def _boom() -> None:
        raise ValueError("boom")

    for _ in range(3):
        with pytest.raises(ValueError):
            await password_hashing._run(_boom, kind=_HASH)

    assert password_hashing._inflight[_HASH] == 0
    assert await hash_password_async(_PWD)


async def test_cancelled_request_releases_slot(monkeypatch):
    """請求被 cancel（如行程關閉）時閘位必須釋放。

    注意：executor 的工作無法取消，背景執行緒仍會跑完——故閘計數在取消發生時會低估
    實際負載。此落差已記於 _gate 的 docstring；本測試只保證閘位本身不漏。
    """
    monkeypatch.setattr(password_hashing, "_VERIFY_MAX_INFLIGHT", 1)

    task = asyncio.create_task(password_hashing._run(time.sleep, 0.2, kind=_VERIFY))
    await asyncio.sleep(0.02)
    assert password_hashing._inflight[_VERIFY] == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert password_hashing._inflight[_VERIFY] == 0


async def test_is_reused_takes_a_single_gate_slot(monkeypatch):
    """歷史比對整段只佔一個閘位（一次入場、逐筆執行）。

    逐筆各自取閘會讓一次改密碼要通過最多 26 個閘門（HISTORY_COUNT 上限 24），成功率變成
    (1-p) 的 26 次方——單次卸除率 23.7% 時完成率只剩 0.1%，且中途卸除會白燒掉前面幾次 bcrypt。
    """
    monkeypatch.setattr(password_hashing, "_HASH_MAX_INFLIGHT", 5)
    recent = [hash_password(f"Old1111{i}") for i in range(3)]

    task = asyncio.create_task(is_reused_async("Brand5678", recent))
    await asyncio.sleep(0.05)  # 比對進行中
    assert password_hashing._inflight[_HASH] == 1, "整段比對應只佔一個閘位"
    assert await task is False


async def test_shed_logging_is_throttled(monkeypatch, caplog):
    """卸除要留下 WARNING（否則正式環境是盲區），但需節流避免 log 洪災。"""
    monkeypatch.setattr(password_hashing, "_HASH_MAX_INFLIGHT", 0)
    monkeypatch.setattr(password_hashing, "_last_shed_log", 0.0)

    with caplog.at_level(logging.WARNING, logger="app.core.password_hashing"):
        for _ in range(3):
            with pytest.raises(AppError):
                await hash_password_async(_PWD)

    shed_logs = [r for r in caplog.records if "併發閘卸除" in r.getMessage()]
    assert len(shed_logs) == 1, f"預期節流後只記一筆，實際 {len(shed_logs)} 筆"


# --- 啟停 ---


async def test_warm_up_completes_without_side_effects():
    """暖機可正常完成且不留下閘位（啟動時單執行緒跑一次，關閉 passlib 惰性初始化的競態）。"""
    await password_hashing.warm_up()
    assert password_hashing._inflight[_HASH] == 0
    assert password_hashing._inflight[_VERIFY] == 0
