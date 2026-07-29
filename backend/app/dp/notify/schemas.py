from typing import Annotated, Literal, Optional

from pydantic import BaseModel, StringConstraints

_SubjectStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
_BodyStr = Annotated[str, StringConstraints(min_length=1, max_length=10000)]
Channel = Literal["EMAIL", "MSG", "BOTH"]


class SendResult(BaseModel):
    """SRVDP002 send_email 回傳：排入 outbox 的收件人數與略過原因。"""

    queued_count: int
    skipped_reason: str | None = None


class TemplateResponse(BaseModel):
    """通知範本回應（US9 維護頁用）。"""

    model_config = {"from_attributes": True}

    module: str
    template_code: str
    template_name: str
    subject: str
    body: str
    variables: Optional[str]
    channel: str
    is_enabled: bool
    is_system: bool
    version: int


class TemplateUpdate(BaseModel):
    """更新通知範本請求（US9）：主旨 / 內文 / 管道 / 啟停 + 樂觀鎖版本。

    `version` 為必填（樂觀鎖：以本值比對 DB，不符回衝突 409）。`TEMPLATE_CODE` 固定不可改、
    無新增 / 刪除。系統信（`IS_SYSTEM`）之 `is_enabled=false` 由服務層擋（DP_MAIL_003）。
    """

    subject: _SubjectStr
    body: _BodyStr
    channel: Channel
    is_enabled: bool
    version: int
