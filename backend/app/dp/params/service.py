"""參數服務。

- ParamService（SRVDP001）：跨模組唯讀查詢，不快取——儲存即生效（research §7）。
- ParamAdminService（US5）：DP 後台維護（寫入），前綴過濾 + DETAIL_LOCK + 值域驗證 + 稽核；
  DP 內部使用，不經 app.services 出口暴露（唯讀契約不受污染）。
"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.module_admin import module_admin_gate
from app.core.operator import OperatorInfo
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.dp.audit.service import AuditLogService
from app.dp.params.models import DpParamMaster
from app.dp.params.param_rules import validate_group_invariants, validate_param_value
from app.dp.params.repository import ParamRepository
from app.dp.params.schemas import (
    ParamDetailCreate,
    ParamDetailResponse,
    ParamDetailUpdate,
    ParamItem,
    ParamMasterResponse,
)


class ParamService:
    """SRVDP001 參數唯讀服務（跨模組經 app.services 呼叫）。"""

    def __init__(self, repository: ParamRepository | None = None) -> None:
        self._repo = repository or ParamRepository()

    async def get_param_value(self, db: AsyncSession, param_id: str, key: str = "VALUE") -> str | None:
        """取單值參數；PARAM_ID / PARAM_KEY 不存在或明細停用皆回 None。

        Args:
            db: 呼叫方 AsyncSession。
            param_id: 參數主檔代碼（如 JWT）。
            key: 明細碼；單值參數固定 VALUE，群組型傳實際碼（如 ACCESS_TTL_MIN）。

        Returns:
            PARAM_VALUE 字串；查無或停用回 None（利呼叫方以預設值 fallback）。
        """
        detail = await self._repo.get_detail(db, param_id, key)
        if detail is None or not detail.is_enabled:
            return None
        return detail.param_value

    async def get_int_param(self, db: AsyncSession, param_id: str, key: str, default: int) -> int:
        """取整數參數；查無 / 停用 / 非整數字串一律回 default（利呼叫方安全 fallback）。"""
        raw = await self.get_param_value(db, param_id, key)
        try:
            return int(raw) if raw is not None else default
        except ValueError:
            return default

    async def get_param_list(self, db: AsyncSession, param_id: str, enabled_only: bool = True) -> list[ParamItem]:
        """取清單型參數定義，依 SORT_ORDER 排序。

        Args:
            db: 呼叫方 AsyncSession。
            param_id: 參數主檔代碼（如 ACTION_TYPE）。
            enabled_only: True（預設）僅回啟用項；False 連停用項一併回傳。

        Returns:
            ParamItem 清單；PARAM_ID 不存在回空清單（非例外）。
        """
        details = await self._repo.list_details(db, param_id, enabled_only)
        return [
            ParamItem(key=d.param_key, value=d.param_value, is_enabled=d.is_enabled, sort_order=d.sort_order)
            for d in details
        ]


_FUNC_NAME = "DP-PARAMS"
_NOT_FOUND_MSG = "查無此參數"
_FORBIDDEN_MSG = "無權限維護此模組之參數"
_LOCKED_MSG = "此代碼已鎖定，不可修改代碼值"
_DUP_MSG = "清單項代碼已存在"
_TYPE_MSG = "此參數不支援清單項維護"
_NO_FIELD_MSG = "未提供任何更新欄位"


def _scope(param_id: str) -> str:
    """依 PARAM_ID 前綴判定歸屬：ET_ / DM_＝模組級；其餘＝平台級（platform，共用）。"""
    if param_id.startswith("ET_"):
        return "ET"
    if param_id.startswith("DM_"):
        return "DM"
    return "platform"


class ParamAdminService:
    """US5 參數 / 清單維護服務（DP 後台自身，不經 app.services 出口）。"""

    def __init__(self, repository: ParamRepository | None = None, audit: AuditLogService | None = None) -> None:
        self._repo = repository or ParamRepository()
        self._audit = audit or AuditLogService()

    async def _admin_flags(self, db: AsyncSession, user_id: str) -> tuple[bool, bool]:
        """回 (是否 ET 管理者, 是否 DM 管理者)。checker 未註冊時 fail-closed False（見 T017）。"""
        is_et = await module_admin_gate.is_module_admin("ET", user_id, db)
        is_dm = await module_admin_gate.is_module_admin("DM", user_id, db)
        return is_et, is_dm

    def _visible(self, scope: str, is_et: bool, is_dm: bool) -> bool:
        """平台級共用；模組級須具該模組管理者身分（A-strict，SA Q1 定案）。"""
        if scope == "platform":
            return True
        if scope == "ET":
            return is_et
        return is_dm  # DM

    async def list_visible(self, db: AsyncSession, user_id: str) -> list[ParamMasterResponse]:
        """列操作者可見之參數主檔 + 明細（平台級 + 具管理者身分之模組級）。"""
        is_et, is_dm = await self._admin_flags(db, user_id)
        masters = await self._repo.list_masters(db)
        result: list[ParamMasterResponse] = []
        for m in masters:
            scope = _scope(m.param_id)
            if not self._visible(scope, is_et, is_dm):
                continue
            details = await self._repo.list_details(db, m.param_id, enabled_only=False)
            result.append(
                ParamMasterResponse(
                    param_id=m.param_id,
                    param_name=m.param_name,
                    param_type=m.param_type,
                    detail_lock=m.detail_lock,
                    description=m.description,
                    scope=scope,  # type: ignore[arg-type]
                    details=[ParamDetailResponse.model_validate(d) for d in details],
                )
            )
        return result

    async def _require_visible_master(self, db: AsyncSession, param_id: str, user_id: str) -> DpParamMaster:
        """載入主檔並檢核操作者可見；不存在 404 DP_PARAM_004、越權 403 DP_PARAM_003。"""
        master = await self._repo.get_master(db, param_id)
        if master is None:
            raise AppError(status_code=404, detail=_NOT_FOUND_MSG, error_code="DP_PARAM_004")
        is_et, is_dm = await self._admin_flags(db, user_id)
        if not self._visible(_scope(param_id), is_et, is_dm):
            raise AppError(status_code=403, detail=_FORBIDDEN_MSG, error_code="DP_PARAM_003")
        return master

    async def update_detail(
        self, db: AsyncSession, *, param_id: str, param_key: str, data: ParamDetailUpdate, operator: OperatorInfo
    ) -> ParamDetailResponse:
        """更新明細值 / 啟停（param_key 不可改）。VALUE 型驗證型別 / 值域 + 跨欄位一致性。

        Raises:
            AppError: 未提供欄位（422 COMMON_001）、主檔 / 明細不存在（404 DP_PARAM_004）、
                越權（403 DP_PARAM_003）、值不合法（422 DP_PARAM_001）。
        """
        fields = data.model_dump(exclude_unset=True)
        if not fields:
            raise AppError(status_code=422, detail=_NO_FIELD_MSG, error_code="COMMON_001")

        master = await self._require_visible_master(db, param_id, operator.user_id)
        detail = await self._repo.get_detail(db, param_id, param_key)
        if detail is None:
            raise AppError(status_code=404, detail=_NOT_FOUND_MSG, error_code="DP_PARAM_004")

        new_value = fields.get("param_value")
        if new_value is not None and master.param_type == "VALUE":
            validate_param_value(param_id, param_key, new_value)
            await self._validate_group(db, master, param_key, new_value)

        before = {"param_value": detail.param_value, "is_enabled": detail.is_enabled}
        now = utcnow()
        await self._repo.update_detail(
            db,
            detail=detail,
            param_value=new_value,
            is_enabled=fields.get("is_enabled"),
            operator_id=operator.user_id,
            now=now,
        )
        await self._log(
            db,
            operator.user_id,
            param_id,
            param_key,
            "UPDATE",
            "維護參數明細",
            before=before,
            after={"param_value": detail.param_value, "is_enabled": detail.is_enabled},
        )
        return ParamDetailResponse.model_validate(detail)

    async def create_detail(
        self, db: AsyncSession, *, param_id: str, data: ParamDetailCreate, operator: OperatorInfo
    ) -> ParamDetailResponse:
        """新增 LIST 型清單項。

        Raises:
            AppError: 主檔不存在 / 越權、非 LIST 型（400 DP_PARAM_006）、
                鎖定清單不可新增（403 DP_PARAM_002）、代碼重複（409 DP_PARAM_005）。
        """
        master = await self._require_visible_master(db, param_id, operator.user_id)
        if master.param_type != "LIST":
            raise AppError(status_code=400, detail=_TYPE_MSG, error_code="DP_PARAM_006")
        if master.detail_lock:
            raise AppError(status_code=403, detail=_LOCKED_MSG, error_code="DP_PARAM_002")
        if await self._repo.get_detail(db, param_id, data.param_key) is not None:
            raise AppError(status_code=409, detail=_DUP_MSG, error_code="DP_PARAM_005")

        now = utcnow()
        # get_detail 檢查與 flush 之間有 TOCTOU 空窗：並發新增同碼 → 撞 PK_DP_PARAM_D。
        # 比照 users/verify_service 兜底轉乾淨 409（否則落全域 500），交 get_db rollback。
        try:
            detail = await self._repo.create_detail(
                db,
                param_id=param_id,
                param_key=data.param_key,
                param_value=data.param_value,
                sort_order=data.sort_order,
                operator_id=operator.user_id,
                now=now,
            )
        except IntegrityError as exc:
            raise AppError(status_code=409, detail=_DUP_MSG, error_code="DP_PARAM_005") from exc
        await self._log(
            db,
            operator.user_id,
            param_id,
            data.param_key,
            "CREATE",
            "新增參數清單項",
            after={"param_value": data.param_value, "is_enabled": True},
        )
        return ParamDetailResponse.model_validate(detail)

    async def _validate_group(self, db: AsyncSession, master: DpParamMaster, param_key: str, new_value: str) -> None:
        """載入同主檔全部明細、套用新值後檢核跨欄位一致性（如 PWD_POLICY）。"""
        details = await self._repo.list_details(db, master.param_id, enabled_only=False)
        values = {d.param_key: d.param_value for d in details if d.param_value is not None}
        values[param_key] = new_value
        validate_group_invariants(master.param_id, values)

    async def _log(
        self,
        db: AsyncSession,
        operator_id: str,
        param_id: str,
        param_key: str,
        action_type: str,
        description: str,
        *,
        before: dict | None = None,
        after: dict | None = None,
    ) -> None:
        await self._audit.log_action(
            db,
            module="DP",
            func_name=_FUNC_NAME,
            action_type=action_type,
            result="SUCCESS",
            operator_id=operator_id,
            target_id=f"{param_id}.{param_key}",
            description=description,
            before_value=before,
            after_value=after,
            source_ip=get_client_ip(),
        )
