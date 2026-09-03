"""永久保留 / append-only 契約回歸（T064，unit，無需 DB）。

以 ORM 模型內省守門「永久保留」設計，防未來誤加可竄改 / 可刪除欄位或路徑：
- append-only 記錄表（DM_CHANGE_LOG / DM_USER_ROLE_LOG）：僅 CREATED_*，**無** UPDATED_* / DELETED
  → 無任何欄位可承載「修改 / 軟刪除」，落實不可竄改不可刪除（spec.md SC / data-model append-only 契約）。
- 版本表（DM_DOC_VERSION）採**軟刪除**：具 DELETED 欄（永久保留、以 DELETED=1 標記，不實體刪）。
"""

import pytest

from app.dm.document.models import DmDocVersion
from app.dm.review.models import DmChangeLog
from app.dm.roles.models import DmUserRoleLog

pytestmark = pytest.mark.unit

_MUTABLE_COLS = {"UPDATED_USER", "UPDATED_DATE", "DELETED"}


def _cols(model) -> set[str]:
    return {c.name for c in model.__table__.columns}


def test_change_log_is_append_only():
    cols = _cols(DmChangeLog)
    assert {"CREATED_USER", "CREATED_DATE"} <= cols
    assert not (_MUTABLE_COLS & cols), f"DM_CHANGE_LOG 不應有可竄改/軟刪欄位：{_MUTABLE_COLS & cols}"


def test_user_role_log_is_append_only():
    cols = _cols(DmUserRoleLog)
    assert {"CREATED_USER", "CREATED_DATE"} <= cols
    assert not (_MUTABLE_COLS & cols), f"DM_USER_ROLE_LOG 不應有可竄改/軟刪欄位：{_MUTABLE_COLS & cols}"


def test_doc_version_uses_soft_delete():
    """版本永久保留：以 DELETED 軟刪除標記，不採實體刪除。"""
    assert "DELETED" in _cols(DmDocVersion)
