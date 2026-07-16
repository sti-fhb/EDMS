"""稽核寫入服務（SRVDP003）。

各模組資安稽核事件之統一寫入口（DP_AUDIT_LOG，append-only）。
服務內計算鏈式 ROW_HASH（research §6）、序列化前後值為 JSON、遮罩機密欄位；
呼叫方於 CUD 完成時在**同一交易內**呼叫 log_action，只 flush 不 commit。
"""

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import utcnow
from app.dp.audit.repository import AuditLogRepository

# 機密 key 遮罩清單（子字串、不分大小寫）：對齊 sti-backend-logging 禁寫敏感資料。
_SENSITIVE_KEY_PARTS = ("password", "passwd", "pwd", "secret", "token", "api_key", "apikey", "authorization")
_MASK = "***"


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _mask_sensitive(data: Any) -> Any:
    """遞迴遮罩 dict / list / tuple 中 key 命中機密清單的值（不改動非機密內容）。"""
    if isinstance(data, dict):
        return {k: (_MASK if _is_sensitive(k) else _mask_sensitive(v)) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [_mask_sensitive(v) for v in data]
    return data


def _json_default(value: Any) -> str:
    """json.dumps 遇非原生型別的 fallback：僅對已知安全型別轉字串。

    稽核是全平台唯一寫入口且 append-only、寫入即永久不可刪。禁止用 str(obj) 泛化
    fallback——否則「key 不在機密清單、但 __repr__ 含機密」的物件會被序列化落庫造成洩漏。
    僅白名單 datetime / date / Decimal / UUID / Enum；未知型別一律回固定佔位字串，
    既不拋 TypeError 連累呼叫方交易，也不外洩內容。
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, Enum):
        return str(value.value)
    return "<non-serializable>"


def _to_json(data: dict | None) -> str | None:
    """前後值 dict → JSON 字串（先遮罩、sort_keys 決定性）；None 回 None。

    非原生 JSON 型別走 _json_default 白名單序列化，避免序列化失敗在同交易內
    連累呼叫方 CUD rollback，同時不讓未知物件的 repr 洩漏機密。
    """
    if data is None:
        return None
    return json.dumps(_mask_sensitive(data), ensure_ascii=False, sort_keys=True, default=_json_default)


def _compute_row_hash(
    *,
    prev_hash: str | None,
    module: str,
    func_name: str,
    action_type: str,
    result: str,
    operator_id: str,
    target_id: str | None,
    description: str | None,
    source_ip: str | None,
    before_json: str | None,
    after_json: str | None,
    created_date: datetime,
) -> str:
    """本列內容 + 前列 ROW_HASH 之 SHA-256 鏈式雜湊（research §6）。

    canonical 以 sort_keys 確保決定性；genesis（prev_hash=None）以空字串接鏈。
    """
    payload = json.dumps(
        {
            "module": module,
            "func_name": func_name,
            "action_type": action_type,
            "result": result,
            "operator_id": operator_id,
            "target_id": target_id,
            "description": description,
            "source_ip": source_ip,
            "before": before_json,
            "after": after_json,
            "created_date": created_date.isoformat(),
            "prev": prev_hash or "",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AuditLogService:
    """SRVDP003 稽核寫入服務（跨模組經 app.services 呼叫）。"""

    def __init__(self, repository: AuditLogRepository | None = None) -> None:
        self._repo = repository or AuditLogRepository()

    async def log_action(
        self,
        db: AsyncSession,
        *,
        module: str,
        func_name: str,
        action_type: str,
        result: str,
        operator_id: str,
        target_id: str | None = None,
        description: str | None = None,
        before_value: dict | None = None,
        after_value: dict | None = None,
        source_ip: str | None = None,
    ) -> None:
        """寫入一筆稽核（append-only、鏈式 ROW_HASH）。

        於呼叫方交易內執行（同一 db session），只 flush 不 commit。

        Args:
            db: 呼叫方的 AsyncSession（與其 CUD 同交易）。
            module: 事件歸屬 DP / ET / DM。
            func_name: 功能 / 資源名稱（如 DP-USERS）。
            action_type: LOGIN / LOGOUT / CREATE / UPDATE / DELETE。
            result: SUCCESS / FAIL。
            operator_id: 操作者 USER_ID（系統作業用 SYSTEM）。
            target_id: 異動對象識別（選填）。
            description: 事件描述（選填）。
            before_value / after_value: 異動前 / 後值 dict；服務內遮罩機密並序列化為 JSON。
            source_ip: 來源 IP（選填）。
        """
        # 序列化鏈接臨界區，避免並行 append 讀到同一 prev hash
        await self._repo.acquire_chain_lock(db)
        prev_hash = await self._repo.get_last_row_hash(db)

        before_json = _to_json(before_value)
        after_json = _to_json(after_value)
        created_date = utcnow()
        row_hash = _compute_row_hash(
            prev_hash=prev_hash,
            module=module,
            func_name=func_name,
            action_type=action_type,
            result=result,
            operator_id=operator_id,
            target_id=target_id,
            description=description,
            source_ip=source_ip,
            before_json=before_json,
            after_json=after_json,
            created_date=created_date,
        )

        await self._repo.insert(
            db,
            {
                "module": module,
                "func_name": func_name,
                "action_type": action_type,
                "target_id": target_id,
                "result": result,
                "description": description,
                "source_ip": source_ip,
                "before_value": before_json,
                "after_value": after_json,
                "row_hash": row_hash,
                "created_user": operator_id,
                "created_date": created_date,
            },
        )
