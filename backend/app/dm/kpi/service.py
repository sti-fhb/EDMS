"""閱讀統計 KPI 服務（US13）。

兩塊：① DM10 儀表板唯讀查詢（DM_ADMIN，逐文件應看/已看/未看/閱讀率 + 統計卡 + CSV）
② SCHDM001 每週排程之核心（KPI 週報予全 DM_ADMIN、未讀提醒逐位未看閱覽者一信）。

「應看」母體＝具 DM_VIEWER 角色且可見對象相符者（掛「全體」→ 全部 DM_VIEWER；否則 audience 交集）；
「已看」＝其中已下載目前發布版者；閱讀率＝已看/應看（應看=0 → None，不計入整體平均，AC3a）。
逐人內容於執行當下算好後逐一以固定 params 呼叫平台發信（SA 裁示 2026-09-02，FR-006）。
"""

import csv
import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.csv_export import sanitize_csv_cell
from app.core.exceptions import AppError
from app.dm.kpi.repository import KpiRepository
from app.dm.kpi.schemas import KpiDocItem, KpiListResponse, KpiSummary
from app.dm.notify.service import DmNotifier
from app.dm.roles.authz import DM_ADMIN, has_role

_CSV_HEADERS = ["文件編號", "文件名稱", "分類", "目前版本", "應看", "已看", "未看", "閱讀率"]
_TPL_WEEKLY = "KPI_WEEKLY"
_TPL_UNREAD = "UNREAD_REMIND"
_DASHBOARD_PATH = "/dm/kpi"


@dataclass
class _DocKpi:
    """單一文件之 KPI 計算結果（含未看閱覽者集，供未讀提醒逐人彙整）。"""

    doc_id: str
    doc_name: str
    category_code: str
    category_name: str | None
    current_version_no: str | None
    should_see: int
    seen: int
    unseen: int
    rate: float | None
    unseen_members: set[str] = field(default_factory=set)


@dataclass
class WeeklyRunResult:
    """SCHDM001 執行結果（供 handler 記錄 log）。"""

    total_docs: int
    weekly_queued: int  # KPI 週報排入 Email 數
    unread_notified: int  # 收到未讀提醒之閱覽者數（實際排入者）


def _pct(rate: float | None) -> str:
    """閱讀率轉顯示字串（None → 「—」）。"""
    return "—" if rate is None else f"{rate * 100:.1f}%"


class KpiService:
    """DM10 閱讀統計 KPI（查詢 / 匯出 / 每週排程）。"""

    def __init__(self, repository: KpiRepository | None = None, notifier: DmNotifier | None = None) -> None:
        self._repo = repository or KpiRepository()
        self._notifier = notifier or DmNotifier()

    @staticmethod
    def _ensure_admin(roles: Iterable[str]) -> None:
        """FR-002 後端硬閘：非 DM_ADMIN 一律 403（對應 DM-MSG-DM10-002，擋直連）。"""
        if not has_role(roles, DM_ADMIN):
            raise AppError(status_code=403, detail="需要文件管理者權限", error_code="DM_AUTH_003")

    async def _compute(self, db: AsyncSession, *, keyword: str | None, category: str | None) -> list[_DocKpi]:
        """算出（符合條件之）全部已發布文件之逐文件 KPI。"""
        viewer_ids = await self._repo.viewer_ids(db)
        viewer_tags = await self._repo.viewer_audience_tags(db, viewer_ids)
        docs = await self._repo.list_published_docs(db, keyword=keyword, category=category)
        doc_ids = [d.doc_id for d in docs]
        doc_aud = await self._repo.doc_audience(db, doc_ids)
        reads = await self._repo.reads_current(db, doc_ids)

        stats: list[_DocKpi] = []
        for d in docs:
            tags, has_all = doc_aud.get(d.doc_id, (set(), False))
            if has_all:
                members = set(viewer_ids)
            else:
                members = {u for u in viewer_ids if viewer_tags.get(u, frozenset()) & tags}
            readers = reads.get(d.doc_id, set())
            seen_members = members & readers
            should_see = len(members)
            seen = len(seen_members)
            rate = (seen / should_see) if should_see > 0 else None
            stats.append(
                _DocKpi(
                    doc_id=d.doc_id,
                    doc_name=d.doc_name,
                    category_code=d.category_code,
                    category_name=d.category_name,
                    current_version_no=d.current_version_no,
                    should_see=should_see,
                    seen=seen,
                    unseen=should_see - seen,
                    rate=rate,
                    unseen_members=members - readers,
                )
            )
        return stats

    @staticmethod
    def _summary(stats: Sequence[_DocKpi]) -> KpiSummary:
        rated = [s.rate for s in stats if s.rate is not None]  # 排除應看=0（AC3a）
        overall = (sum(rated) / len(rated)) if rated else None
        below_50 = sum(1 for r in rated if r < 0.5)
        return KpiSummary(total_docs=len(stats), overall_rate=overall, below_50_count=below_50)

    async def search(
        self,
        db: AsyncSession,
        *,
        roles: Iterable[str],
        keyword: str | None,
        category: str | None,
        page: int,
        limit: int,
    ) -> KpiListResponse:
        """DM10 儀表板（FR-002，DM_ADMIN）：逐文件 KPI（後端分頁）+ 統計卡摘要。"""
        self._ensure_admin(roles)
        stats = await self._compute(db, keyword=keyword, category=category)
        summary = self._summary(stats)
        total = len(stats)
        total_pages = (total + limit - 1) // limit if total > 0 else 0
        page_stats = stats[(page - 1) * limit : (page - 1) * limit + limit] if page <= total_pages else []
        data = [
            KpiDocItem(
                doc_id=s.doc_id,
                doc_name=s.doc_name,
                category_code=s.category_code,
                category_name=s.category_name,
                current_version_no=s.current_version_no,
                should_see=s.should_see,
                seen=s.seen,
                unseen=s.unseen,
                rate=s.rate,
            )
            for s in page_stats
        ]
        return KpiListResponse(
            data=data,
            meta={"total": total, "page": page, "limit": limit, "total_pages": total_pages},
            summary=summary,
        )

    async def export_csv(self, db: AsyncSession, *, roles: Iterable[str], keyword: str | None, category: str | None) -> bytes:
        """匯出當前查詢結果為 CSV（FR-002，全量、無分頁）。含 UTF-8 BOM 供 Excel 辨識中文。"""
        self._ensure_admin(roles)
        stats = await self._compute(db, keyword=keyword, category=category)
        buf = io.StringIO()
        writer = csv.writer(buf)  # csv 模組處理逗號 / 換行 / 引號跳脫，禁手拼
        writer.writerow(_CSV_HEADERS)
        for s in stats:
            writer.writerow(
                [
                    sanitize_csv_cell(s.doc_id),
                    sanitize_csv_cell(s.doc_name),
                    sanitize_csv_cell(s.category_name or s.category_code),
                    sanitize_csv_cell(s.current_version_no or ""),
                    s.should_see,
                    s.seen,
                    s.unseen,
                    _pct(s.rate),
                ]
            )
        return buf.getvalue().encode("utf-8-sig")

    async def run_weekly(self, db: AsyncSession) -> WeeklyRunResult:
        """SCHDM001 每週核心（FR-004~006）：算全部已發布文件 KPI → 寄 KPI 週報 + 未讀提醒。

        逐位收件人於執行當下算好內容後逐一固定 params enqueue（平台不做寄送時組信）。範本停用時
        平台端 skip、不寄（本方法照常呼叫，queued 計數自然為 0）。
        """
        stats = await self._compute(db, keyword=None, category=None)
        summary = self._summary(stats)
        weekly_queued = await self._send_weekly_report(db, stats=stats, summary=summary)
        unread_notified = await self._send_unread_reminders(db, stats=stats)
        return WeeklyRunResult(
            total_docs=summary.total_docs, weekly_queued=weekly_queued, unread_notified=unread_notified
        )

    async def _send_weekly_report(self, db: AsyncSession, *, stats: Sequence[_DocKpi], summary: KpiSummary) -> int:
        """KPI 週報予所有 DM_ADMIN：內文摘要（總數 / 平均 / 最低前 5 份 / 儀表板連結），不走附件。"""
        recipients = await self._repo.admin_emails(db)
        if not recipients:
            return 0
        lowest = sorted((s for s in stats if s.rate is not None), key=lambda s: s.rate)[:5]
        lowest_list = "\n".join(f"- {s.doc_name}（{_pct(s.rate)}）" for s in lowest) or "（無可計算閱讀率之文件）"
        params = {
            "total_docs": str(summary.total_docs),
            "avg_rate": _pct(summary.overall_rate),
            "lowest_list": lowest_list,
            "dashboard_link": f"{settings.FRONTEND_BASE_URL.rstrip('/')}{_DASHBOARD_PATH}",
        }
        result = await self._notifier.notify(db, template_code=_TPL_WEEKLY, recipients=recipients, params=params)
        return result.queued_count

    async def _send_unread_reminders(self, db: AsyncSession, *, stats: Sequence[_DocKpi]) -> int:
        """未讀提醒：對每位有未看文件之閱覽者寄一封彙整信（涵蓋全部已發布文件）。無未看者不寄。"""
        viewer_unseen: dict[str, list[str]] = {}
        for s in stats:
            for user_id in s.unseen_members:
                viewer_unseen.setdefault(user_id, []).append(s.doc_name)
        if not viewer_unseen:
            return 0
        profiles = await self._repo.viewer_profiles(db, viewer_unseen.keys())
        notified = 0
        for user_id, doc_names in viewer_unseen.items():
            prof = profiles.get(user_id)
            if prof is None or not prof.email:
                continue
            params = {
                "viewer_name": prof.user_name or "",
                "unread_count": str(len(doc_names)),
                "unread_list": "\n".join(f"- {n}" for n in doc_names),
            }
            result = await self._notifier.notify(
                db, template_code=_TPL_UNREAD, recipients=[prof.email], params=params
            )
            if result.queued_count:
                notified += 1
        return notified
