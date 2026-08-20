"""跨模組教材引用門面（US12 / UCDM12，ET → DM in-process）。

ET 依 `sti-backend-boundaries`（API-First 隔離）只經 `app/services/__init__.py` 匯出之本 Service 呼叫，
不打 DM 的 HTTP 端點（HTTP 掛 `app/dm/deps.py` 存取閘，要求呼叫者具 DM 角色，ET 師生未必具備會被擋）。

- **SRVDM001** `get_current_by_doc_id`：依 DOC_ID 取當前發布版 metadata；廢止仍回廢止前最後版 + `obsolete`。
- **SRVDM002** `list_training_documents`：取「訓練教材」分類、有當前發布版且在架之文件清單。
- **取檔** `read_file_for_reference`：供 ET 學員取教材檔——**不掛 DM 角色閘**（授權由 ET 自判）；
  **D-1 只給目前發布版**、**D-2 不寫 `DM_DOC_READ`**（交付前自檢裁示，見契約決策紀錄）。

契約權威：`docs/specs/dm/contracts/document-service.md`。廢止後「通知 ET 教師」採裁示 A（ET 端依 `obsolete`
旗標自偵測、DM 不主動推播），故本模組不含通知邏輯。
"""

from dataclasses import dataclass
from datetime import datetime

from app.core.exceptions import AppError
from app.dm.integration.repository import IntegrationRepository

_OBSOLETE = "OBSOLETE"
_PUBLISHED = "PUBLISHED"

_NOT_FOUND = AppError(status_code=404, detail="查無此文件或無權存取", error_code="DM_DOC_001")


@dataclass(frozen=True)
class DmCurrentVersion:
    """SRVDM001 回傳：文件當前發布版 metadata（廢止時仍為廢止前最後版）。"""

    doc_id: str
    doc_name: str
    category_code: str
    current_version_id: int
    version_no: str
    file_name: str | None
    file_mime: str | None
    published_date: datetime | None
    status: str  # PUBLISHED（含廢止待簽核期間）/ OBSOLETE
    obsolete: bool


@dataclass(frozen=True)
class DmDocItem:
    """SRVDM002 清單項目。"""

    doc_id: str
    doc_name: str
    version_no: str
    published_date: datetime | None


@dataclass(frozen=True)
class DmFileContent:
    """取檔回傳：落地檔資訊（ET 以 FileResponse 回學員，不自行解析路徑另作他用）。"""

    path: str
    mime: str
    name: str


class DmDocumentService:
    """跨模組（ET→DM）文件取用門面。ET 只碰本類別，不碰 DM 內部 repository / model。"""

    def __init__(self, repository: IntegrationRepository | None = None) -> None:
        self._repo = repository or IntegrationRepository()

    async def get_current_by_doc_id(self, db, doc_id: str) -> DmCurrentVersion:
        """SRVDM001：依 DOC_ID 取當前發布版；廢止仍回最後版 + obsolete=true；無發布版 → DM_DOC_013。"""
        doc = await self._repo.get_document(db, doc_id)
        if doc is None:
            raise _NOT_FOUND
        if doc.current_version_id is None:
            raise AppError(status_code=409, detail="文件尚無已發布版本", error_code="DM_DOC_013")
        ver = await self._repo.get_version(db, doc.current_version_id)
        if ver is None:
            raise _NOT_FOUND
        obsolete = doc.status == _OBSOLETE
        return DmCurrentVersion(
            doc_id=doc.doc_id,
            doc_name=doc.doc_name,
            category_code=doc.category_code,
            current_version_id=ver.version_id,
            version_no=ver.version_no,
            file_name=ver.file_name,
            file_mime=ver.file_mime,
            published_date=ver.published_date,
            status=_OBSOLETE if obsolete else _PUBLISHED,
            obsolete=obsolete,
        )

    async def list_training_documents(
        self, db, *, category: str = "TRAINING", keyword: str = "", func_code: str | None = None
    ) -> list[DmDocItem]:
        """SRVDM002：取分類（預設 TRAINING）有當前發布版且在架之文件；分類不存在 → DM_DOC_010。"""
        category = (category or "TRAINING").strip()
        keyword = (keyword or "").strip()
        if not await self._repo.category_exists(db, category):
            raise AppError(status_code=422, detail="受控選項無效或已停用", error_code="DM_DOC_010")
        rows = await self._repo.list_training(db, category=category, keyword=keyword, func_code=func_code)
        return [
            DmDocItem(doc_id=r.doc_id, doc_name=r.doc_name, version_no=r.version_no, published_date=r.published_date)
            for r in rows
        ]

    async def read_file_for_reference(self, db, *, doc_id: str, version_id: int) -> DmFileContent:
        """供 ET 學員取教材檔。**不掛 DM 角色閘**（授權由 ET 自判）；D-1 只給目前版、D-2 不寫 DM_DOC_READ。

        OBSOLETE 文件仍可取（`CURRENT_VERSION_ID` 指廢止前最後發布版，FR-003 學員仍可閱讀）。
        """
        doc = await self._repo.get_document(db, doc_id)
        if doc is None:
            raise _NOT_FOUND
        if version_id != doc.current_version_id:  # D-1：僅目前發布版
            raise AppError(status_code=403, detail="舊版本不可下載，請聯絡管理者", error_code="DM_DOC_002")
        ver = await self._repo.get_version(db, version_id)
        if ver is None or not ver.file_path:
            raise _NOT_FOUND
        # D-2：不寫 DM_DOC_READ——ET 代學員取檔不計入 DM 閱讀統計（US13），ET 端自行統計學習進度。
        return DmFileContent(
            path=ver.file_path,
            mime=ver.file_mime or "application/octet-stream",
            name=ver.file_name or "file",
        )
