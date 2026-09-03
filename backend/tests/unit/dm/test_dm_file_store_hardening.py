"""檔案上傳加固（T066 L2 fail-closed 白名單 / M2 magic-byte）unit 測試（stub ParamService，無需 DB）。"""

import pytest

from app.core.exceptions import AppError
from app.dm.document.file_store import enforce_size_limit, is_previewable, resolve_upload_mime, validate_upload

pytestmark = pytest.mark.unit

_PDF_MAGIC = b"%PDF-1.4 ..."
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n...."


class _StubParam:
    """ParamService 替身：固定回傳指定之大小上限與副檔名白名單。"""

    def __init__(self, max_mb: int = 50, file_types: str = ""):
        self._max_mb = max_mb
        self._file_types = file_types

    async def get_int_param(self, db, param_id, key, default):
        return self._max_mb

    async def get_param_value(self, db, param_id, key):
        return self._file_types


# ── L2：DM_FILE_TYPES 缺值 → fail-closed 安全預設白名單 ──


async def test_empty_file_types_falls_back_to_safe_default_reject():
    """DM_FILE_TYPES 清空時，非預設白名單副檔名仍被擋（fail-closed，非 fail-open 放行）。"""
    with pytest.raises(AppError) as ei:
        await validate_upload(None, size_bytes=10, filename="evil.exe", params=_StubParam(file_types=""))
    assert ei.value.error_code == "DM_FILE_002"


async def test_empty_file_types_allows_default_whitelisted_ext():
    """DM_FILE_TYPES 清空時，預設白名單內副檔名（pdf）仍放行。"""
    await validate_upload(None, size_bytes=10, filename="ok.pdf", params=_StubParam(file_types=""))


async def test_custom_whitelist_still_enforced():
    """管理者自訂白名單（txt）→ 非白名單（pdf）擋、白名單（txt）放行。"""
    with pytest.raises(AppError) as ei:
        await validate_upload(None, size_bytes=10, filename="a.pdf", params=_StubParam(file_types="txt"))
    assert ei.value.error_code == "DM_FILE_002"
    await validate_upload(None, size_bytes=10, filename="a.txt", params=_StubParam(file_types="txt"))


async def test_oversize_still_blocked():
    with pytest.raises(AppError) as ei:
        await validate_upload(None, size_bytes=999 * 1024 * 1024, filename="ok.pdf", params=_StubParam(max_mb=50))
    assert ei.value.error_code == "DM_FILE_001"


# ── M1：read() 前之大小預檢（enforce_size_limit）──


async def test_enforce_size_limit_over_raises():
    with pytest.raises(AppError) as ei:
        await enforce_size_limit(None, size_bytes=2 * 1024 * 1024, params=_StubParam(max_mb=1))
    assert ei.value.error_code == "DM_FILE_001"


async def test_enforce_size_limit_within_ok():
    await enforce_size_limit(None, size_bytes=100, params=_StubParam(max_mb=1))


# ── M2：magic-byte 判定權威 MIME（可預覽 ⟺ 已驗證）──


def test_previewable_ext_matching_magic_returns_authoritative_mime():
    assert resolve_upload_mime(_PDF_MAGIC, "a.pdf", "application/pdf") == "application/pdf"
    assert resolve_upload_mime(_PNG_MAGIC, "b.png", "image/png") == "image/png"
    # jpg / jpeg 皆歸 image/jpeg
    assert resolve_upload_mime(b"\xff\xd8\xff\xe0xxxx", "c.jpg", "image/jpeg") == "image/jpeg"


def test_previewable_ext_wrong_magic_rejected():
    """.pdf 副檔名但檔頭非 PDF（evil.exe 改名 evil.pdf）→ DM_FILE_002。"""
    with pytest.raises(AppError) as ei:
        resolve_upload_mime(b"MZ\x90\x00 not a pdf", "evil.pdf", "application/pdf")
    assert ei.value.error_code == "DM_FILE_002"


def test_previewable_ext_ignores_client_mime_uses_server():
    """.png 內容實為 PDF → 以副檔名 png 之期望比對（magic 非 PNG）→ 擋（不信用戶端 content_type）。"""
    with pytest.raises(AppError):
        resolve_upload_mime(_PDF_MAGIC, "x.png", "image/png")


def test_non_previewable_ext_keeps_office_mime():
    office = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert resolve_upload_mime(b"PK\x03\x04....", "d.docx", office) == office
    assert is_previewable(resolve_upload_mime(b"PK\x03\x04....", "d.docx", office)) is False


def test_non_previewable_ext_strips_lied_previewable_mime():
    """非可預覽副檔名但用戶端謊報可預覽 MIME → 剝除為 octet-stream（不會被當可預覽內嵌）。"""
    resolved = resolve_upload_mime(b"MZ\x90\x00 exe", "sneaky.docx", "image/png")
    assert resolved == "application/octet-stream"
    assert is_previewable(resolved) is False
