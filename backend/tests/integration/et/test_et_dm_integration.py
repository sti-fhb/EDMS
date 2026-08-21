"""ET → DM 文件取用之接線測試（AC 10；#185 × #183）。

**範圍界定**：DM 端 `DmDocumentService` 之業務邏輯（分類過濾、廢止仍回最後版、只給
目前版、不寫 `DM_DOC_READ` 等）已由 `tests/integration/dm/test_dm_integration.py`
完整覆蓋，本檔**不重複驗證**。此處只驗 **ET 側的接線與約束**：

1. ET 經 `app/services` 唯一出口取得 Service（模組邊界）
2. 三支方法從 ET 呼叫確實可用（AC 10 之實質）
3. ET 端的使用約束成立——metadata 不含 `file_path`，迫使取檔必走
   `read_file_for_reference`（該方法不掛 DM 角色閘，授權由 ET 自判）

> #183 交付前本檔為 stub 契約測試；PR #189 合併後改為真實整合。
"""

import pytest
from sqlalchemy import select

from app.core.exceptions import AppError
from app.core.utils import utcnow

# 測試建資用：import DM model 以建立 DM 側測資，並使 DM_DOCUMENT 之 FK 目標表
# （DM_CATEGORY）進入 SQLAlchemy metadata。**這是測試 fixture、非應用碼**——
# `app/et/**` 不得 import DM 內部，該約束由下方 test_et_模組未直接_import_dm_內部 把關。
from app.dm.catalog.models import DmCategory  # noqa: F401
from app.dm.document.models import DmDocument, DmDocVersion
from app.et.common.dm_client import TRAINING_CATEGORY, get_dm_document_client

pytestmark = pytest.mark.integration

_client = get_dm_document_client()


async def _published_training_doc(db, doc_id: str, *, name="訓練教材", category=TRAINING_CATEGORY) -> int:
    """建一份已發布之訓練教材（doc + PUBLISHED 版本 + current_version_id 指向該版）。"""
    now = utcnow()
    db.add(
        DmDocument(
            doc_id=doc_id,
            doc_name=name,
            category_code=category,
            func_code=None,
            current_version_id=None,
            status="PUBLISHED",
            created_user="ed",
            created_date=now,
        )
    )
    await db.flush()
    ver = DmDocVersion(
        doc_id=doc_id,
        version_no="v1.0",
        change_summary="摘要",
        file_name="a.pdf",
        file_path=f"/x/{doc_id}.pdf",
        file_size=100,
        file_mime="application/pdf",
        status="PUBLISHED",
        published_date=now,
        created_user="ed",
        created_date=now,
    )
    db.add(ver)
    await db.flush()
    doc = await db.scalar(select(DmDocument).where(DmDocument.doc_id == doc_id))
    doc.current_version_id = ver.version_id
    await db.flush()
    return ver.version_id


class TestBoundary:
    """模組邊界：ET 只經 `app/services` 取得 DM 門面，不碰 DM 內部。"""

    def test_service_自平台唯一出口匯出(self) -> None:
        import app.services as services

        assert hasattr(services, "DmDocumentService")
        assert type(_client).__name__ == "DmDocumentService"

    def test_分類碼與_dm_白名單一致(self) -> None:
        """填錯（如舊值 `TRAINING_MATERIAL`）會被 DM 端以 DM_DOC_010 擋下。"""
        assert TRAINING_CATEGORY == "TRAINING"

    def test_et_模組未直接_import_dm_內部(self) -> None:
        """架構護欄：ET 全模組不得 `from app.dm...`（僅可經 app.services）。"""
        from pathlib import Path

        et_root = Path(__file__).resolve().parents[3] / "app" / "et"
        offenders = [
            f"{py.name}"
            for py in et_root.rglob("*.py")
            if "from app.dm" in py.read_text(encoding="utf-8") or "import app.dm" in py.read_text(encoding="utf-8")
        ]
        assert offenders == [], f"ET 不得直接 import DM 內部：{offenders}"


class TestSrvdm002List:
    async def test_可取得訓練教材清單(self, db) -> None:
        await _published_training_doc(db, "DM-TRAINING-900001", name="成分製備訓練教材")
        items = await _client.list_training_documents(db)
        assert any(i.doc_id == "DM-TRAINING-900001" for i in items)

    async def test_清單列之_doc_id_為字串非數值(self, db) -> None:
        """`docId` 格式 `DM-{分類碼}-{6位流水號}`；ET 端一律以字串儲存於 ET_MATERIAL_DOC。"""
        await _published_training_doc(db, "DM-TRAINING-900002")
        items = await _client.list_training_documents(db)
        item = next(i for i in items if i.doc_id == "DM-TRAINING-900002")
        assert isinstance(item.doc_id, str)
        assert item.doc_id.startswith("DM-")

    async def test_關鍵字過濾(self, db) -> None:
        await _published_training_doc(db, "DM-TRAINING-900003", name="輸血反應處理")
        items = await _client.list_training_documents(db, keyword="輸血反應")
        assert [i.doc_id for i in items] == ["DM-TRAINING-900003"]


class TestSrvdm001Current:
    async def test_取當前發布版_metadata(self, db) -> None:
        vid = await _published_training_doc(db, "DM-TRAINING-900004")
        cur = await _client.get_current_by_doc_id(db, "DM-TRAINING-900004")
        assert cur.current_version_id == vid
        assert cur.category_code == TRAINING_CATEGORY
        assert cur.obsolete is False
        assert cur.status == "PUBLISHED"

    async def test_metadata_不含檔案路徑(self, db) -> None:
        """DM 刻意不在 metadata 暴露 file_path——迫使取檔必走 read_file_for_reference。

        若日後 DM 加回該欄位，本測試會失敗以提醒 ET 端不得改為自行組路徑
        （會繞過 #160 之 storage-root 圍籬）。
        """
        await _published_training_doc(db, "DM-TRAINING-900005")
        cur = await _client.get_current_by_doc_id(db, "DM-TRAINING-900005")
        assert not hasattr(cur, "file_path")

    async def test_查無文件時拋_404_而非回_none(self, db) -> None:
        """語意與 #183 交付前之 stub 不同——呼叫端不可再假設「回 None 代表查無」。"""
        with pytest.raises(AppError) as e:
            await _client.get_current_by_doc_id(db, "DM-TRAINING-999999")
        assert e.value.status_code == 404


class TestReadFile:
    async def test_無_dm_角色亦可取檔(self, db) -> None:
        """本方法刻意不掛 DM 角色閘——ET 學員多半無 DM 角色。授權由 ET 自判。"""
        vid = await _published_training_doc(db, "DM-TRAINING-900006")
        content = await _client.read_file_for_reference(db, doc_id="DM-TRAINING-900006", version_id=vid)
        assert content.path.endswith(".pdf")
        assert content.mime == "application/pdf"
        assert content.name == "a.pdf"

    async def test_非當前版被擋(self, db) -> None:
        vid = await _published_training_doc(db, "DM-TRAINING-900007")
        with pytest.raises(AppError) as e:
            await _client.read_file_for_reference(db, doc_id="DM-TRAINING-900007", version_id=vid + 9999)
        assert e.value.status_code == 403
