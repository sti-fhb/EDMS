"""ET 教材內容（US3 / #203）schema。

教材三類媒材：影片（`ET_MATERIAL_VIDEO`）、DM 文件引用（`ET_MATERIAL_DOC`）、
說明文字（`ET_MATERIAL.DESCRIPTION_HTML`）。三者皆選填但**至少擇一**方可存檔
（`rules.ensure_material_has_media`）。
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# `MATERIAL_NAME` 為 VARCHAR(100)。
MATERIAL_NAME_MAX_LEN = 100
# `DOC_ID` 為 VARCHAR(20)，格式 `DM-{分類碼}-{6位流水號}`。
DOC_ID_MAX_LEN = 20
# 說明文字之長度上限。`DESCRIPTION_HTML` 於 DB 為 TEXT（無長度限制），但無界限的
# 請求本體會讓消毒與傳輸成為放大攻擊面——WYSIWYG 的說明文字實務上遠低於此。
DESCRIPTION_HTML_MAX_LEN = 50_000
# DM 文件下拉之關鍵字長度上限（避免超長字串進到 LIKE 查詢）。
KEYWORD_MAX_LEN = 100
# 單一教材之引用文件 / 影片數上限——全量覆寫送完整陣列，無界限會成為放大面
# （比照課程標籤之 `MAX_TAG_IDS`）。
MAX_DOC_IDS = 100
MAX_VIDEO_IDS = 100


class MaterialUpdateReq(BaseModel):
    """更新教材：名稱、說明文字，與**完整的媒材集合**（帶 `version` 檢核樂觀鎖）。

    ## 為何改成全量覆寫（2026-08-26 依實測回饋）

    原本文件引用是逐筆即時生效的端點（加一筆就打一次 API）。實測發現兩個問題：

    1. **「取消」不再是取消**——使用者刪掉一份文件、按取消，那次刪除早就送出去了
    2. **「至少擇一媒材」被繞過**——刪到一份不剩時沒有任何檢核，教材直接變成空的，
       而那正是 `ET_MATERIAL_002` 要防的狀態

    改為送最終狀態後，兩者一併解決：檢核對象是**存檔後的樣子**，且未按儲存就什麼
    都沒發生。比照課程標籤（`CourseUpdateReq.tag_ids`）之全量覆寫契約。

    **影片上傳仍是獨立端點**——檔案傳輸無法「暫存」在請求裡（單檔上限 500 MB）。
    此處的 `video_ids` 是**要保留的影片**，未列出者視為刪除。
    """

    material_name: str = Field(min_length=1, max_length=MATERIAL_NAME_MAX_LEN)
    description_html: str | None = Field(default=None, max_length=DESCRIPTION_HTML_MAX_LEN)
    #: 本教材最終要引用的 DM 文件編號（依序）。未列出之既有引用將被軟刪除。
    doc_ids: list[str] = Field(default_factory=list, max_length=MAX_DOC_IDS)
    #: 本教材最終要保留的影片 ID。未列出之既有影片將被軟刪除。
    video_ids: list[int] = Field(default_factory=list, max_length=MAX_VIDEO_IDS)
    version: int = Field(ge=0)

    @field_validator("doc_ids")
    @classmethod
    def _docs_unique(cls, v: list[str]) -> list[str]:
        """同一教材不可重複引用同一文件——在此先擋，避免送到 DB 才撞唯一索引（500）。"""
        cleaned = [d.strip() for d in v]
        if any(not d for d in cleaned):
            raise ValueError("文件編號不得為空白")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("同一教材不可重複引用同一份文件")
        return cleaned

    @field_validator("material_name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("教材名稱不得為空白")
        return stripped


class MaterialDocCreateReq(BaseModel):
    """新增一筆 DM 文件引用。

    只帶 `doc_id`——文件名稱、版號、廢止狀態一律即時經 SRVDM001 取得，**不落地快取**，
    否則 DM 發布新版後 ET 這邊會顯示舊資料（data-model §ET_MATERIAL_DOC）。
    """

    doc_id: str = Field(min_length=1, max_length=DOC_ID_MAX_LEN)

    @field_validator("doc_id")
    @classmethod
    def _doc_id_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("文件編號不得為空白")
        return stripped


class VideoRow(BaseModel):
    """教材影片列（回應）。"""

    model_config = {"from_attributes": True}

    video_id: int
    file_name: str
    duration_sec: int
    file_size_bytes: int
    sort_order: int


class DocRow(BaseModel):
    """教材引用之 DM 文件列（回應）。

    `doc_name` / `version_no` / `obsolete` 皆為**即時查得**（SRVDM001），非 ET 落地值。
    `obsolete=True` 時前端顯示「此文件已廢止」警告（ET-MSG-ET02-002）並僅可逐筆刪除。

    `unavailable` 表示該文件目前取不到（於 DM 被刪、或無發布版）——與「已廢止」不同：
    廢止文件學員仍讀得到廢止前最後版，取不到的則是真的沒東西。兩者都要讓教師看見，
    但混為一談會讓教師誤以為只要不理會就好。
    """

    mat_doc_id: int
    doc_id: str
    doc_name: str | None
    version_no: str | None
    obsolete: bool
    unavailable: bool
    sort_order: int


class MaterialDetail(BaseModel):
    """教材詳細（回應）——三類媒材一次帶齊。"""

    material_id: int
    material_name: str
    description_html: str | None
    version: int
    videos: list[VideoRow]
    docs: list[DocRow]


class DmDocOption(BaseModel):
    """DM 訓練教材下拉項（SRVDM002）。

    清單**不含已廢止文件**（DM 端 `_LIST_STATUSES` 僅納入 `PUBLISHED` 與
    `PENDING_OBSOLETE`）——「廢止待簽核」期間文件仍屬有效，照常可選。
    """

    doc_id: str
    doc_name: str
    version_no: str
    published_date: datetime | None
