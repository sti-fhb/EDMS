"""帳號（Email）變更服務（US8）：申請（唯一檢核 + 產 token + 寄新信箱）與驗證（切換 EMAIL）。

延遲生效（FR-03）：申請時不動 DP_USER.EMAIL，僅產一次性 EMAIL_CHANGE token（帶 NEW_EMAIL）並寫
PENDING_EMAIL、寄驗證信至**新信箱**；驗證前舊 Email 仍可登入。點連結驗證通過才切 EMAIL、清 PENDING、
作廢 token、寫稽核（含前後值）；逾時 / 已用一律作廢。token 明文入信、DB 存 SHA-256（research §5）。

重用 DP_PWD_RESET（TOKEN_TYPE=EMAIL_CHANGE）與忘記密碼共構（token.py / repository token 方法）。

📌 **停用帳號不得完成變更**（#956）：`verify()` 於切換前判定 `STATUS`，停用即回 `DP_PWD_007`
「帳號已停用，請洽管理者」並寫 FAIL 稽核。缺了這道閘，離職者可用停用前申請、尚未點擊的連結把
帳號 Email 換成自己的信箱——日後帳號一旦重新啟用，他就能走忘記密碼接管（攻擊全程都是正常功能，
稽核上只留一筆看似正常的「Email 變更」）。

⛔ **判定用 `is_account_disabled(status)`，不要改用 `is_account_usable()`**：後者把鎖定也算進去，
會讓「密碼打錯三次被鎖 15 分鐘」的使用者連 Email 變更都做不了，而鎖定是暫時的、非本案標的。
"""

import logging
from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.dp.user.repository import AuthRepository
from app.dp.user.token import generate_reset_token, hash_token
from app.dp.users.account_status import is_account_disabled
from app.services import AuditLogService, NotifyService, ParamService

logger = logging.getLogger(__name__)

_TOKEN_TYPE = "EMAIL_CHANGE"  # noqa: S105 — DP_PWD_RESET.TOKEN_TYPE 值，非密碼
_TEMPLATE_CODE = "EMAIL_CHANGE_VERIFY"  # 信件範本代碼
_FUNC_NAME = "DP-PROFILE"
_DEFAULT_TTL_MIN = 30
_TOKEN_INVALID_MSG = "連結已失效，Email 變更作廢，原 Email 維持有效"  # noqa: S105 — 使用者訊息，非密碼
#: 停用帳號點驗證連結時的訊息（#956 SA 裁示 Q1：明說，不與 token 失效混為一談）。
#:
#: 沿用 #958 既有的 `DP_PWD_007`——同前綴（本流程的 token 失效本來就是 `DP_PWD_005`）、同條件
#: （持有效的一次性連結但帳號已停用）、同訊息。⛔ 該碼有兩條來自 #958 的硬約束，沿用時一併守住：
#: **必須維持 400**、且**不得進入前端 `ACCOUNT_BLOCKED_CODES`**——兩者缺一不可，否則已登入的 A
#: 點到 B 的連結會被判成「A 的帳號被停用」而把 A 登出。這也是當初不重用 `DP_AUTH_004`（403、
#: 且在該表內）的原因。
#:
#: ⛔ **日後若有人為了「防列舉」把本碼併回 `DP_PWD_005`，那不會讓兩者變得不可區分。** 停用分支
#: 比失效分支多走一次 SELECT、一次 advisory lock、一次 INSERT 與一次 COMMIT，等鎖逾時還會回 503
#: 而失效分支不會——耗時與 503 的差異會**靜默地保留**那個區分能力。真正讓它不構成破口的，是
#: 「要先登入才申請得到 token、而持帳密者登入時本來就被告知帳號已停用」（SA 裁示 Q1），不是錯誤碼
#: 長得一不一樣。
_ACCOUNT_DISABLED_MSG = "帳號已停用，請洽管理者"


class EmailChangeService:
    """Email 變更（US8 T038）：申請寄新信箱驗證信 + 點連結後切換。"""

    def __init__(
        self,
        repository: AuthRepository | None = None,
        params: ParamService | None = None,
        notify: NotifyService | None = None,
        audit: AuditLogService | None = None,
    ) -> None:
        self._repo = repository or AuthRepository()
        self._params = params or ParamService()
        self._notify = notify or NotifyService()
        self._audit = audit or AuditLogService()

    async def request(self, db: AsyncSession, *, user_id: str, new_email: str) -> None:
        """申請 Email 變更：新信箱唯一檢核 → 作廢舊 token → 產新 token + PENDING_EMAIL → 寄新信箱。

        Raises:
            AppError: 查無帳號（404 DP_USER_008）、新 Email 已被使用（409 DP_USER_007）。
        """
        now = utcnow()
        user = await self._repo.get_by_user_id(db, user_id)
        if user is None:
            raise AppError(status_code=404, detail="查無此帳號", error_code="DP_USER_008")
        # 新信箱唯一：已被任一帳號使用或他人待驗證中即擋（延遲切換窗口，含軟刪除；亦擋「改為自己現用信箱」）
        # 他人驗證連結已逾期 / 作廢者不算待驗證中（#904）
        if await self._repo.email_taken_for_change(db, new_email, requester_id=user_id, now=now):
            raise AppError(status_code=409, detail="此 Email 已被使用", error_code="DP_USER_007")

        ttl_min = await self._params.get_int_param(db, "LOGIN", "EMAIL_CHANGE_TTL_MIN", _DEFAULT_TTL_MIN)
        await self._repo.invalidate_active_reset_tokens(db, user_id=user_id, token_type=_TOKEN_TYPE, now=now)

        plaintext = generate_reset_token()
        await self._repo.create_reset_token(
            db,
            token_hash=hash_token(plaintext),
            user_id=user_id,
            token_type=_TOKEN_TYPE,
            expires_date=now + timedelta(minutes=ttl_min),
            operator_id=user_id,
            now=now,
            new_email=new_email,
        )
        await self._repo.set_pending_email(db, user=user, pending_email=new_email, operator_id=user_id, now=now)

        verify_link = f"{settings.FRONTEND_BASE_URL}/verify-email-change?token={plaintext}"
        await self._notify.send_email(
            db,
            recipients=[new_email],
            template_code=_TEMPLATE_CODE,
            module="DP",
            params={"user_name": user.user_name, "verify_link": verify_link, "expiry_minutes": str(ttl_min)},
            caller_module="DP",
        )

    async def verify(self, db: AsyncSession, *, token: str) -> None:
        """以 token 完成 Email 變更：預檢 token 與帳號狀態 → 原子消費 → 切 EMAIL + 清 PENDING + 稽核。

        ### 為什麼改成「先唯讀預檢、後消費」（#956）

        原本是先原子消費、再查使用者。要在此補上停用判定時，那個順序會讓兩個需求互斥——
        擋下時若不 commit，失敗稽核會被 `get_db` 對 `AppError` 的 rollback 一併抹除；若 commit，
        又會把前面那筆消費一起落地、白白燒掉一張其實還有效的連結。改為消費前先唯讀預檢，
        兩者即可同時成立。範式同 `forgot_service.reset`（讀 → 查帳號 → 才消費）。

        ⚠️ 預檢**不取代**消費：一次性保證仍由 `consume_email_change_token` 的條件式 UPDATE
        提供，並發送出同一 token 仍只有一個成功。

        ⚠️ 預檢也**不取代**寫入端自己的條件。「判定」與「寫入」之間的窗口**不是毫秒級**——
        若管理者的停用交易已取得該列行鎖、尚未 commit，寫入會**等鎖而非失敗**，窗口上界因此是
        對方交易的長度（其中還含一次要搶稽核鏈 advisory lock 的寫入）。故 `switch_email` 自己帶
        `account_not_disabled_clause()` 把窗口關死（#956 安審 MEDIUM-1，完整推導見該方法 docstring）；
        它回 `False` 即代表處理期間帳號被停用，本方法與預檢擋下同樣回 `DP_PWD_007`。

        Raises:
            AppError: token 失效 / 已用 / 逾時、查無帳號、NEW_EMAIL 已非目前 PENDING_EMAIL
                （皆 400 DP_PWD_005）；帳號已停用（400 DP_PWD_007，#956）；新 Email 於 TTL 窗口內
                遭他人搶用（409 DP_USER_007）。
        """
        now = utcnow()
        token_hash = hash_token(token)
        row = await self._repo.get_active_email_change_token(db, token_hash=token_hash, now=now)
        if row is None:
            raise AppError(status_code=400, detail=_TOKEN_INVALID_MSG, error_code="DP_PWD_005")
        user = await self._repo.get_by_user_id(db, row.user_id)
        if user is None:
            # 帳號已軟刪：連結本身不該再有意義，回 token 失效。⚠️ 與「帳號還在、只是停用」是兩回事，
            # 不可合併成同一個分支（同 `forgot_service.reset` 的分法）。
            # 📌 本分支的 token **不會**被消費（改序之前是先消費才查得到這裡，會被消費）。目前無實際
            # 差異：`DP_USER.DELETED` 全 codebase 無寫入點、亦無還原功能；若日後補上軟刪 / 還原，
            # 軟刪期間殘留的有效連結會在還原後可用——屆時請一併決定是否要在此作廢。
            raise AppError(status_code=400, detail=_TOKEN_INVALID_MSG, error_code="DP_PWD_005")
        if is_account_disabled(user.status):
            await self._audit_verify_blocked(
                db,
                user_id=user.user_id,
                reason="持連結者嘗試完成 Email 變更，帳號已停用故拒絕",
                event="email_change_blocked_disabled_account",
            )
            raise AppError(status_code=400, detail=_ACCOUNT_DISABLED_MSG, error_code="DP_PWD_007")

        consumed = await self._repo.consume_email_change_token(db, token_hash=token_hash, now=now)
        if consumed is None:
            raise AppError(status_code=400, detail=_TOKEN_INVALID_MSG, error_code="DP_PWD_005")
        user_id, new_email = consumed
        # NEW_EMAIL 須仍是目前的 PENDING_EMAIL：與「變更審核中」同一判定（#904，repository `_pending_email_active`），
        # 並發重複申請殘留的另一筆有效 token 不可完成變更，免得畫面顯示審核中 Y、點 X 的連結卻切成 X
        # ⚠️ 刻意留在消費之後，純粹是為了不更動既有行為。⛔ 不要寫成「移到前面可少燒一張 token」——
        # 那是假的：本分支 `raise` 之後 `get_db` 會 rollback，連前面那筆消費一起還原，兩種順序都不燒。
        if user.pending_email != new_email:
            raise AppError(status_code=400, detail=_TOKEN_INVALID_MSG, error_code="DP_PWD_005")

        before_email = user.email
        # 縱深防禦：request 時的唯一性檢核與此處消費間仍有 TTL 窗口，若期間他人搶用同一 Email，
        # DB 之 UQ_DP_USER_EMAIL 會拋 IntegrityError；攔下轉乾淨 409（避免落成未處理 500）。
        try:
            switched = await self._repo.switch_email(
                db, user_id=user.user_id, new_email=new_email, operator_id=user_id, now=now
            )
        except IntegrityError as exc:
            raise AppError(status_code=409, detail="此 Email 已被使用", error_code="DP_USER_007") from exc
        if not switched:
            # 預檢通過後、寫入落地前帳號才被停用（#956 安審 MEDIUM-1）。
            # ⚠️ 本分支的 token **會**被消費：稽核要 commit，而那會把前面那筆消費一併落地。這與
            # 「擋下時不消費」的 AC 不衝突——該 AC 針對的是常態路徑（預檢擋下），而這裡是競態邊界，
            # 連結燒掉反而是安全的一邊。
            await self._audit_verify_blocked(
                db,
                user_id=user.user_id,
                reason="持連結者嘗試完成 Email 變更，帳號於處理期間停用故拒絕",
                event="email_change_blocked_disabled_during_write",
            )
            raise AppError(status_code=400, detail=_ACCOUNT_DISABLED_MSG, error_code="DP_PWD_007")
        await self._audit.log_action(
            db,
            module="DP",
            func_name=_FUNC_NAME,
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=user_id,
            target_id=user_id,
            description="Email 變更",
            before_value={"email": before_email},
            after_value={"email": new_email},
            source_ip=get_client_ip(),
        )

    async def _audit_verify_blocked(self, db: AsyncSession, *, user_id: str, reason: str, event: str) -> None:
        """停用帳號點驗證連結被擋下的稽核 + 告警 log（#956）——**寫完立即 commit**，再由呼叫端拋 `AppError`。

        🔴 **commit 不可省**：`get_db` 對 `AppError` 會 rollback，稽核列會被一併抹除，結果是
        「程式有寫、DP05 查不到」。這個缺陷是靜默的——測試若在 service 層直接呼叫、或只驗
        `log_action` 有被呼叫，兩種寫法都會全綠。`test_email_change_verify_停用帳號的稽核確實落地`
        刻意走端點來釘住它。同一理由與既有範式見 `forgot_service._audit_reset_fail`（#958）。

        🔴 **呼叫本方法之前的所有步驟必須保持唯讀。** commit 會把當下 session 內**所有**未提交的
        寫入一併落地。目前兩個呼叫點之前只有 SELECT（預檢擋下），或只有一筆刻意要落地的消費
        （競態擋下）。⛔ 日後若有人在狀態閘之前加入任何寫入（嘗試次數、PENDING 清理等），那筆
        寫入會在一個以 `AppError` 收場的請求裡被提交，而且**不會有任何測試變紅**。

        ⚠️ 測試環境以 savepoint 隔離（`conftest` 的 `db` fixture），此處 commit 只釋放 savepoint、
        不破壞隔離。

        ⛔ **`description` / `target_id` 不得帶 NEW_EMAIL**：那是申請時自選的字串、屬個資，而且
        #958 的 Code Review HIGH 正是遮罩後的 Email 寫進 `TARGET_ID`（String(100)）撐爆長度、
        讓匿名端點回 500——存在的帳號回 400、長網域回 500，兩者可區分即是帳號列舉破口。本方法
        寫進稽核的一切都是程式內固定字串或 `USER_ID`（String(20)），沒有使用者可控的值。

        ⚠️ `operator_id` 填的是 token 對應的帳號，但本端點匿名——持連結者未必是帳號本人（信件
        轉寄、共用信箱、申請時填錯地址）。DP05 會把它呈現為「操作者：某某」，故 `reason` 一律
        寫成「持連結者……」而不是「該使用者……」，免得人讀時誤判為本人所為。

        ## 可重放：已知且接受（與 #958 同一分界）

        擋下時不消費 token（SA 裁示 Q2），所以同一張有效連結可被重複送出，每次留一筆已 commit、
        **不可刪**的稽核列。上限：10 次/60 秒/IP（`core/rate_limit.py`）× TTL 上界 120 分
        ＝每 IP 每張 token 最多約 1,200 列，再乘上來源 IP 數；影響面是 DP05 匯出上限 10,000 筆。

        判定可接受的理由與 #958 一致：該案拒絕記錄的是**零知識即可觸發**、內容零資訊量的分支，
        而本分支需持有有效 token、每列都指名真實帳號、有調查價值。⛔ 不要據此把本稽核拿掉。
        """
        ip = get_client_ip()
        # 稽核給事後查詢用、log 給即時告警用，兩者讀者不同（同 `forgot_service.request` 的停用分支）。
        # ⛔ 只放 user_id 與 IP：token 與 NEW_EMAIL 都不得進 log。
        logger.warning("停用帳號嘗試完成 Email 變更已擋下 ip=%s user_id=%s event=%s", ip, user_id, event)
        await self._audit.log_action(
            db,
            module="DP",
            func_name=_FUNC_NAME,
            action_type="UPDATE",
            result="FAIL",
            operator_id=user_id,
            target_id=user_id,
            description=reason,
            source_ip=ip,
        )
        await db.commit()
