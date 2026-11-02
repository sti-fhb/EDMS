"""檔案上傳加固（T066 L2 fail-closed 白名單 / M2 magic-byte）unit 測試（stub ParamService，無需 DB）。"""

from io import BytesIO

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.core.exceptions import AppError
from app.dm.document.file_store import (
    MAX_FILE_NAME_LEN,
    enforce_size_limit,
    is_previewable,
    read_upload,
    resolve_upload_mime,
    validate_upload,
)

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


# ── M2：伺服端由副檔名 + magic 判定權威 MIME（可預覽 ⟺ 已驗證；完全不採用戶端 content_type）──

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_previewable_ext_matching_magic_returns_authoritative_mime():
    assert resolve_upload_mime(_PDF_MAGIC, "a.pdf") == "application/pdf"
    assert resolve_upload_mime(_PNG_MAGIC, "b.png") == "image/png"
    # jpg / jpeg 皆歸 image/jpeg
    assert resolve_upload_mime(b"\xff\xd8\xff\xe0xxxx", "c.jpg") == "image/jpeg"


def test_previewable_ext_wrong_magic_rejected():
    """.pdf 副檔名但檔頭非 PDF（evil.exe 改名 evil.pdf）→ DM_FILE_005（內容與副檔名不符，#211 L1）。"""
    with pytest.raises(AppError) as ei:
        resolve_upload_mime(b"MZ\x90\x00 not a pdf", "evil.pdf")
    assert ei.value.status_code == 422
    assert ei.value.error_code == "DM_FILE_005"


def test_png_ext_with_pdf_content_rejected():
    """.png 副檔名但內容實為 PDF → magic 與副檔名不符 → 擋（伺服端判定，非信用戶端）。"""
    with pytest.raises(AppError) as ei:
        resolve_upload_mime(_PDF_MAGIC, "x.png")
    assert ei.value.error_code == "DM_FILE_005"


def test_office_ext_derives_server_mime_not_previewable():
    """Office 副檔名 → 落地 MIME 由伺服端映射（權威）、非可預覽（僅下載）。"""
    resolved = resolve_upload_mime(b"PK\x03\x04....", "d.docx")
    assert resolved == _DOCX_MIME
    assert is_previewable(resolved) is False


def test_unknown_ext_falls_back_to_octet_stream():
    """未知/未映射副檔名 → application/octet-stream（非可預覽），完全不受用戶端宣稱影響。"""
    resolved = resolve_upload_mime(b"<html>evil</html>", "sneaky.bin")
    assert resolved == "application/octet-stream"
    assert is_previewable(resolved) is False


# ── L1：白名單內 Office 類亦以檔頭驗真實型別（#211）──
#
# 先前只驗可預覽類（PDF / 圖片），Office 類只看副檔名——`.exe` 改名 `.docx` 照樣落盤。

_ZIP_MAGIC = b"PK\x03\x04"
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_OFFICE_EXTS = ["docx", "xlsx", "pptx", "doc", "xls", "ppt"]


@pytest.mark.parametrize(
    ("filename", "head"),
    [
        ("a.docx", _ZIP_MAGIC),
        ("a.xlsx", _ZIP_MAGIC),
        ("a.pptx", _ZIP_MAGIC),
        ("a.doc", _OLE2_MAGIC),
        ("a.xls", _OLE2_MAGIC),
        ("a.ppt", _OLE2_MAGIC),
    ],
)
def test_office_ext_with_matching_magic_passes(filename, head):
    resolved = resolve_upload_mime(head + b"....", filename)
    assert resolved != "application/octet-stream"
    assert is_previewable(resolved) is False


@pytest.mark.parametrize("ext", _OFFICE_EXTS)
def test_office_ext_with_wrong_magic_rejected(ext):
    """`.exe` 改名成任一 Office 副檔名 → 422 DM_FILE_005。"""
    with pytest.raises(AppError) as ei:
        resolve_upload_mime(b"MZ\x90\x00 renamed exe", f"evil.{ext}")
    assert ei.value.status_code == 422
    assert ei.value.error_code == "DM_FILE_005"


@pytest.mark.parametrize("ext", ["docx", "xlsx", "pptx"])
def test_password_protected_ooxml_with_ole2_container_passes(ext):
    """加密的 docx / xlsx / pptx 以 OLE2 容器存放（EncryptedPackage），不是 ZIP——不可誤擋。"""
    resolve_upload_mime(_OLE2_MAGIC + b"....", f"secret.{ext}")


@pytest.mark.parametrize("ext", ["doc", "xls", "ppt"])
def test_legacy_office_ext_with_zip_content_rejected(ext):
    """舊版 Office 副檔名只認 OLE2；ZIP 內容不屬於這三種格式。"""
    with pytest.raises(AppError) as ei:
        resolve_upload_mime(_ZIP_MAGIC + b"....", f"a.{ext}")
    assert ei.value.error_code == "DM_FILE_005"


def test_empty_office_file_rejected():
    """0 位元組的 docx 沒有任何格式可言，比照 PDF 一併擋下。

    ⚠️ 僅限函式層：兩支 service 以 `if not file_bytes` 判斷附檔與否，空 bytes 視同「未附檔」，
    走不到這裡——HTTP 路徑上傳空檔不會回 422。
    """
    with pytest.raises(AppError) as ei:
        resolve_upload_mime(b"", "empty.docx")
    assert ei.value.error_code == "DM_FILE_005"


@pytest.mark.parametrize("filename", ["notes.txt", "list.csv"])
def test_ext_without_fixed_header_only_checked_by_whitelist(filename):
    """txt / csv 等無固定檔頭的格式（管理者可經 DM_FILE_TYPES 加入）維持只驗副檔名，不做檔頭比對。"""
    assert resolve_upload_mime(b"any,content\n", filename) == "application/octet-stream"


# ── M1：讀取時即把關大小（#211）──


class _CountingStream(BytesIO):
    """記錄實際被讀出多少位元組——用來證明超限時「沒有整包讀進記憶體」。"""

    def __init__(self, data: bytes):
        super().__init__(data)
        self.bytes_read = 0

    def read(self, size: int | None = -1) -> bytes:
        chunk = super().read(size)
        self.bytes_read += len(chunk)
        return chunk


def _upload(data: bytes, *, size: int | None) -> tuple[UploadFile, _CountingStream]:
    stream = _CountingStream(data)
    headers = Headers({"content-type": "application/pdf"})
    return UploadFile(file=stream, size=size, filename="a.pdf", headers=headers), stream


async def test_read_upload_without_file_returns_none():
    assert await read_upload(None, None, params=_StubParam()) == (None, None, None)


async def test_read_upload_known_size_over_limit_rejected_before_any_read():
    """`UploadFile.size` 已知且超限 → 一個位元組都不讀就擋下。"""
    data = b"x" * (2 * 1024 * 1024)
    file, stream = _upload(data, size=len(data))
    with pytest.raises(AppError) as ei:
        await read_upload(None, file, params=_StubParam(max_mb=1))
    assert ei.value.error_code == "DM_FILE_001"
    assert stream.bytes_read == 0


async def test_read_upload_unknown_size_reads_at_most_limit_plus_one():
    """`size` 取不到時最多只讀「上限 + 1」位元組即判超限，不把剩下的內容讀進記憶體。"""
    data = b"x" * (5 * 1024 * 1024)
    file, stream = _upload(data, size=None)
    with pytest.raises(AppError) as ei:
        await read_upload(None, file, params=_StubParam(max_mb=1))
    assert ei.value.error_code == "DM_FILE_001"
    assert stream.bytes_read == 1024 * 1024 + 1


async def test_read_upload_unknown_size_exactly_at_limit_passes():
    """上限本身不可誤擋——只測超限的話，把判斷寫成 `>=` 也會過。"""
    data = b"x" * (1024 * 1024)
    file, _ = _upload(data, size=None)
    name, body, mime = await read_upload(None, file, params=_StubParam(max_mb=1))
    assert (name, body, mime) == ("a.pdf", data, "application/pdf")


async def test_read_upload_known_size_within_limit_returns_full_content():
    data = b"%PDF-1.4 " + b"x" * (3 * 1024 * 1024)
    file, _ = _upload(data, size=len(data))
    _, body, _ = await read_upload(None, file, params=_StubParam(max_mb=50))
    assert body == data


# ── 檔名長度（#697）──────────────────────────────────────────────


async def test_檔名超過欄位長度回_422_而非_500():
    """`DM_DOC_VERSION.FILE_NAME` / `DM_REVIEW.OBSOLETE_FILE_NAME` 都是 `String(255)`。

    先前只驗大小與副檔名，超長檔名會走到 INSERT 才撞 asyncpg 的
    `StringDataRightTruncation`；`main.py` 沒有 `DataError` 系列的處理器 ⇒ 落到最後的
    catch-all、冒成 500。兩條上傳路徑（編輯器 / 廢止附件）都經過 `validate_upload`，
    故一處守門涵蓋四個端點。
    """
    too_long = "超" * (MAX_FILE_NAME_LEN - 3) + "x.pdf"  # 副檔名合法，只有長度違規
    assert len(too_long) > MAX_FILE_NAME_LEN
    with pytest.raises(AppError) as ei:
        await validate_upload(None, size_bytes=10, filename=too_long, params=_StubParam())
    assert ei.value.error_code == "DM_FILE_003"
    assert ei.value.status_code == 422


async def test_檔名剛好等於上限時放行():
    """上限不可誤擋界內值——只測「超限」的話，把上限設成 1 也會過。"""
    exact = "名" * (MAX_FILE_NAME_LEN - 4) + ".pdf"
    assert len(exact) == MAX_FILE_NAME_LEN
    await validate_upload(None, size_bytes=10, filename=exact, params=_StubParam())


async def test_檔名長度先於副檔名檢核():
    """兩者都違規時回「檔名過長」——使用者真正要做的是縮短檔名，而非去找格式問題。

    若順序顛倒，他會收到「不支援的檔案格式」，改了副檔名仍然失敗。
    """
    with pytest.raises(AppError) as ei:
        await validate_upload(None, size_bytes=10, filename="長" * 300 + ".exe", params=_StubParam())
    assert ei.value.error_code == "DM_FILE_003", "長度應先於副檔名檢核"
