"""DM06 閱讀統計 KPI schema（US13 / UCDM13）。"""

from pydantic import BaseModel

from app.core.pagination import PageMetaResponse


class KpiAudienceGroup(BaseModel):
    """單一可見對象組之完成度（#567 A）。

    `label` 為組名：「全體」／職位名／「單位．職位」。

    ⚠️ **逐組 `should_see` 之加總會 ≥ 文件的 `should_see`**：一位閱覽者可同時符合同一份文件
    的多組（身兼兩職），各組分母都含他、文件總計去重（裁示 2026-10-07）。呈現端須標註，
    否則讀者會判定成算錯。
    """

    label: str
    should_see: int
    seen: int
    unseen: int
    rate: float | None  # 0~1；該組應看=0 → None（不是 0%）


class KpiDocItem(BaseModel):
    """逐文件閱讀 KPI 列（FR-002/003）。

    rate 為 None 代表應看=0（無對應閱覽者）：前端顯示「—（無對應閱覽者）」、不計入整體平均。
    """

    doc_id: str
    doc_name: str
    category_code: str
    category_name: str | None
    current_version_no: str | None
    should_see: int
    seen: int
    unseen: int
    rate: float | None  # 0~1；應看=0 → None
    groups: list[KpiAudienceGroup] = []  # 逐可見對象組明細（依 label 排序）


class KpiTrainingDoc(BaseModel):
    """訓練教材清單列（#567 B）——**刻意不含任何閱讀統計欄位**。

    TRAINING 之閱讀由教育訓練模組追蹤：ET 代學員取檔不寫 `DM_DOC_READ`
    （`app/et/common/dm_client.py` D-2），於此計算閱讀率會固定低報。給數字比不給更糟，
    因為它看起來有權威性。
    """

    doc_id: str
    doc_name: str
    category_name: str | None
    current_version_no: str | None


class KpiSummary(BaseModel):
    """頂部統計卡（AC3a：整體平均排除應看=0 文件）。"""

    total_docs: int  # 統計母體之文件數（不含 TRAINING）
    rated_docs: int  # 其中應看>0、可計算閱讀率者——`below_50_count` 的分母
    overall_rate: float | None  # 全部應看>0 文件之平均閱讀率；無可計文件 → None
    below_50_count: int  # 閱讀率 < 50% 之文件數（僅計應看>0 者）


class KpiListResponse(BaseModel):
    """KPI 儀表板回應：逐文件清單（分頁）+ 統計卡摘要 + 訓練教材清單。"""

    data: list[KpiDocItem]
    meta: PageMetaResponse
    summary: KpiSummary
    training_docs: list[KpiTrainingDoc] = []  # 不分頁、有上限（見 service._TRAINING_LIST_LIMIT）
    training_total: int = 0  # 符合條件之訓練教材總數（可能 > len(training_docs)）
