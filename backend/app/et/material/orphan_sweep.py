"""孤兒影片檔清理（#775，SCHET002 第 5 批）。

孤兒＝儲存目錄裡有檔、**沒有任何資料列指向它**。產生的路徑（2026-10-20 盤點）：

| # | 路徑 |
|---|------|
| A | 已發布 / 已關閉課程上傳影片後沒按「更新」就離開，下次進編輯頁丟掉未保留的暫存 |
| B | 同上，教師按「取消」放棄整輪編輯 |
| C | 上傳後在暫存區又刪掉那支影片，再按「更新」——它從沒進過活表，暫存列隨套用清掉 |
| D | 檔案已搬進正式目錄、寫列的交易卻失敗（`storage.promote` 刻意的不對稱取捨） |
| E | 上傳到一半當機，`.tmp/` 留下殘檔 |

使用者裁示採**每日掃描**（而非在 A～C 各丟棄點當場刪）：五條路徑一次涵蓋，連既有的
孤兒也回收；D、E 本來就沒有可掛勾的時點。

⚠️ **不在範圍**：活表已軟刪影片的檔案——軟刪除可回復，那些檔照舊永久保留（使用者裁示
維持現狀，保留期另議）。`referenced_video_paths` 因此把已軟刪的列也算作引用。
"""

import logging
import time
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.et.material import storage
from app.et.material.repository import EtMaterialRepository
from app.et.material.rules import select_orphans

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SweepResult:
    """一次清理的結果——只記數量，不記路徑（路徑含教材 id，屬內部資訊）。"""

    scanned: int
    deleted: int


class EtOrphanVideoSweeper:
    """掃描影片儲存目錄、刪除孤兒檔。"""

    def __init__(self, materials: EtMaterialRepository | None = None) -> None:
        self._materials = materials or EtMaterialRepository()

    async def run(self, db: AsyncSession, *, root: str | None = None, now: float | None = None) -> SweepResult:
        """執行一次清理。唯讀 DB、只動檔案系統，不需要 commit。

        🔴 **先讀引用、後列目錄**，順序不可反：反過來的話，列目錄之後才 commit 的新上傳
        不在白名單裡——寬限期雖然擋得住，但那是唯一一道防線。先讀引用則新檔必然比白名單
        新，由寬限期與「列目錄晚於讀引用」兩件事一起保護。

        Args:
            root: 儲存根目錄；預設 `storage.storage_root()`。⚠️ 測試**必須**傳暫存目錄——
                本機的測試與開發共用同一個根目錄，而測試 DB 看不到開發 DB 的列。
            now: 現在時刻（epoch 秒），預設系統時間；供測試固定。

        Returns:
            掃描檔數與刪除檔數。
        """
        target_root = root or storage.storage_root()
        referenced = await self._materials.referenced_video_paths(db)
        files = storage.list_stored_files(target_root)
        orphans = select_orphans(files, referenced=referenced, now=time.time() if now is None else now)
        deleted = sum(1 for rel in orphans if storage.remove_stored_file(target_root, rel))
        if len(orphans) != deleted:
            logger.warning("ET 孤兒影片檔部分未刪除：應刪 %d、實刪 %d", len(orphans), deleted)
        return SweepResult(scanned=len(files), deleted=deleted)
