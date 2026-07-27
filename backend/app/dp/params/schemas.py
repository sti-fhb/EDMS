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
