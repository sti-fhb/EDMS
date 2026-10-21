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

## 刪檔不可逆，所以「看不懂就不刪」

以下任一情況整輪中止、一支都不刪（`SweepResult.aborted` 記原因）：

| 情況 | 為何中止 |
|---|---|
| ET 與 DM 的儲存根目錄互相包含 | 掃 ET 根目錄會掃到 DM 的受控文件，而那些沒有任何 ET 列指向 |
| 有暫存列讀不出 `file_path` | 那一列可能正指向某支檔；略過它等於判它可刪 |
| 白名單是空的、目錄裡卻有系統產生的檔 | 最常見的成因是連到錯的 DB 或查詢壞了，不是「真的全是孤兒」 |

另外只處理系統產生的檔名（`rules.is_managed_video_path`）、一次至多刪
`MAX_ORPHAN_DELETES_PER_RUN` 支。
"""

import logging
import os
import time
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.et.material import storage
from app.et.material.repository import EtMaterialRepository
from app.et.material.rules import is_managed_video_path, select_orphans

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SweepResult:
    """一次清理的結果——只記數量與中止原因，不記路徑（路徑含教材 id，屬內部資訊）。"""

    scanned: int
    deleted: int
    aborted: str | None = None


def _roots_overlap(a: str, b: str) -> bool:
    """兩個目錄是否相同或其一包含另一個。"""
    ra, rb = os.path.normcase(os.path.realpath(a)), os.path.normcase(os.path.realpath(b))
    try:
        common = os.path.commonpath([ra, rb])
    except ValueError:  # Windows 跨磁碟：必然不重疊
        return False
    return common in (ra, rb)


class EtOrphanVideoSweeper:
    """掃描影片儲存目錄、刪除孤兒檔。"""

    def __init__(self, materials: EtMaterialRepository | None = None) -> None:
        self._materials = materials or EtMaterialRepository()

    async def run(
        self,
        db: AsyncSession,
        *,
        root: str | None = None,
        now: float | None = None,
        dm_root: str | None = None,
    ) -> SweepResult:
        """執行一次清理。唯讀 DB、只動檔案系統，不需要 commit。

        🔴 **先讀引用、後列目錄**，順序不可反：反過來的話，列目錄之後才 commit 的新上傳不在
        白名單裡——寬限期雖然擋得住，但那會是唯一一道防線。

        Args:
            root: 儲存根目錄；`None` 時用 `storage.storage_root()`。⚠️ 測試**必須**傳暫存目錄
                ——本機的測試與開發共用同一個根目錄，而測試 DB 看不到開發 DB 的列。
                ⚠️ 判 `is None` 而非真偽：誤傳空字串在刪檔情境下不該靜默改用真實根目錄。
            now: 現在時刻（epoch 秒），預設系統時間；供測試固定。
            dm_root: DM 儲存根目錄；`None` 時讀設定。供測試檢查重疊判定。

        Returns:
            掃描檔數、刪除檔數，以及中止原因（未中止為 `None`）。
        """
        target_root = storage.storage_root() if root is None else root
        if not target_root:
            raise ValueError("ET 影片儲存根目錄不可為空字串")
        if _roots_overlap(target_root, settings.DM_FILE_STORAGE_ROOT if dm_root is None else dm_root):
            return self._abort(0, "ET 與 DM 的儲存根目錄互相包含")

        referenced_raw, unreadable = await self._materials.referenced_video_paths(db)
        files = storage.list_stored_files(target_root)
        if unreadable:
            return self._abort(len(files), f"有 {unreadable} 筆暫存影片列讀不出路徑")
        managed = [(p, m) for p, m in files if is_managed_video_path(p)]
        if not referenced_raw and managed:
            return self._abort(len(files), "白名單為空但目錄內有影片檔")

        referenced = {storage.path_key(target_root, p) for p in referenced_raw}
        orphans = select_orphans(
            files,
            referenced=referenced,
            now=time.time() if now is None else now,
            key=lambda p: storage.path_key(target_root, p),
        )
        deleted = sum(1 for rel in orphans if storage.remove_stored_file(target_root, rel))
        if len(orphans) != deleted:
            logger.warning("ET 孤兒影片檔部分未刪除：應刪 %d、實刪 %d", len(orphans), deleted)
        return SweepResult(scanned=len(files), deleted=deleted)

    @staticmethod
    def _abort(scanned: int, reason: str) -> SweepResult:
        logger.warning("ET 孤兒影片檔清理中止：%s", reason)
        return SweepResult(scanned=scanned, deleted=0, aborted=reason)
