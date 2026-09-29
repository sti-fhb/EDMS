"""參數服務。

- ParamService（SRVDP001）：跨模組唯讀查詢，不快取——儲存即生效（research §7）。
- ParamAdminService（US5）：DP 後台維護（寫入），前綴過濾 + DETAIL_LOCK + 值域驗證 + 稽核；
  DP 內部使用，不經 app.services 出口暴露（唯讀契約不受污染）。
"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.module_admin import module_admin_gate
from app.core.module_assign import module_assign_registry
from app.core.operator import OperatorInfo
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.dp.audit.service import AuditLogService
from app.dp.params.models import DpParamMaster
from app.dp.params.param_rules import validate_group_invariants, validate_param_value
from app.dp.params.repository import ParamRepository
from app.dp.params.schemas import (
    ControlledCreate,
    ControlledItemResponse,
    ControlledRename,
    ControlledSectionResponse,
    ControlledToggle,
    ControlledToggleResponse,
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
            ParamItem(
                key=d.param_key,
                name=d.param_name,
                value=d.param_value,
                is_enabled=d.is_enabled,
                sort_order=d.sort_order,
            )
            for d in details
        ]


_FUNC_NAME = "DP-PARAMS"
_NOT_FOUND_MSG = "查無此參數"
_FORBIDDEN_MSG = "無權限維護此模組之參數"
_LOCKED_MSG = "此代碼已鎖定，不可修改代碼值"
_DUP_MSG = "清單項代碼已存在"
_TYPE_MSG = "此參數不支援清單項維護"
_NO_FIELD_MSG = "未提供任何更新欄位"
_IT_MANAGED_MSG = "此參數由 IT 設定，不可於畫面修改"
# 系統寫死的 enum 清單（後端稽核直接寫碼、非管理者維護對象），一律排除於維護面（見 /sti-plan #68 §9）
#
# 與 EDIT_SCOPE（#171）分層並存，兩者**作用層不同**，勿收斂為單一機制：
#
#   | | _SYSTEM_PARAM_IDS | EDIT_SCOPE |
#   |---|---|---|
#   | 作用層 | 主檔（PARAM_ID）| 明細（PARAM_ID + PARAM_KEY）|
#   | 語意 | 這個參數整組不屬於維護面 | 這一列誰可以改 |
#   | 錯誤碼 | 404 DP_PARAM_004 | 403 DP_PARAM_007 |
#
# ACTION_TYPE 的 5 列明細亦回填 EDIT_SCOPE='HIDDEN'（分類表在資料層完整），但實際擋人的是
# 主檔層這道——它先執行（list_visible 於迴圈開頭 continue、_require_visible_master 於載入前拋）。
# 移除本集合改由 EDIT_SCOPE 統一處理會讓 test_action_type_excluded_from_maintenance 變紅：
# 該測試刻意鎖定 404 行為，動它等於推翻當初的決定（#171 D1）。
_SYSTEM_PARAM_IDS = frozenset({"ACTION_TYPE"})

EDIT_SCOPE_ADMIN = "ADMIN"
EDIT_SCOPE_HIDDEN = "HIDDEN"


def is_editable_scope(edit_scope: str) -> bool:
    """該明細是否開放管理者於維護頁編輯（#171）。

    刻意寫成「只有 ADMIN 可編輯」而非「READONLY / HIDDEN 要擋」——對三個已知值兩者等價，
    對**未知值**方向相反。READONLY / HIDDEN 之值由 IT 直接操作 DB 變更（spec_us5 FR-DP-US5-11），
    人手寫入就有打成 'readonly' 的可能：本寫法讓它維持不可編輯，反向寫法會讓它悄悄變成可編輯。
    DB 端另有 CK_DP_PARAM_D_EDIT_SCOPE 擋住非三值之寫入，此處是不依賴該約束的第二道。
    """
    return edit_scope == EDIT_SCOPE_ADMIN


def _scope(param_id: str) -> str:
    """依 PARAM_ID 前綴判定歸屬：ET_ / DM_＝模組級；其餘＝平台級（platform，共用）。"""
    if param_id.startswith("ET_"):
        return "ET"
    if param_id.startswith("DM_"):
        return "DM"
    return "platform"


def _detail_snapshot(detail) -> dict:
    """明細可異動欄位快照（供稽核 before / after）。"""
    return {
        "param_name": detail.param_name,
        "param_value": detail.param_value,
        "description": detail.description,
        "is_enabled": detail.is_enabled,
    }


def _to_item(item) -> ControlledItemResponse:
    return ControlledItemResponse(
        code=item.code, name=item.name, is_builtin=item.is_builtin, is_enabled=item.is_enabled
    )


def _split_sections(module: str, kind, items) -> list[ControlledSectionResponse]:
    """把一個 kind 的項目攤成畫面分區：有子分組者每組一區，否則整個 kind 一區。"""
    if not kind.groups:
        return [
            ControlledSectionResponse(
                module=module,
                kind=kind.kind,
                name=kind.name,
                requires_code=kind.requires_code,
                items=[_to_item(i) for i in items],
            )
        ]
    return [
        ControlledSectionResponse(
            module=module,
            kind=kind.kind,
            name=kind.name,
            requires_code=kind.requires_code,
            group_code=group.code,
            group_name=group.name,
            items=[_to_item(i) for i in items if i.tag_group_code == group.code],
        )
        for group in kind.groups
    ]


class ControlledAdminService:
    """US5 模組受控清單維護服務（#182）。

    受控清單存於**模組自持表**（`DM_CATEGORY` / `DM_FUNC` / `DM_TAG` / `ET_TAG`），
    DP 一律經 `module_assign_registry` 委派模組 provider，不直接讀寫模組表
    （`sti-backend-boundaries`）。與 `ParamAdminService`（`DP_PARAM`）並存於同一畫面、
    但兩者資料源與鎖定語意不同，故不合併模型。
    """

    async def list_visible(self, db: AsyncSession, user_id: str) -> list[ControlledSectionResponse]:
        """列操作者可維護之受控清單分區（僅具該模組管理者身分者）。

        逐模組取 provider → `list_controlled_kinds()` 取分區定義 → 逐分區取項目。
        有子分組之 kind（DM 標籤）依組拆成多個分區，供畫面分區呈現。

        Args:
            db: 呼叫方 AsyncSession。
            user_id: 操作者 USER_ID。

        Returns:
            分區清單；無任何模組管理者身分回空清單（fail-closed，不拋例外）。
        """
        sections: list[ControlledSectionResponse] = []
        for module in module_assign_registry.registered_modules():
            provider = module_assign_registry.get(module)
            # checker 未註冊時 is_module_admin 回 False（fail-closed）——不得因 provider
            # 已註冊就列出該模組清單
            if provider is None or not await module_admin_gate.is_module_admin(module, user_id, db):
                continue
            for kind in await provider.list_controlled_kinds(db):
                items = await provider.list_controlled(db, kind.kind)
                sections.extend(_split_sections(module, kind, items))
        return sections

    async def _require_manageable(self, db: AsyncSession, module: str, user_id: str):
        """取該模組 provider，並確認操作者為該模組管理者。

        Raises:
            AppError: 非該模組管理者、或該模組未註冊 provider（403 DP_PARAM_003，fail-closed）。
        """
        provider = module_assign_registry.get(module)
        if provider is None or not await module_admin_gate.is_module_admin(module, user_id, db):
            raise AppError(status_code=403, detail=_FORBIDDEN_MSG, error_code="DP_PARAM_003")
        return provider

    async def create(
        self, db: AsyncSession, *, module: str, kind: str, data: ControlledCreate, operator: OperatorInfo
    ) -> None:
        """新增受控項（委派模組）。代碼格式 / 重複檢核與稽核皆由模組負責。

        Raises:
            AppError: 越權（403 DP_PARAM_003）；模組自身之業務碼（重複 / 格式 / 查無）原樣透出。
        """
        provider = await self._require_manageable(db, module, operator.user_id)
        await provider.create_controlled(db, kind, code=data.code or "", name=data.name, operator_id=operator.user_id)

    async def rename(
        self, db: AsyncSession, *, module: str, kind: str, code: str, data: ControlledRename, operator: OperatorInfo
    ) -> None:
        """受控項改名（委派模組）。內建項之保護規則歸模組（前端隱藏入口僅為 UX）。

        Raises:
            AppError: 越權（403 DP_PARAM_003）；模組業務碼原樣透出。
        """
        provider = await self._require_manageable(db, module, operator.user_id)
        await provider.rename_controlled(db, kind, code=code, new_name=data.name, operator_id=operator.user_id)

    async def set_enabled(
        self, db: AsyncSession, *, module: str, kind: str, code: str, data: ControlledToggle, operator: OperatorInfo
    ) -> ControlledToggleResponse:
        """受控項啟停（委派模組；不刪除）。

        Returns:
            受影響數（僅 DM 可見對象 soft-retire 有值）；該數字為下限，見 schema 說明。

        Raises:
            AppError: 越權（403 DP_PARAM_003）；模組業務碼原樣透出。
        """
        provider = await self._require_manageable(db, module, operator.user_id)
        result = await provider.set_controlled_enabled(
            db, kind, code=code, enabled=data.enabled, operator_id=operator.user_id
        )
        return ControlledToggleResponse(affected_docs=result.affected_docs, affected_viewers=result.affected_viewers)


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
            if m.param_id in _SYSTEM_PARAM_IDS:
                continue  # 系統 enum 不納維護頁
            scope = _scope(m.param_id)
            if not self._visible(scope, is_et, is_dm):
                continue
            all_details = await self._repo.list_details(db, m.param_id, enabled_only=False)
            # HIDDEN 明細不進維護面。濾在 service 而非 repository——後者同時供 ParamService
            # （SRVDP001）執行期讀取，那條路徑不得受維護層級影響，否則 MAIL.RATE_PER_MIN
            # 會讀不到而 fallback 到程式碼預設值：行為變了卻沒有任何錯誤訊息。
            #
            # 未知 EDIT_SCOPE 在這條路徑上**不會**變成「列得出來但不可編輯」——
            # ParamDetailResponse.edit_scope 是 Literal，未知值會在序列化時拋 ValidationError，
            # 使整頁 500。此情形由 CK_DP_PARAM_D_EDIT_SCOPE 擋在資料層而不會發生；
            # 真正需要 fail-closed 的是寫入路徑，那由 is_editable_scope() 負責（見其 docstring）。
            details = [d for d in all_details if d.edit_scope != EDIT_SCOPE_HIDDEN]
            # 整組皆 HIDDEN（如 MAIL）→ 連主檔一併不回傳，避免畫面出現 0 項的空群組。
            # 限定「本來就有明細」才跳過：本來就沒有明細的 LIST 主檔須留著，否則新建的清單
            # 連第一個項目都加不進去（維護頁的新增入口在主檔列上）。
            if all_details and not details:
                continue
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
        """載入主檔並檢核操作者可見；系統 enum / 不存在 404 DP_PARAM_004、越權 403 DP_PARAM_003。"""
        if param_id in _SYSTEM_PARAM_IDS:
            raise AppError(status_code=404, detail=_NOT_FOUND_MSG, error_code="DP_PARAM_004")  # 不開放維護
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
        # 維護層級檢核（#171）。位置有意義：
        # - 在模組過濾（_require_visible_master）之**後**——ET 管理者碰 DM 參數要回越權碼
        #   DP_PARAM_003，回 007 會讓前端分不出「你不是這模組的管理者」與「這參數誰都不能改」。
        # - 在值域驗證之**前**——這一列根本不開放編輯時，值合不合法無關緊要，也不必洩露
        #   一個改不動的參數的值域規則。
        # D2：READONLY ＝整列唯讀，四個欄位一律擋。不只擋 param_value——能停用就能讓
        # get_param_value() 回 None 使呼叫端 fallback 到預設值，等於繞過唯讀改了實際行為。
        if not is_editable_scope(detail.edit_scope):
            raise AppError(status_code=403, detail=_IT_MANAGED_MSG, error_code="DP_PARAM_007")

        new_value = fields.get("param_value")
        if new_value is not None and master.param_type == "VALUE":
            validate_param_value(param_id, param_key, new_value)
            await self._validate_group(db, master, param_key, new_value)

        before = _detail_snapshot(detail)
        now = utcnow()
        await self._repo.update_detail(db, detail=detail, fields=fields, operator_id=operator.user_id, now=now)
        await self._log(
            db,
            operator.user_id,
            param_id,
            param_key,
            "UPDATE",
            "維護參數明細",
            before=before,
            after=_detail_snapshot(detail),
        )
        return ParamDetailResponse.model_validate(detail)

    async def create_detail(
        self, db: AsyncSession, *, param_id: str, data: ParamDetailCreate, operator: OperatorInfo
    ) -> ParamDetailResponse:
        """新增 LIST 型清單項。

        **本方法刻意不看 `EDIT_SCOPE`**：該欄管的是「既有列誰能改」，不管「清單能不能被加列」。
        要讓整組清單不可變動請設 `DETAIL_LOCK=true`（下方那道檢核），兩者分工見 spec_us5
        〈三個相鄰機制的分工〉。把 LIST 的幾個明細標成 READONLY 而未設 DETAIL_LOCK 時，
        管理者仍能新增項目改變 get_param_list() 的結果——今日無可觸發對象（唯一的 LIST 主檔
        ACTION_TYPE 在 _require_visible_master 就被擋掉），日後新增 LIST 主檔時 MUST 一併確認。

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
                param_name=data.param_name,
                param_value=data.param_value,
                description=data.description,
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
            after=_detail_snapshot(detail),
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
        # 決策紀錄（2026-07-23，Security Review MEDIUM）：稽核前後值含 param_value 明文。
        # sti-backend-logging 將 DP_PARAM_D.PARAM_VALUE 列為敏感，但目前所有平台級 seed 參數
        # （JWT / PWD_POLICY / LOGIN / MAIL 數值、ACTION_TYPE 清單）皆非機密，故不遮罩（不為
        # 不存在情境預寫防禦碼，sti-coding-style）。日後若引入以 PARAM_VALUE 存放機密（如通關
        # 密碼雜湊）之參數，MUST 於此對該類 param_id 遮罩後再寫稽核（機密改走 config/.env 為上策）。
        #
        # 補充（2026-08-04，#112 Security Review MEDIUM）：description 自 #112 起開放維護頁編輯，
        # 屬使用者自由文字且同樣以明文入稽核。AuditLogService 的遮罩為 key 子字串比對
        # （password / secret / token…），"description" 不命中、架構上也抓不到自由文字內容，
        # 故改以 UI 提示（維護頁「說明」欄 helperText）勸阻填入機密，此處不加遮罩。
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
