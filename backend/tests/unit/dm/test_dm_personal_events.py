"""我的文件動態之事件展開（`PersonalService._build_events`）——純邏輯，不連 DB。

## 為什麼這檔必須存在（2026-09-23 由變異檢查逼出來）

30 天窗口在**兩層**各擋一次：查詢層 `repository._within_window_or_pending`、
service 層 `_build_events` 的日期判斷。兩層互為後盾，於是**拿掉任一層，整合測試都照樣全綠**
——實測兩個變異（拿掉 service 那道／拿掉查詢層整個條件）都是 31 passed。

⚠️ 那不是護欄失效，是**整合測試在斷言一個由兩個機制共同保證的結果**，因此偵測不到
任一層單獨失守。要釘住個別層，就得繞過另一層——本檔以合成的 row 直餵 `_build_events`，
把 service 那層獨立起來。查詢層則由整合測試負責。
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.dm.personal.service import PersonalService

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 23, tzinfo=timezone.utc)
_SINCE = _NOW - timedelta(days=30)


def _row(**kw):
    """合成一列送審週期；預設為可達的正常審核者。"""
    base = dict(
        review_id=1,
        doc_id="DM-SOP-000001",
        doc_name="文件",
        review_type="NEW",
        status="PENDING",
        submit_date=_NOW - timedelta(days=1),
        complete_date=None,
        party_name="王審核",
        party_status="ACTIVE",
        party_deleted=0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _build(rows):
    return PersonalService._build_events(rows, since=_SINCE, now=_NOW, threshold=7)


def test_pending_逾窗口仍產生送審事件():
    """D-1：`PENDING` 是當前狀態不是歷程，不受窗口限制（#395）。"""
    events = _build([_row(submit_date=_NOW - timedelta(days=100))])
    assert len(events) == 1
    assert events[0].event_kind == "submitted" and events[0].is_overdue


def test_已結案且逾窗口者不產生任何事件():
    """⛔ 豁免只給 `PENDING`——已結案是歷程，逾窗口就該消失，否則動態無限成長。

    ⚠️ 這條在整合測試裡**抓不到**：查詢層會先把這一列濾掉，service 這道判斷因而
    永遠走不到。本檔直餵 row 才驗得出 service 自己有沒有守住。
    """
    events = _build(
        [
            _row(
                status="APPROVED",
                submit_date=_NOW - timedelta(days=100),
                complete_date=_NOW - timedelta(days=99),
            )
        ]
    )
    assert events == []


def test_已結案且在窗口內產生兩列事件():
    """同一週期展開為 送審 + 結果 兩列（既有行為的回歸護欄）。"""
    events = _build(
        [
            _row(
                status="APPROVED",
                submit_date=_NOW - timedelta(days=5),
                complete_date=_NOW - timedelta(days=2),
            )
        ]
    )
    assert [e.event_kind for e in events] == ["resolved", "submitted"]  # 時間新→舊


def test_未逾門檻之_pending_不標逾期():
    events = _build([_row(submit_date=_NOW - timedelta(days=3))])
    assert events[0].is_overdue is False


@pytest.mark.parametrize(
    ("party_status", "party_deleted", "expected"),
    [
        ("ACTIVE", 0, None),
        ("DISABLED", 0, "DISABLED"),
        (None, None, "NOT_FOUND"),  # outerjoin 落空：整組欄位皆為 None
        ("ACTIVE", 1, "DISABLED"),  # DELETED 目前恆 0，保留為 fail-closed
    ],
    ids=["可達", "已停用", "查無帳號", "已刪除"],
)
def test_對造人不可達的三種判讀(party_status, party_deleted, expected):
    """⚠️ 「查無帳號」與「已停用」**不可併成一句**——`None != "ACTIVE"` 也成立，
    併起來會告訴撰寫者「審核者帳號已停用」而真相是「那個 user_id 不存在」。
    兩者補救動作不同（修資料 vs 換審核者）。
    """
    events = _build([_row(party_status=party_status, party_deleted=party_deleted)])
    assert events[0].party_unreachable == expected
