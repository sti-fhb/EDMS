"""DM 文件取用 Client（T029）——**目前為 stub，待 #183 交付後抽換為真呼叫**。

ET 教材引用 DM「訓練教材」分類之文件，需 DM 提供兩支內部服務（見
docs/specs/et/contracts/srv-et-dm-document-{list,content}.md，已依 DM 定稿契約對齊）：

- **SRVDM002**：取 `category=TRAINING` 之有效文件清單（ET02 教材下拉）
- **SRVDM001**：依 `docId` 取當前發布版 metadata 與廢止狀態（ET02 發布檢核 / ET05 學員閱讀）

## 為何是 stub

DM 端 `T057` / `T058` **尚未實作**（#183，其前置為 #178 DM US6 簽核處理），且 DM Service
尚未自 `app/services/__init__.py` 匯出——目前該出口僅有 DP 三個 Service。ET 先以本模組
定義呼叫介面與回傳型別，使上層（ET Issue #3 / #5）得以照介面開發；#183 交付後只需替換
`_StubDmDocumentClient` 為真實實作，介面不變。

## 抽換時的兩項注意（已於契約標註）

1. **不得打 DM 的 HTTP 端點**——DM 存取閘（`app/dm/deps.py`）要求呼叫者具備任一 DM 角色，
   ET 學員多半沒有，會被 403 `DM_AUTH_001` 擋下。須經 `app/services` 之 in-process Service。
2. **不得直接讀回應之 `file_path`**——違反模組邊界，且 #160 正強化 storage-root 路徑穿越
   圍籬。檔案本體須經 DM 提供之檔案存取能力取得。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

# ET 教材固定引用之 DM 分類碼（非 `TRAINING_MATERIAL`——2026-08-19 依 DM 定稿契約更正）
TRAINING_CATEGORY = "TRAINING"


@dataclass(frozen=True)
class DmDocumentListItem:
    """SRVDM002 回應之清單列。

    `doc_id` 為 **VARCHAR(20) 字串**（格式 `DM-{分類碼}-{6位流水號}`），非數值型。
    DM 端本服務不回傳 `file_type` / `file_size_bytes`。
    """

    doc_id: str
    doc_name: str
    version_no: str
    published_date: datetime | None


@dataclass(frozen=True)
class DmDocumentCurrent:
    """SRVDM001 回應——文件當前發布版之 metadata 與廢止狀態。

    `status` 為 `PUBLISHED`（含廢止待簽核期間，仍對外有效）或 `OBSOLETE`；
    `obsolete=True` 時仍回傳廢止前最後發布版本之位置，ET 據此於學員端顯示
    「此文件已廢止」標籤、於教師端阻擋課程發布。
    """

    doc_id: str
    doc_name: str
    category_code: str
    current_version_id: int
    version_no: str
    file_name: str
    file_path: str
    file_mime: str
    published_date: datetime | None
    status: str
    obsolete: bool


class DmDocumentClient(Protocol):
    """ET → DM 文件取用介面（#183 交付後由真實實作替換）。"""

    async def list_training_documents(
        self, *, keyword: str | None = None, func_code: str | None = None
    ) -> list[DmDocumentListItem]:
        """SRVDM002：取訓練教材分類之有效文件清單。

        僅含**有當前發布版本**者；`PENDING_OBSOLETE`（廢止待簽核）仍列入、
        `OBSOLETE`（已廢止）不列。依發布時間 DESC。
        """
        ...

    async def get_current_version(self, doc_id: str) -> DmDocumentCurrent | None:
        """SRVDM001：依 `doc_id` 取當前發布版；查無文件回 None。

        文件存在但尚無已發布版本時，DM 端回 `NO_PUBLISHED_VERSION`——由實作決定
        映射為 None 或拋出，介面契約於 #183 抽換時一併定案。
        """
        ...


class _StubDmDocumentClient:
    """暫用 stub：回固定測資，使上層開發與測試不被 #183 阻塞。

    ⚠️ **不得用於正式環境**——`get_dm_document_client()` 於 #183 交付後改回真實實作。
    """

    async def list_training_documents(
        self, *, keyword: str | None = None, func_code: str | None = None
    ) -> list[DmDocumentListItem]:
        return []

    async def get_current_version(self, doc_id: str) -> DmDocumentCurrent | None:
        return None


def get_dm_document_client() -> DmDocumentClient:
    """取得 DM 文件 Client。

    TODO(#183): DM US12 交付且 DM Service 自 `app/services/__init__.py` 匯出後，
    改回傳真實實作（經 in-process Service，不打 HTTP 端點）。
    """
    return _StubDmDocumentClient()
