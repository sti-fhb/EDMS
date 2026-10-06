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


class TestUploadLimitsSharesOneSource:
    """#455：前端的 `accept` 與上傳驗證**必須同源**。

    改版前上傳畫面的文案與 `accept` 是寫死的，於是 IT 依既定途徑改了 `DP_PARAM` 之後，
    DP07 顯示新值、上傳畫面仍說舊話，而 `accept` 還會把新允許的格式擋在選檔器外——
    **使用者看到的是「這個格式不能選」，不會有任何錯誤訊息告訴他為什麼**。

    本組釘住「`resolve_upload_limits` 回的那組值，就是 `validate_upload` 執行的那組值」。
    ⚠️ 少了它，日後有人為端點另寫一支解析也不會有東西變紅，而分岔的表徵是
    **選得到卻傳不上去**——正是本 issue 要修的病。
    """

    async def test_回出的上限與驗證實際採用的一致(self, db) -> None:
        from app.dm.document.file_store import resolve_upload_limits

        max_mb, _ = await resolve_upload_limits(db)

        # 剛好等於上限 → 必須通過；多 1 byte → 必須被擋。兩條成對才釘得住邊界。
        await validate_upload(db, size_bytes=max_mb * 1024 * 1024, filename="doc.pdf")
        with pytest.raises(AppError) as e:
            await validate_upload(db, size_bytes=max_mb * 1024 * 1024 + 1, filename="doc.pdf")
        assert e.value.error_code == "DM_FILE_001"

    async def test_回出的每個副檔名驗證都接受(self, db) -> None:
        from app.dm.document.file_store import resolve_upload_limits

        _, allowed = await resolve_upload_limits(db)

        assert allowed, "錨點失敗：允許清單是空的，下面的迴圈等於沒驗"
        for ext in allowed:
            await validate_upload(db, size_bytes=1024, filename=f"x.{ext}")

    async def test_未回出的副檔名驗證一律拒絕(self, db) -> None:
        """與上一條成對：少了它，把 `resolve_upload_limits` 改成回「全部副檔名」
        也會通過上一條。"""
        from app.dm.document.file_store import resolve_upload_limits

        _, allowed = await resolve_upload_limits(db)

        for ext in ("exe", "sh", "bat"):
            assert ext not in allowed, f"{ext} 不該在允許清單裡"
            with pytest.raises(AppError) as e:
                await validate_upload(db, size_bytes=1024, filename=f"x.{ext}")
            assert e.value.error_code == "DM_FILE_002"

    async def test_參數清空時退回安全預設而非全部放行(self, db) -> None:
        """🔴 fail-closed（T066 L2）：管理者誤清 `DM_FILE_TYPES` 不該等於開放任意副檔名。

        ⚠️ 本條同時守住**前端**——`accept` 現在也走這支，fallback 若改成「全部放行」，
        選檔器會變成不限格式。
        """
        from sqlalchemy import text

        from app.dm.document.file_store import resolve_upload_limits

        # ⚠️ `DP_PARAM_D` 的主鍵是 (PARAM_ID, PARAM_KEY)，而 `PARAM_ID` 本身就是參數
        # 代碼——沒有 `PARAM_CODE` 這個欄位。
        await db.execute(
            text(
                'UPDATE "DP_PARAM_D" SET "PARAM_VALUE" = \'\' '
                "WHERE \"PARAM_ID\" = 'DM_FILE_TYPES' AND \"PARAM_KEY\" = 'VALUE'"
            )
        )
        await db.flush()

        _, allowed = await resolve_upload_limits(db)

        assert "pdf" in allowed, "清空後應退回安全預設白名單"
        assert "exe" not in allowed, "清空後變成全部放行了（fail-open）"
