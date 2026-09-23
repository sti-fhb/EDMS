from typing import Annotated, Literal, Optional

from pydantic import BaseModel, StringConstraints

# 代碼：英數 + 底線；名稱：非空 ≤100；值 / 說明：≤500（值/說明可空，名稱必填）
_KeyStr = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_]+$")
]
_NameStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
_ValueStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
_DescStr = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class ParamItem(BaseModel):
    """清單型參數的單一明細項（SRVDP001 get_param_list 回傳元素）。"""

    key: str
    name: str
    value: str | None
    is_enabled: bool
    sort_order: int | None

    model_config = {"from_attributes": True}


class ParamDetailResponse(BaseModel):
    """參數明細回應（維護頁用）。"""

    model_config = {"from_attributes": True}

    param_key: str
    param_name: str
    param_value: Optional[str]
    description: Optional[str]
    sort_order: Optional[int]
    is_enabled: bool


class ParamMasterResponse(BaseModel):
    """參數主檔 + 明細回應（維護頁用）。scope 依 PARAM_ID 前綴衍生。"""

    param_id: str
    param_name: str
    param_type: str
    detail_lock: bool
    description: Optional[str]
    scope: Literal["platform", "ET", "DM"]
    details: list[ParamDetailResponse]


class ControlledItemResponse(BaseModel):
    """模組受控清單之單一項（模組自持表，非 `DP_PARAM`）。"""

    code: str
    name: str
    is_builtin: bool
    is_enabled: bool


class ControlledSectionResponse(BaseModel):
    """受控清單之一個維護分區（維護頁用）。

    一個 `kind` 通常對應一個分區；有子分組者（DM 標籤依 `DM_TAG_GROUP`）每組各一分區，
    此時 `group_code` / `group_name` 非空。`requires_code` 決定新增表單要不要代碼欄。
    """

    module: str
    kind: str
    name: str
    requires_code: bool
    group_code: Optional[str] = None
    group_name: Optional[str] = None
    items: list[ControlledItemResponse]


# 受控項名稱上限取各模組**最窄**之欄位（`DM_CATEGORY.CATEGORY_NAME` / `DM_TAG.TAG_NAME` /
# `ET_TAG.TAG_NAME` 皆為 VARCHAR(50)）。不沿用 `_NameStr`（100）——超出欄位長度會在 INSERT
# 時由 DB 拋 `value too long`，落成未攔截的 500 而非乾淨的 422。
# 取捨：`DM_FUNC.FUNC_NAME` 實為 VARCHAR(100)，於此一併收斂至 50（前端 Zod 同值）。
_ControlledNameStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
# 代碼上限取最寬者（`DM_TAG_GROUP.TAG_GROUP_CODE` VARCHAR(20)；TAG 之 code 為所屬標籤組）。
# 更嚴的逐類長度與字元集檢核歸模組（DM `_ensure_code` 擋 10 碼英數）。
_ControlledCodeStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]


class ControlledCreate(BaseModel):
    """新增受控項請求。

    `code` 之語意依分區而定（見 `ControlledSectionResponse.requires_code`）：需代碼者由使用者輸入、
    有子分組者由前端帶入所屬組代碼、兩者皆非則模組忽略。**格式檢核歸模組**（DP 不重複實作），
    此處僅設長度上限以免超長輸入直抵 DB 造成 500。
    """

    code: Optional[_ControlledCodeStr] = None
    name: _ControlledNameStr


class ControlledRename(BaseModel):
    """受控項改名請求（代碼建立後鎖定，不可改）。"""

    name: _ControlledNameStr


class ControlledToggle(BaseModel):
    """受控項啟停請求（不刪除、淘汰改停用）。"""

    enabled: bool


class ControlledToggleResponse(BaseModel):
    """啟停結果；僅 DM 可見對象停用（soft-retire）帶受影響數，其餘為 null。

    受影響數為**下限**——在途草稿之版本層標籤快照未計入（#388），畫面須標示「至少」。
    """

    affected_docs: Optional[int] = None
    affected_viewers: Optional[int] = None


class ParamDetailUpdate(BaseModel):
    """更新明細請求：改名（param_name）/ 改值（param_value）/ 說明 / 啟停。

    各欄皆選填，至少提供一項（服務層以 exclude_unset 判定，全空回 COMMON_001）。
    param_key 不可改（碼值鎖定 / 淘汰改停用）。
    """

    param_name: Optional[_NameStr] = None
    param_value: Optional[_ValueStr] = None
    description: Optional[_DescStr] = None
    is_enabled: Optional[bool] = None


class ParamDetailCreate(BaseModel):
    """新增 LIST 型清單項請求。param_name 必填；param_value（值）與 description 選填。"""

    param_key: _KeyStr
    param_name: _NameStr
    param_value: Optional[_ValueStr] = None
    description: Optional[_DescStr] = None
    sort_order: Optional[int] = None
