"""base_model 標準欄位測試（對齊 EDMS 平台模組 DP：單一組織、無 SITE 維度）。

EDMS 為單一組織，標準欄位省略 CREATED_SITE / UPDATED_SITE
（見 docs/specs/dp/data-model.md 標準欄位、docs/specs/dp/research.md §1、
docs/_refs/09-平台模組.md §1.4）。本測試確保四個基底類別皆不含 SITE 欄位，
且各自的標準欄位集合正確。
"""

import pytest
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import (
    AuditLogBaseModel,
    BaseModel,
    BaseModelHardDelete,
    BaseModelNoResId,
)

pytestmark = pytest.mark.unit


# 以具體子類別觸發 table 映射後檢視實際欄位（DB 欄位名為大寫）。
class _ConcreteStandard(BaseModel):
    __tablename__ = "_test_concrete_standard"
    id: Mapped[str] = mapped_column("ID", String(10), primary_key=True)


class _ConcreteNoResId(BaseModelNoResId):
    __tablename__ = "_test_concrete_no_res_id"
    id: Mapped[str] = mapped_column("ID", String(10), primary_key=True)


class _ConcreteAuditLog(AuditLogBaseModel):
    __tablename__ = "_test_concrete_audit_log"
    id: Mapped[str] = mapped_column("ID", String(10), primary_key=True)


class _ConcreteHardDelete(BaseModelHardDelete):
    __tablename__ = "_test_concrete_hard_delete"
    id: Mapped[str] = mapped_column("ID", String(10), primary_key=True)


def _column_names(model) -> set[str]:
    return {c.name for c in model.__table__.columns}


def test_no_site_columns() -> None:
    """四個基底類別皆不得含 CREATED_SITE / UPDATED_SITE（EDMS 單一組織）。"""
    for model in (
        _ConcreteStandard,
        _ConcreteNoResId,
        _ConcreteAuditLog,
        _ConcreteHardDelete,
    ):
        cols = _column_names(model)
        assert "CREATED_SITE" not in cols, f"{model.__name__} 不應含 CREATED_SITE"
        assert "UPDATED_SITE" not in cols, f"{model.__name__} 不應含 UPDATED_SITE"


def test_standard_columns_present() -> None:
    """各基底類別之標準欄位集合須「精確」符合 data-model 定義（不含 SITE、不多帶欄位）。

    以 == 精確比對（含測試子類別自帶的 ID 主鍵），確保未來不慎多帶非預期標準欄位亦會被捕捉。
    """
    # BaseModel：完整標準欄位（含 RES_ID + DELETED）
    assert _column_names(_ConcreteStandard) == {
        "ID",
        "CREATED_USER",
        "CREATED_DATE",
        "UPDATED_USER",
        "UPDATED_DATE",
        "RES_ID",
        "DELETED",
    }
    # BaseModelNoResId：無 RES_ID
    assert _column_names(_ConcreteNoResId) == {
        "ID",
        "CREATED_USER",
        "CREATED_DATE",
        "UPDATED_USER",
        "UPDATED_DATE",
        "DELETED",
    }
    # AuditLogBaseModel：append-only，僅 CREATED_*
    assert _column_names(_ConcreteAuditLog) == {"ID", "CREATED_USER", "CREATED_DATE"}
    # BaseModelHardDelete：含 RES_ID、無 DELETED
    assert _column_names(_ConcreteHardDelete) == {
        "ID",
        "CREATED_USER",
        "CREATED_DATE",
        "UPDATED_USER",
        "UPDATED_DATE",
        "RES_ID",
    }
