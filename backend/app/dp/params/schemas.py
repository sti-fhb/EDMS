from pydantic import BaseModel


class ParamItem(BaseModel):
    """清單型參數的單一明細項（SRVDP001 get_param_list 回傳元素）。"""

    key: str
    value: str | None
    is_enabled: bool
    sort_order: int | None

    model_config = {"from_attributes": True}
