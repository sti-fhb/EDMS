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


class MaterialUpdateReq(BaseModel):
    """更新教材名稱與說明文字（帶教材自身之 `version` 檢核樂觀鎖）。

    **不含影片與文件引用**——那兩者各有自己的端點（上傳 / 逐筆增刪），不走全量覆寫：
    影片是檔案上傳、文件引用需逐筆確認廢止狀態，硬塞進同一個 PUT 會讓「改個名稱」
    也得把整包媒材重送一次。
    """

    material_name: str = Field(min_length=1, max_length=MATERIAL_NAME_MAX_LEN)
    description_html: str | None = Field(default=None, max_length=DESCRIPTION_HTML_MAX_LEN)
    version: int = Field(ge=0)

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
