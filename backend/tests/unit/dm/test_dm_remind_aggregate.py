"""催辦逐人彙整之分組邏輯（#699）。

## 為何是 unit

要驗的是**分組與組信**這段純邏輯：誰跟誰併成一封、清單怎麼排、數字怎麼算。
依 `.claude/rules/sti-testing.md` 的閘門「拿掉真 DB 還驗得了嗎」——驗得了，
故不寫 integration。真的排進 outbox 那條（接線）留在
`tests/integration/dm/test_dm_review.py::test_scan_overdue_reminds`。

## 為何逐筆 warning 要單獨釘住

四類「催辦未寄出」（查無帳號 / 停用 / 無角色 / 無 Email）的 warning 帶
`review_id` / `doc_id`，是給人拿去追積壓用的。彙整很容易順手把它們也合併成
一條——那會讓「一位停用審核者卡著三件」變成 log 上只剩一件。
`scan_overdue_and_remind` 既有註解已明說「日後有人會照這行 log 去查」。
"""

import logging
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.utils import utcnow
from app.dm.review.center_service import ReviewCenterService
from app.dm.review.repository import ReviewCenterRepository

pytestmark = pytest.mark.unit


def _row(*, review_id: int, doc_id: str, doc_name: str, reviewer: str, days: int, **over):
    """模擬 `list_overdue_pending` 的一列（欄位名逐字對齊該查詢的 label）。"""
    base = dict(
        review_id=review_id,
        doc_id=doc_id,
        doc_name=doc_name,
        assigned_reviewer=reviewer,
        submit_date=utcnow() - timedelta(days=days),
        reviewer_email=f"{reviewer}@e.com",
        reviewer_name=f"{reviewer} 審核",
        reviewer_status="ACTIVE",
        reviewer_deleted=0,
        reviewer_has_role=True,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _svc(rows, *, queued=1):
    """以 mock repo / notifier 組出受測 service；回傳 (service, notify_mock)。

    `waiting_days` 委派真實的 static method——它是純函式，mock 掉反而會讓
    「清單裡的天數算錯」這類缺陷驗不到。
    """
    repo = MagicMock()
    repo.list_overdue_pending = AsyncMock(return_value=rows)
    repo.waiting_days = ReviewCenterRepository.waiting_days
    # 只讀 `.queued_count` / `.skipped_reason` 兩個屬性，不綁平台 SendResult 的其餘形狀
    notify = AsyncMock(return_value=SimpleNamespace(queued_count=queued, skipped_reason=None))
    notifier = MagicMock(notify=notify)
    return ReviewCenterService(repository=repo, notifier=notifier), notify


async def test_同一審核者多筆逾期只組一封():
    """本 issue 的核心：3 筆逾期 → 1 封，而不是 3 封。"""
    rows = [
        _row(review_id=1, doc_id="D1", doc_name="採血SOP", reviewer="rev1", days=10),
        _row(review_id=2, doc_id="D2", doc_name="輸血SOP", reviewer="rev1", days=9),
        _row(review_id=3, doc_id="D3", doc_name="製備SOP", reviewer="rev1", days=8),
    ]
    svc, notify = _svc(rows)

    await svc.scan_overdue_and_remind(MagicMock(), threshold_days=7)

    assert notify.await_count == 1, "同一位審核者的多筆逾期必須彙整成一封"
    params = notify.await_args.kwargs["params"]
    assert params["pending_count"] == "3"
    for name in ("採血SOP", "輸血SOP", "製備SOP"):
        assert name in params["pending_list"], f"彙整清單漏了 {name}"


async def test_彙整清單依停留最久者在前():
    """跨日順序必須穩定，否則同一批案件每天長得不一樣。

    `list_overdue_pending` 沒有 ORDER BY（查詢回傳順序不保證），故排序由 service 負責；
    此處刻意以**亂序**輸入，順序正確才能通過。
    """
    rows = [
        _row(review_id=1, doc_id="D1", doc_name="中間", reviewer="rev1", days=9),
        _row(review_id=2, doc_id="D2", doc_name="最久", reviewer="rev1", days=30),
        _row(review_id=3, doc_id="D3", doc_name="最近", reviewer="rev1", days=8),
    ]
    svc, notify = _svc(rows)

    await svc.scan_overdue_and_remind(MagicMock(), threshold_days=7)

    listing = notify.await_args.kwargs["params"]["pending_list"]
    assert listing.index("最久") < listing.index("中間") < listing.index("最近")
    # 正向錨點：天數真的算進清單（只驗順序的話，不印天數也會通過）
    assert "30 天" in listing


async def test_兩位審核者的清單不交叉():
    rows = [
        _row(review_id=1, doc_id="D1", doc_name="甲的文件", reviewer="rev1", days=10),
        _row(review_id=2, doc_id="D2", doc_name="乙的文件", reviewer="rev2", days=11),
        _row(review_id=3, doc_id="D3", doc_name="甲的另一份", reviewer="rev1", days=12),
    ]
    svc, notify = _svc(rows)

    await svc.scan_overdue_and_remind(MagicMock(), threshold_days=7)

    assert notify.await_count == 2
    by_to = {call.kwargs["recipients"][0]: call.kwargs["params"] for call in notify.await_args_list}
    assert by_to["rev1@e.com"]["pending_count"] == "2"
    assert "乙的文件" not in by_to["rev1@e.com"]["pending_list"]
    assert by_to["rev2@e.com"]["pending_count"] == "1"
    assert "甲的文件" not in by_to["rev2@e.com"]["pending_list"]


async def test_停用審核者的三筆各留一條_warning(caplog):
    """跳過的 warning 不得跟著彙整——它是拿來追「哪幾件卡住」的。"""
    rows = [
        _row(review_id=i, doc_id=f"D{i}", doc_name=f"文件{i}", reviewer="off", days=10, reviewer_status="DISABLED")
        for i in (1, 2, 3)
    ]
    svc, notify = _svc(rows)

    with caplog.at_level(logging.WARNING, logger="app.dm.review.center_service"):
        await svc.scan_overdue_and_remind(MagicMock(), threshold_days=7)

    assert notify.await_count == 0
    skipped = [r for r in caplog.records if "催辦未寄出" in r.getMessage()]
    assert len(skipped) == 3, "三筆各自留痕，不得合併成一條"
    for i in (1, 2, 3):
        assert any(f"review_id={i}" in r.getMessage() for r in skipped), f"review_id={i} 沒有留下 warning"


async def test_回傳封數與涵蓋筆數():
    """`count` 的語意自本 issue 起是**封數**；筆數另外回，否則積壓規模會從 log 消失。"""
    rows = [
        _row(review_id=1, doc_id="D1", doc_name="A", reviewer="rev1", days=10),
        _row(review_id=2, doc_id="D2", doc_name="B", reviewer="rev1", days=9),
        _row(review_id=3, doc_id="D3", doc_name="C", reviewer="rev2", days=8),
    ]
    svc, _ = _svc(rows)

    result = await svc.scan_overdue_and_remind(MagicMock(), threshold_days=7)

    assert result.emails == 2, "兩位審核者＝兩封"
    assert result.items == 3, "涵蓋三筆"


async def test_未排入_outbox_時不計入且留下該封涵蓋的_review_ids(caplog):
    """沿用 #627 的原則：沒有真的進 outbox 就不計入，且要留痕。

    彙整後一封涵蓋多筆，warning 必須列出**全部** review_id，否則追查者只會看到其中一件。
    """
    rows = [
        _row(review_id=11, doc_id="D1", doc_name="A", reviewer="rev1", days=10),
        _row(review_id=12, doc_id="D2", doc_name="B", reviewer="rev1", days=9),
    ]
    svc, _ = _svc(rows, queued=0)

    with caplog.at_level(logging.WARNING, logger="app.dm.review.center_service"):
        result = await svc.scan_overdue_and_remind(MagicMock(), threshold_days=7)

    assert result.emails == 0
    assert result.items == 0, "沒寄出去就不算涵蓋"
    text = caplog.text
    assert "11" in text and "12" in text, "warning 必須列出該封涵蓋的全部 review_id"
