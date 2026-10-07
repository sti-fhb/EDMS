"""閱讀統計 KPI 服務（US13）。

兩塊：① DM06 儀表板唯讀查詢（DM_ADMIN，逐文件應看/已看/未看/閱讀率 + 統計卡 + CSV）
② SCHDM001 每週排程之核心（KPI 週報予全 DM_ADMIN、未讀提醒逐位未看閱覽者一信）。

「應看」母體＝具 DM_VIEWER 角色且可見對象相符者（掛「全體」→ 全部 DM_VIEWER；否則 audience 交集）；
「已看」＝其中已下載目前發布版者；閱讀率＝已看/應看（應看=0 → None，不計入整體平均，AC3a）。
逐人內容於執行當下算好後逐一以固定 params 呼叫平台發信（SA 裁示 2026-09-02，FR-006）。
"""

import csv
import io
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.csv_export import sanitize_csv_cell
from app.core.exceptions import AppError
from app.dm.kpi.repository import KpiRepository
from app.dm.kpi.schemas import KpiAudienceGroup, KpiDocItem, KpiListResponse, KpiSummary, KpiTrainingDoc
from app.dm.notify.service import DmNotifier
from app.dm.roles.authz import DM_ADMIN, has_role

_CSV_HEADERS = ["文件編號", "文件名稱", "分類", "目前版本", "應看", "已看", "未看", "閱讀率"]
_TPL_WEEKLY = "KPI_WEEKLY"
_TPL_UNREAD = "UNREAD_REMIND"
_DASHBOARD_PATH = "/dm/kpi"

#: 可見對象配對 `(單位 tag_id, 職位 tag_id)`；通用值（「全單位」/「全體」）已正規化為 `None`。
_Pair = tuple[int | None, int | None]

#: 訓練教材清單之回傳上限。該區不含統計、只是讓管理者看得到教材存在，故不另做一套分頁；
#: 但仍設上限——無上限清單正是 #563 的形狀，不在同一個模組再造一個。超出時以
#: `training_total` 告知實際筆數。
_TRAINING_LIST_LIMIT = 200


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
    groups: list[KpiAudienceGroup] = field(default_factory=list)  # 逐可見對象組（#567 A）


@dataclass
class WeeklyRunResult:
    """SCHDM001 執行結果（供 handler 記錄 log）。"""

    total_docs: int
    weekly_queued: int  # KPI 週報排入 Email 數
    unread_notified: int  # 收到未讀提醒之閱覽者數（實際排入者）


def _single_pair_visible(du: int | None, dp: int | None, user_pairs: set[tuple[int | None, int]]) -> bool:
    """**單一**文件配對 (du, dp) 是否涵蓋該使用者（#437）。

    Python 版之判定，語意須與 SQL 版 `visibility.audience_pair_match` **完全一致**：
    文件端之通用值已由 `doc_audience` 正規化為 `None`（「全單位」/「全體」）。

        可見 ⟺ (du is None AND dp is None)            -- 全系統，不需任何授權
                OR ∃ 使用者配對 (uu, up)：
                     (du is None OR du == uu) AND (dp is None OR dp == up)

    人側 `uu is None`（單位未指定）時 `du == uu` 恆為 False，故僅能匹配 `du is None`
    ——與 SQL 端 NULL 比較的行為相同。

    ⚠️ 兩份實作各自存在是因為 KPI 需在 Python 層對「文件 × 閱覽者」做交叉統計；改動判定規則時
    **兩邊都要改**。`test_dm_kpi.py` 之配對案例與 `test_dm_kpi_audience_groups.py` 之逐案
    參數化測試即為此而設。
    """
    if du is None and dp is None:
        return True
    for uu, up in user_pairs:
        if (du is None or du == uu) and (dp is None or dp == up):
            return True
    return False


def _pair_visible(doc_pairs: Mapping[_Pair, str], user_pairs: set[tuple[int | None, int]]) -> bool:
    """此文件之**任一**可見對象配對是否涵蓋該使用者。

    `doc_pairs` 為 `{配對: 組名}`——迭代 dict 取得的即配對本身，組名於此不參與判定。
    """
    return any(_single_pair_visible(du, dp, user_pairs) for du, dp in doc_pairs)


def _audience_breakdown(
    doc_pairs: Mapping[_Pair, str],
    *,
    viewer_ids: Iterable[str],
    viewer_tags: Mapping[str, set[tuple[int | None, int]]],
    readers: set[str],
) -> tuple[set[str], list[KpiAudienceGroup]]:
    """單趟掃出「去重後的應看集」與「逐組統計」（#567 A）。

    刻意一次掃完而非「總計掃一次、每組各掃一次」：後者是 O(閱覽者 × 組數) 次完整比對，
    而本迴圈每位閱覽者只取一次授權集。

    ## 逐組加總會大於去重總計

    一位閱覽者可同時符合同一份文件的多組配對（身兼兩職、而文件兩組都掛）。裁示
    （2026-10-07）為**各組分母都含他、文件總計去重**——「這一組的完成度」對兩組而言
    該員都確實是應讀者。⚠️ 呈現端必須標註兩者對不起來，否則讀者會判定成算錯。

    Args:
        doc_pairs: 該文件之 `{(單位, 職位): 組名}`，通用值已正規化為 `None`。
        viewer_ids: 應看母體（具 DM_VIEWER 且帳號有效者）。
        viewer_tags: 各閱覽者之授權配對集；無授權者可不出現。
        readers: 該文件目前發布版之 distinct 下載者。

    Returns:
        (去重後之應看集, 逐組統計依組名排序)。
    """
    members: set[str] = set()
    per_pair: dict[_Pair, set[str]] = {pair: set() for pair in doc_pairs}
    for user_id in viewer_ids:
        user_pairs = viewer_tags.get(user_id, frozenset())
        for pair in doc_pairs:
            if _single_pair_visible(pair[0], pair[1], user_pairs):
                per_pair[pair].add(user_id)
                members.add(user_id)
    groups = [
        KpiAudienceGroup(
            label=label,
            should_see=len(group_members),
            seen=len(group_members & readers),
            unseen=len(group_members - readers),
            # 該組無人 → None（「無對應閱覽者」），不是 0%——與文件層 AC3a 同語意
            rate=(len(group_members & readers) / len(group_members)) if group_members else None,
        )
        for label, group_members in ((doc_pairs[pair], per_pair[pair]) for pair in doc_pairs)
    ]
    groups.sort(key=lambda g: g.label)  # 輸出穩定：同一份資料兩次請求順序一致
    return members, groups


def _pct(rate: float | None) -> str:
    """閱讀率轉顯示字串（None → 「—」）。"""
    return "—" if rate is None else f"{rate * 100:.1f}%"


class KpiService:
    """DM06 閱讀統計 KPI（查詢 / 匯出 / 每週排程）。"""

    def __init__(self, repository: KpiRepository | None = None, notifier: DmNotifier | None = None) -> None:
        self._repo = repository or KpiRepository()
        self._notifier = notifier or DmNotifier()

    @staticmethod
    def _ensure_admin(roles: Iterable[str]) -> None:
        """FR-002 後端硬閘：非 DM_ADMIN 一律 403（對應 DM-MSG-DM06-002，擋直連）。"""
        if not has_role(roles, DM_ADMIN):
            raise AppError(status_code=403, detail="需要文件管理者權限", error_code="DM_AUTH_003")

    async def _compute(self, db: AsyncSession, *, keyword: str | None, category: str | None) -> list[_DocKpi]:
        """算出（符合條件之）全部已發布文件之逐文件 KPI。

        **母體不含 TRAINING**（#567 B）——其閱讀由教育訓練模組追蹤，於此計算會固定低報。
        本方法是儀表板 / CSV / 週報總數 / 未讀提醒四個出口的共同來源，故排除只需做在這裡一處。
        """
        viewer_ids = await self._repo.viewer_ids(db)
        viewer_tags = await self._repo.viewer_audience_tags(db, viewer_ids)
        docs = await self._repo.list_published_docs(db, keyword=keyword, category=category)
        doc_ids = [d.doc_id for d in docs]
        doc_aud = await self._repo.doc_audience(db, doc_ids)
        reads = await self._repo.reads_current(db, doc_ids)

        stats: list[_DocKpi] = []
        for d in docs:
            readers = reads.get(d.doc_id, set())
            members, groups = _audience_breakdown(
                doc_aud.get(d.doc_id, {}), viewer_ids=viewer_ids, viewer_tags=viewer_tags, readers=readers
            )
            should_see = len(members)
            seen = len(members & readers)
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
                    groups=groups,
                )
            )
        return stats

    @staticmethod
    def _summary(stats: Sequence[_DocKpi]) -> KpiSummary:
        rated = [s.rate for s in stats if s.rate is not None]  # 排除應看=0（AC3a）
        overall = (sum(rated) / len(rated)) if rated else None
        below_50 = sum(1 for r in rated if r < 0.5)
        # `rated_docs` 是 `below_50_count` 的分母：兩者同母體（排除應看=0），而 `total_docs`
        # 含全部文件。並列顯示時若拿 total_docs 當分母，分子分母母體不同（#567 C）。
        return KpiSummary(total_docs=len(stats), rated_docs=len(rated), overall_rate=overall, below_50_count=below_50)

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
        """DM06 儀表板（FR-002，DM_ADMIN）：逐文件 KPI（後端分頁）+ 統計卡摘要 + 訓練教材清單。

        訓練教材另成一區、**不計任何閱讀統計**（#567 B）；該區不分頁，但有上限，超出時
        `training_total` 仍為實際筆數。
        """
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
                groups=s.groups,
            )
            for s in page_stats
        ]
        training_rows = await self._repo.list_published_docs(db, keyword=keyword, category=category, only_training=True)
        return KpiListResponse(
            data=data,
            meta={"total": total, "page": page, "limit": limit, "total_pages": total_pages},
            summary=summary,
            training_docs=[
                KpiTrainingDoc(
                    doc_id=r.doc_id,
                    doc_name=r.doc_name,
                    category_name=r.category_name,
                    current_version_no=r.current_version_no,
                )
                for r in training_rows[:_TRAINING_LIST_LIMIT]
            ],
            training_total=len(training_rows),
        )

    async def export_csv(
        self, db: AsyncSession, *, roles: Iterable[str], keyword: str | None, category: str | None
    ) -> bytes:
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
            result = await self._notifier.notify(db, template_code=_TPL_UNREAD, recipients=[prof.email], params=params)
            if result.queued_count:
                notified += 1
        return notified
