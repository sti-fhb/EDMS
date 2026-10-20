"""系統儀表板（US7 / DM00）服務——各類型文件總數 + 最新更新公告（唯讀）。

- 統計（FR-002）：4 內建分類之「已發布目前版本」數 + 總計；含 PENDING_OBSOLETE（在架）、排除 OBSOLETE/送審/草稿/舊版。
- 公告（FR-003）：**最新 N 筆**已發布版本（新增/新版本兩類），發布時間 DESC；空清單由前端呈現 DM-MSG-DM00-001。
"""

from collections.abc import Iterable

from app.dm.dashboard.repository import DashboardRepository
from app.dm.dashboard.schemas import AnnouncementItem, CategoryStat, DashboardStats

# 公告只列最新 N 筆，**不設時間窗**（#758）：首頁是入口不是清單，要看更早的請至 DM01 文件庫
# （公告區右上即有「查看全部文件 →」）。原為「近 30 天 + 上限 50」，時間窗已移除。
_ANNOUNCE_LIMIT = 10
# 內建分類固定呈現順序（對齊 wireframe：SOP / 系統操作手冊 / 訓練教材 / 其他）
_CATEGORY_ORDER = ("SOP", "MANUAL", "TRAINING", "OTHER")
_NEW = "NEW"
_NEW_VERSION = "NEW_VERSION"


class DashboardService:
    """DM00 統計 + 公告。"""

    def __init__(self, repository: DashboardRepository | None = None) -> None:
        self._repo = repository or DashboardRepository()

    async def get_stats(self, db, *, user_id: str, roles: Iterable[str]) -> DashboardStats:
        """4 內建分類之已發布目前版本數 + 總計（0 亦顯示卡片；固定順序；套可見性）。"""
        counts = await self._repo.published_counts_by_category(db, user_id=user_id, roles=roles)
        cats = {code: name for code, name in await self._repo.builtin_categories(db)}
        ordered = [c for c in _CATEGORY_ORDER if c in cats] + [c for c in cats if c not in _CATEGORY_ORDER]
        items = [CategoryStat(category_code=c, category_name=cats[c], count=counts.get(c, 0)) for c in ordered]
        total = sum(i.count for i in items)
        return DashboardStats(items=items, total=total)

    async def get_announcements(self, db, *, user_id: str, roles: Iterable[str]) -> list[AnnouncementItem]:
        """最新 `_ANNOUNCE_LIMIT` 筆已發布版本（新增/新版本），發布時間 DESC；無資料回空清單；套可見性。

        ⚠️ `limit` 必須交給 repository 放進**同一個查詢**，與可見性條件一起由 DB 執行。
        ⛔ 不可改成「先取 N 筆再於應用層過濾」——那會讓閱覽者看到少於 N 筆（甚至 0 筆），
        而系統中其實還有他看得到的文件。`test_十筆上限在閱覽者可見範圍內取` 守這件事。
        """
        rows = await self._repo.recent_announcements(db, limit=_ANNOUNCE_LIMIT, user_id=user_id, roles=roles)
        return [
            AnnouncementItem(
                doc_id=r.doc_id,
                doc_name=r.doc_name,
                category_code=r.category_code,
                category_name=r.category_name,
                version_no=r.version_no,
                change_summary=r.change_summary,
                published_date=r.published_date,
                author_name=r.author_name,
                # 無對應 APPROVED review（種子 / 資料異常）→ 視為新增首版
                kind=_NEW_VERSION if r.kind == _NEW_VERSION else _NEW,
            )
            for r in rows
        ]
