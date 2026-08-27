"""以 `ffprobe` 取影片長度（#203 / SA 裁示 Q2）。

`ET_MATERIAL_VIDEO.DURATION_SEC` 是 ET05 觀看覆蓋率公式的**分母**
（覆蓋率 = 已觀看區段聯集秒數 ÷ DURATION_SEC），故 data-model 訂為 NOT NULL 且
**取得失敗不得存檔**——否則該影片覆蓋率永遠算不出、章節永久無法解鎖。

## 為何用 ffprobe（SA 裁示 Q2 = A）

影片長度包在容器檔案內部的 metadata（mp4 的 box 樹、webm 的 EBML），不是檔案系統
屬性。純 Python 解析這些結構在常見檔案上可行，但**冷門編碼會失敗**，而失敗的成本
落在教師身上：系統只能說「無法解析，請改用其他格式」，教師無從得知該改成什麼，
而 spec 又不允許放行——這條路就斷了。

代價是 ffmpeg 成為本專案**第一個系統層依賴**（其餘 11 個皆為純 Python 套件）。
安裝點三處：本機開發（README 環境需求）、CI runner、部署映像檔。

## 安全約束

- **不經 shell**（傳 list 而非字串）——`shell=True` 會讓檔名變成命令注入面
- 傳入的路徑是**後端自建的暫存檔路徑**，不是使用者提供的字串
- 設 timeout：畸形檔可能讓 ffprobe 久候不返
- 限制讀取的輸出量：ffprobe 正常只吐一行數字，異常時不該讓它灌爆記憶體

## 為何用執行緒 + 阻塞版 subprocess，而非 `asyncio.create_subprocess_exec`

原本用 asyncio 版，在 `fastapi dev`（`--reload`）下必定拋 `NotImplementedError`。
根因在 uvicorn 的迴圈選擇（`uvicorn/loops/asyncio.py`）：

```python
if sys.platform == "win32" and not use_subprocess:
    return asyncio.ProactorEventLoop
return asyncio.SelectorEventLoop          # use_subprocess=True 走這裡
```

而 `use_subprocess = reload or workers > 1`。也就是說——uvicorn **因為它自己要用
子行程**（重載 / 多 worker）而選了一個**不支援子行程**的迴圈，我們的 ffprobe 就跟著
陣亡。Windows 上 `SelectorEventLoop` 不實作 `_make_subprocess_transport`。

更糟的是它的失敗形狀：單 worker 的正式環境用 Proactor、跑得好好的，只有開發模式
壞掉——很容易被當成「我這台環境的問題」而放過。

改用 `asyncio.to_thread` + 阻塞版 `subprocess.run` 後與迴圈實作無關，任何平台、
任何 loop policy 都一致。代價是佔用一個執行緒池執行緒，但 ffprobe 只讀 metadata、
毫秒等級就返回。
"""

import asyncio
import logging
import math
import subprocess
import sys

from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

#: ffprobe 執行檔名。不寫絕對路徑——各平台安裝位置不同，交由 PATH 解析。
FFPROBE = "ffprobe"

#: 單次探測之逾時（秒）。ffprobe 只讀 metadata、不解碼整支影片，正常在毫秒等級完成；
#: 給到 30 秒是為了容忍極大檔案在慢速磁碟上的 metadata 搜尋。
PROBE_TIMEOUT_SEC = 30

#: 輸出讀取上限（bytes）。正常輸出是一行浮點數（< 32 bytes），此界限純為防禦。
MAX_OUTPUT_BYTES = 4096

_UNPARSEABLE = AppError(
    status_code=422,
    detail="無法解析影片長度，請改用其他格式",
    error_code="ET_MATERIAL_004",
)


def parse_duration_output(text: str) -> int | None:
    """把 ffprobe 的 `format=duration` 輸出轉為整數秒；無法解析時回 `None`。

    ## 為何**向下取整**

    `ET_PROGRESS_INTERVAL` 的 `START_SEC` / `END_SEC` 為整數欄位，播放器回報的秒數
    進到 DB 時已被截斷。一支實際 180.7 秒的影片：

    - 向下取整存 180 → 學員看完全片可累積到 180，覆蓋率 180/180 = **100%**
    - 向上取整存 181 → 學員最多只到 180，覆蓋率 180/181 = 99.4%，**永遠無法完課**

    分母只要比可達到的最大值大一點點，章節就永久解不了鎖——這正是 data-model 警告的
    情形，只是成因從「取不到」變成「取得後進位」。

    ## 為何最小值為 1

    不足一秒的影片向下取整會是 0，使覆蓋率的分母為零。這種影片本身無意義，但讓它
    以 0 落地會製造一個除零的地雷；夾到 1 則語意合理（看 0~1 秒即 100%）且無害。

    Args:
        text: ffprobe 之 stdout（預期為單行浮點秒數）。

    Returns:
        整數秒（>= 1），或 `None` 表示無法解析。
    """
    stripped = text.strip()
    if not stripped:
        return None
    try:
        seconds = float(stripped)
    except ValueError:
        return None
    # NaN / inf：float() 接受 "nan" 與 "inf"，但兩者都不是有效長度。
    if not math.isfinite(seconds) or seconds <= 0:
        return None
    return max(1, math.floor(seconds))


def _run_ffprobe(path: str) -> subprocess.CompletedProcess[bytes]:
    """同步執行 ffprobe（於工作執行緒中呼叫）。"""
    return subprocess.run(  # noqa: S603 - 固定參數清單、不經 shell、路徑為後端自建
        [
            FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        capture_output=True,
        timeout=PROBE_TIMEOUT_SEC,
        check=False,
        # Windows 上避免每次探測都閃一個主控台視窗
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )


async def probe_duration_sec(path: str) -> int:
    """以 `ffprobe` 取影片長度（整數秒）。

    Args:
        path: **後端自建**之檔案路徑（非使用者提供的字串）。

    Returns:
        整數秒（>= 1）。

    Raises:
        AppError: 422 `ET_MATERIAL_004`——ffprobe 不存在、逾時、非零結束，或輸出
            無法解析。**四種情形共用同一個錯誤碼**（使用者能做的事一樣：換個檔案），
            但「ffprobe 不存在」會另記 ERROR log——那是環境問題不是檔案問題，
            症狀會是「所有影片都傳不上去」，缺了這行 log 會被誤判為程式壞掉。
    """
    try:
        completed = await asyncio.to_thread(_run_ffprobe, path)
    except FileNotFoundError:
        logger.error(
            "找不到 ffprobe 執行檔，影片長度無法解析——這是**環境設定問題**，"
            "所有影片上傳都會失敗。請確認執行環境已安裝 ffmpeg（見 README 環境需求）。"
        )
        raise _UNPARSEABLE from None
    except subprocess.TimeoutExpired:
        logger.warning("ffprobe 解析影片長度逾時（不記檔案路徑）")
        raise _UNPARSEABLE from None

    if completed.returncode != 0:
        raise _UNPARSEABLE

    duration = parse_duration_output(completed.stdout[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace"))
    if duration is None:
        raise _UNPARSEABLE
    return duration
