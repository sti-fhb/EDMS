"""系統儀表板（US7 / DM00）服務——各類型文件總數 + 最新更新公告（唯讀）。

- 統計（FR-002）：4 內建分類之「已發布目前版本」數 + 總計；含 PENDING_OBSOLETE（在架）、排除 OBSOLETE/送審/草稿/舊版。
- 公告（FR-003）：近 30 天已發布版本（新增/新版本兩類），發布時間 DESC；空清單由前端呈現 DM-MSG-DM00-001。
"""

from collections.abc import Iterable
from datetime import timedelta

from app.core.utils import utcnow
from app.dm.dashboard.repository import DashboardRepository
from app.dm.dashboard.schemas import AnnouncementItem, CategoryStat, DashboardStats

_ANNOUNCE_DAYS = 30
_ANNOUNCE_LIMIT = 50  # 近 30 天量小；設上限防極端資料量灌爆前端
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
        """近 30 天已發布版本（新增/新版本），發布時間 DESC；無事件回空清單；套可見性。"""
        cutoff = utcnow() - timedelta(days=_ANNOUNCE_DAYS)
        rows = await self._repo.recent_announcements(
            db, cutoff=cutoff, limit=_ANNOUNCE_LIMIT, user_id=user_id, roles=roles
        )
        return [
            AnnouncementItem(
                doc_id=r.doc_id,
                doc_name=r.doc_name,
                category_code=r.category_code,
                version_no=r.version_no,
                change_summary=r.change_summary,
                published_date=r.published_date,
                author_name=r.author_name,
                # 無對應 APPROVED review（種子 / 資料異常）→ 視為新增首版
                kind=_NEW_VERSION if r.kind == _NEW_VERSION else _NEW,
            )
            for r in rows
        ]
