"""稽核 CSV 匯出筆數上限單元測試（#102）。

上限判斷只看 `count_logs` 回傳的筆數，以假 repository / audit 注入即可驗證，不需真 DB。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import AppError
from app.dp.audit.query_service import EXPORT_MAX_ROWS, AuditQueryService

pytestmark = pytest.mark.unit


def _service(count: int, fetched: int = 0) -> tuple[AuditQueryService, MagicMock, MagicMock]:
    repo = MagicMock()
    repo.count_logs = AsyncMock(return_value=count)
    repo.fetch_for_export = AsyncMock(return_value=[MagicMock() for _ in range(fetched)])
    audit = MagicMock()
    audit.log_action = AsyncMock()
    return AuditQueryService(repository=repo, audit=audit), repo, audit


async def _export(service: AuditQueryService) -> str:
    return await service.export_csv(
        MagicMock(),
        operator_id="admin01",
        operator=None,
        module=None,
        func_name=None,
        action_type=None,
        result=None,
        date_from=None,
        date_to=None,
    )


async def test_筆數等於上限_照常匯出() -> None:
    service, repo, audit = _service(EXPORT_MAX_ROWS)

    await _export(service)

    # 明細查詢帶 LIMIT 上限 + 1 當硬上限：count 與撈明細之間有新寫入時，記憶體仍有天花板
    assert repo.fetch_for_export.await_args.kwargs["limit"] == EXPORT_MAX_ROWS + 1
    audit.log_action.assert_awaited_once()


async def test_筆數超過上限_拋_DP_AUDIT_001_且不查明細不寫稽核() -> None:
    service, repo, audit = _service(EXPORT_MAX_ROWS + 1)

    with pytest.raises(AppError) as exc:
        await _export(service)

    assert exc.value.status_code == 422
    assert exc.value.error_code == "DP_AUDIT_001"
    repo.fetch_for_export.assert_not_awaited()
    audit.log_action.assert_not_awaited()


async def test_count_通過但撈明細時已超過上限_仍拋_DP_AUDIT_001_且不寫稽核() -> None:
    # count 與撈明細之間又寫入新紀錄（稽核表持續寫入）
    service, _, audit = _service(EXPORT_MAX_ROWS, fetched=EXPORT_MAX_ROWS + 1)

    with pytest.raises(AppError) as exc:
        await _export(service)

    assert exc.value.error_code == "DP_AUDIT_001"
    audit.log_action.assert_not_awaited()
