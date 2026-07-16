from pydantic import BaseModel


class SendResult(BaseModel):
    """SRVDP002 send_email 回傳：排入 outbox 的收件人數與略過原因。"""

    queued_count: int
    skipped_reason: str | None = None
