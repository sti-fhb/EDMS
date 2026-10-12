"""`DmNotifier` 的收件人分批與失敗邊界（#563）。

## 為何這支測試存在

平台 `NotifyService.send_email` 對單次收件人數設有上限（`MAX_RECIPIENTS`），超過即拋
`AppError(422, DP_MAIL_002)`。DM 是**全專案僅有的多人清單呼叫方**（ET 11 處全部
`recipients=[一個人]`），而 `_notify_publish` 把全部可見對象相符的閱覽者一次傳入。

那個例外會一路冒到 router，`get_db` 隨即 rollback 整個交易——於是「可見對象超過 50 人」
的文件**核准不了**：文件沒轉 PUBLISHED、版本沒切、`DM_CHANGE_LOG` 沒寫、稽核沒寫，
而審核者看到的錯誤訊息在講寄信。

⚠️ **這個缺陷在 integration 測試裡結構性看不到**——觸發要 51 位可見對象相符的
`DM_VIEWER`，fixture 不會建那麼多人。所以「CI 全綠」對它零證據力。真正建 51 人的驗證
在 `tests/integration/dm/test_dm_review.py`；本檔負責把分批**邏輯**的邊界釘死，
並涵蓋 integration 不便製造的失敗路徑。
"""

import pytest
from sqlalchemy.exc import OperationalError

from app.core.exceptions import AppError
from app.dm.kpi.schemas import KpiSummary
from app.dm.kpi.service import KpiService
from app.dm.notify.service import DmNotifier
from app.services import MAX_RECIPIENTS, SendResult

pytestmark = pytest.mark.unit


class _FakeNotify:
    """記錄每次 `send_email` 收到的收件人批次；回傳值可由建構參數指定。"""

    def __init__(
        self, result: SendResult | None = None, raise_on_call: int | None = None, exc: Exception | None = None
    ):
        self.batches: list[list[str]] = []
        self._result = result or SendResult(queued_count=0, skipped_reason=None)
        self._raise_on_call = raise_on_call
        self._exc = exc

    async def send_email(self, db, *, recipients, template_code, module, params, caller_module) -> SendResult:
        self.batches.append(list(recipients))
        if self._raise_on_call is not None and len(self.batches) == self._raise_on_call:
            raise self._exc
        # 未指定固定回傳時，比照平台：排入數即本批人數
        if self._result.queued_count == -1:
            return SendResult(queued_count=len(recipients), skipped_reason=None)
        return self._result


def _emails(n: int) -> list[str]:
    return [f"zt_user{i:03d}@example.com" for i in range(n)]


def _notifier(fake: _FakeNotify) -> DmNotifier:
    return DmNotifier(notify=fake)  # type: ignore[arg-type]


async def _notify(fake: _FakeNotify, n: int) -> SendResult:
    return await _notifier(fake).notify(
        None, template_code="DOC_PUBLISH", recipients=_emails(n), params={"doc_name": "ZT 測試文件"}
    )


class Test分批邊界:
    """每批不得超過平台上限，且總數不得漏人。"""

    @pytest.mark.parametrize(
        ("total", "expected_batches"),
        [
            (1, [1]),
            (MAX_RECIPIENTS - 1, [MAX_RECIPIENTS - 1]),
            (MAX_RECIPIENTS, [MAX_RECIPIENTS]),  # 剛好上限仍是一批，不該多切一個空批
            (MAX_RECIPIENTS + 1, [MAX_RECIPIENTS, 1]),  # 本 issue 的觸發點
            (MAX_RECIPIENTS * 2, [MAX_RECIPIENTS, MAX_RECIPIENTS]),
            (MAX_RECIPIENTS * 2 + 1, [MAX_RECIPIENTS, MAX_RECIPIENTS, 1]),
        ],
    )
    async def test_切批大小與順序(self, total: int, expected_batches: list[int]) -> None:
        fake = _FakeNotify(SendResult(queued_count=-1))
        result = await _notify(fake, total)

        assert [len(b) for b in fake.batches] == expected_batches
        # 總數錨點：切批不得漏人、不得重複
        assert sum(len(b) for b in fake.batches) == total
        assert [e for b in fake.batches for e in b] == _emails(total)
        assert result.queued_count == total

    async def test_沒有任何一批超過平台上限(self) -> None:
        """本檔的核心不變量：平台只要有一批超過上限就會拋 DP_MAIL_002。"""
        fake = _FakeNotify(SendResult(queued_count=-1))
        await _notify(fake, 237)

        assert fake.batches, "一批都沒送出，下面的 all() 會恆真"
        assert all(len(b) <= MAX_RECIPIENTS for b in fake.batches)

    async def test_空清單不呼叫平台(self) -> None:
        """呼叫端（`_notify_publish` / `_send_weekly_report`）本來就會先擋空清單，此處確立契約。"""
        fake = _FakeNotify(SendResult(queued_count=-1))
        result = await _notify(fake, 0)

        assert fake.batches == []
        assert result.queued_count == 0
        assert result.skipped_reason is None


class Test略過原因的聚合:
    """範本層級的略過原因對每一批都相同，聚合後只回報一次。"""

    @pytest.mark.parametrize("reason", ["TEMPLATE_DISABLED", "CHANNEL_NOT_EMAIL"])
    async def test_範本層級略過原因照實回傳(self, reason: str) -> None:
        fake = _FakeNotify(SendResult(queued_count=0, skipped_reason=reason))
        result = await _notify(fake, MAX_RECIPIENTS + 1)

        assert result.queued_count == 0
        assert result.skipped_reason == reason

    async def test_渲染失敗時每一批都仍被送出(self) -> None:
        """渲染失敗回 `(0, None)` 但**會把該批收件人寫成 FAILED**。

        ⚠️ 若在第一批就短路，後面的收件人不會留下 FAILED 列——`DP_EMAIL_LOG` 是
        「誰沒收到信」的唯一軌跡（前端沒有任何畫面顯示它），截斷等於把稽核軌跡砍掉。
        """
        fake = _FakeNotify(SendResult(queued_count=0, skipped_reason=None))
        result = await _notify(fake, MAX_RECIPIENTS * 2 + 1)

        assert len(fake.batches) == 3, "短路的話這裡會是 1"
        assert sum(len(b) for b in fake.batches) == MAX_RECIPIENTS * 2 + 1
        assert result.queued_count == 0
        assert result.skipped_reason is None


class Test失敗邊界:
    """只吞 `AppError`；DB 層例外必須續拋。"""

    async def test_吞下_apperror_並保住已排入的數量(self) -> None:
        """⚠️ 回 `queued_count=0` 會是說謊——第一批的人**已經**寫進 outbox 了。"""
        fake = _FakeNotify(
            SendResult(queued_count=-1),
            raise_on_call=2,
            exc=AppError(status_code=404, detail="通知範本不存在", error_code="DP_MAIL_001"),
        )
        result = await _notify(fake, MAX_RECIPIENTS + 1)

        assert len(fake.batches) == 2, "第二批確實被呼叫到（否則下面驗不到吞的行為）"
        assert result.queued_count == MAX_RECIPIENTS
        assert result.skipped_reason == "SEND_FAILED"

    async def test_資料庫層例外必須往上拋(self) -> None:
        """那不是「信寄不出去」，是這個交易本來就壞了——吞掉只會讓後續寫入在更遠的地方失敗。

        （理由逐字取自 `app/et/notify/service.py` 模組 docstring，本檔比照。）
        """
        fake = _FakeNotify(
            SendResult(queued_count=-1),
            raise_on_call=1,
            exc=OperationalError("SELECT 1", {}, Exception("connection closed")),
        )
        with pytest.raises(OperationalError):
            await _notify(fake, MAX_RECIPIENTS + 1)


class Test週報走同一個出口:
    """`SCHDM001` 的 KPI 週報收件人是「全部 `DM_ADMIN`」，同樣沒有上限（#563 第二處）。

    分批收在 `DmNotifier` 之後，`_send_weekly_report` 一行都不用改就受涵蓋。本測試釘的正是
    這件事——若日後有人把分批搬回各呼叫點而漏掉這裡，它會紅。
    """

    class _FakeKpiRepo:
        def __init__(self, emails: list[str]) -> None:
            self._emails = emails

        async def admin_emails(self, db) -> list[str]:
            return self._emails

    @staticmethod
    def _summary() -> KpiSummary:
        return KpiSummary(total_docs=3, rated_docs=2, overall_rate=0.5, below_50_count=1)

    async def test_管理者超過上限時週報仍全數排入(self) -> None:
        admins = _emails(MAX_RECIPIENTS + 1)
        fake = _FakeNotify(SendResult(queued_count=-1))
        svc = KpiService(repository=self._FakeKpiRepo(admins), notifier=_notifier(fake))  # type: ignore[arg-type]

        queued = await svc._send_weekly_report(None, stats=[], summary=self._summary())

        assert [len(b) for b in fake.batches] == [MAX_RECIPIENTS, 1]
        assert queued == MAX_RECIPIENTS + 1

    async def test_沒有管理者時不呼叫平台(self) -> None:
        """正向錨點：上面那條若因 `admin_emails` 回空而「通過」，這條會顯示差別。"""
        fake = _FakeNotify(SendResult(queued_count=-1))
        svc = KpiService(repository=self._FakeKpiRepo([]), notifier=_notifier(fake))  # type: ignore[arg-type]

        queued = await svc._send_weekly_report(None, stats=[], summary=self._summary())

        assert fake.batches == []
        assert queued == 0
