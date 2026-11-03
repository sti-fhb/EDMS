"""上傳前檢查磁碟剩餘空間（#905 A1）。

正式環境的上傳暫存（`/tmp`）、DM 檔案與 ET 影片的存放區，與 TBMS 的資料庫在同一顆磁碟上
（2026-11-02 VM 實測：`/var/lib/docker`、`/opt/edms`、`/opt/tbms` 同在 `/dev/root`）。不設防的話，
大量上傳可以把磁碟寫滿，TBMS 的資料庫跟著寫不進去。

`UploadAuthPrecheckMiddleware` 在把上傳交給路由解析 body 之前呼叫 `has_room`：低於門檻就丟棄 body、
回 507，連 `/tmp` 都不會寫。只管上傳端點——磁碟將滿時，登入、查詢與一般寫入照常運作。

## 預留額度：算進「已放行、還在寫」的上傳

只看當下剩多少不夠：同一瞬間開始的上傳都還沒寫入任何位元組，會全部通過。所以每放行一支，
middleware 先預留它最多會用掉的空間（`max_upload_bytes`），回應結束才扣回；判斷的是
「剩餘 − 已預留 − 這一支 ≥ 門檻」。

- **預留的是上限，不是實際大小**：`Content-Length` 由客戶端決定，multipart 也可以不帶。上限取 nginx 的
  `client_max_body_size` 乘 2——寫檔期間 `/tmp` 與存放區的暫存各一份（ET 影片見 `et/material/storage.py`）。
  兩邊的數字由 `tests/unit/test_core_upload_disk_guard.py` 對 `nginx/nginx.conf` 守門
- **行程內計數即可**：與每人同時上傳數上限同一個前提，後端固定單一 worker

## 量哪些目錄

三處都量、取最少的：正式環境三者同在一顆磁碟，量一處就夠；但部署方式改了（例如影片改掛獨立
磁碟）時，各自不足都該擋。目錄還不存在時（全新部署、第一次上傳前）量最近的上層目錄——
`shutil.disk_usage` 對不存在的路徑會拋錯，而那個目錄建立後也會在同一顆磁碟上。

量測是同步的系統呼叫，本機磁碟為微秒等級，直接在事件迴圈上執行。⚠️ 存放區日後若改掛網路磁碟
（NFS 等），掛載點卡住會讓整個後端停住，屆時要改成 `asyncio.to_thread`。

## 量不到時放行

量測拋 `OSError`（掛載點斷線、權限）時**放行**並記 ERROR：這道檢查壞掉時，不該連帶讓所有上傳失敗。

## log 頻率

空間不足期間每次被擋都記一筆的話，持續的上傳嘗試會刷掉同期其他紀錄。改為每 `_LOG_INTERVAL_SEC`
最多一筆，附上這段期間被擋的次數。

## 不是什麼

- **不取代基礎設施的隔離**：EDMS 與 TBMS 分開磁碟才是根本解（#905 A1 的另一半）
- 擋不到發生在後端之前的寫入（前面的反向代理若緩衝 body，那是它自己的設定）
"""

import logging
import os
import shutil
import tempfile
import time

from app.core.config import settings

logger = logging.getLogger(__name__)

_MB = 1024 * 1024

#: 與 `nginx/nginx.conf` 上傳 location 的 `client_max_body_size` 一致（測試守門）。
ET_VIDEO_MAX_BODY_MB = 501
DM_DOCUMENT_MAX_BODY_MB = 51

#: 寫檔期間同一份資料在磁碟上的份數：multipart 暫存（`/tmp`）+ 存放區的暫存。
_COPIES_ON_DISK = 2

_LOG_INTERVAL_SEC = 60.0


def upload_dirs() -> dict[str, str]:
    """上傳會寫入的目錄：multipart 暫存、DM 存放區、ET 影片存放區。"""
    return {
        "tmp": tempfile.gettempdir(),
        "dm": settings.DM_FILE_STORAGE_ROOT,
        "et": settings.ET_VIDEO_STORAGE_ROOT,
    }


def max_upload_bytes(route_path: str) -> int:
    """這支上傳最多會在磁碟上用掉的空間（預留額度）。`route_path` 須為上傳端點的路徑。"""
    body_mb = ET_VIDEO_MAX_BODY_MB if route_path.startswith("/api/et/") else DM_DOCUMENT_MAX_BODY_MB
    return body_mb * _MB * _COPIES_ON_DISK


def _free_bytes(path: str) -> int:
    """`path` 所在磁碟的剩餘空間；目錄還不存在時量最近的上層目錄（不建立目錄）。"""
    current = os.path.abspath(path)
    while not os.path.exists(current):
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return shutil.disk_usage(current).free


class _RejectLog:
    """空間不足的 ERROR 每 `_LOG_INTERVAL_SEC` 最多一筆，期間被擋的次數併入下一筆。"""

    def __init__(self) -> None:
        self.last_logged: float | None = None
        self.suppressed = 0

    def record(self, path: str, free_mb: int, reserved_mb: int, threshold_mb: int) -> None:
        now = time.monotonic()
        if self.last_logged is not None and now - self.last_logged < _LOG_INTERVAL_SEC:
            self.suppressed += 1
            return
        logger.error(
            "磁碟剩餘空間不足，暫停接收上傳：%s 剩餘 %d MB（另有 %d MB 預留給進行中的上傳），門檻 %d MB；"
            "上一筆紀錄之後另擋下 %d 次",
            path,
            free_mb,
            reserved_mb,
            threshold_mb,
            self.suppressed,
        )
        self.last_logged = now
        self.suppressed = 0


_reject_log = _RejectLog()


def has_room(reserved_bytes: int, needed_bytes: int) -> bool:
    """扣掉已預留與這一支的需求後，所有上傳目錄仍不低於 `UPLOAD_MIN_FREE_DISK_MB`。

    門檻為 0 時不檢查；量測失敗時放行並記 ERROR（理由見模組說明）。

    Args:
        reserved_bytes: 已放行、還在進行中的上傳所預留的空間。
        needed_bytes: 這一支要預留的空間（`max_upload_bytes`）。

    Returns:
        可以放行時為 `True`。
    """
    threshold_mb = settings.UPLOAD_MIN_FREE_DISK_MB
    if threshold_mb == 0:
        return True
    try:
        free, path = min((_free_bytes(path), path) for path in upload_dirs().values())
    except OSError:
        logger.exception("無法量測上傳目錄的磁碟剩餘空間，本次上傳放行（不檢查）")
        return True
    if free - reserved_bytes - needed_bytes >= threshold_mb * _MB:
        return True
    _reject_log.record(path, free // _MB, reserved_bytes // _MB, threshold_mb)
    return False
