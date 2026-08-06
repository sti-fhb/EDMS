"""檔案上傳檢核整合測試（讀種子之 DM_FILE_MAX_MB=50 / DM_FILE_TYPES）。"""

import pytest

from app.core.exceptions import AppError
from app.dm.document.file_store import validate_upload

pytestmark = pytest.mark.integration


async def test_within_limit_and_allowed_type_ok(db):
    """50MB 內、允許格式 → 通過。"""
    await validate_upload(db, size_bytes=10 * 1024 * 1024, filename="doc.pdf")


async def test_over_size_limit_rejected(db):
    """逾 50MB → DM_FILE_001。"""
    with pytest.raises(AppError) as e:
        await validate_upload(db, size_bytes=51 * 1024 * 1024, filename="big.pdf")
    assert e.value.error_code == "DM_FILE_001"


async def test_disallowed_type_rejected(db):
    """不在 DM_FILE_TYPES 之副檔名 → DM_FILE_002。"""
    with pytest.raises(AppError) as e:
        await validate_upload(db, size_bytes=1024, filename="virus.exe")
    assert e.value.error_code == "DM_FILE_002"
