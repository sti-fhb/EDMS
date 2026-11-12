"""忘記密碼服務（US3）：申請（產 token + 寄信）與重設（驗 token + 更新密碼）。

token 明文僅入信中連結、DB 存 SHA-256（research §5）；一次性（USED_DATE）+ 時效（EXPIRES_DATE），
同帳號重新申請作廢舊 token。防帳號列舉：申請一律成功語氣、帳號不存在不產 token / 不寄信。
重設更新密碼 + 追加歷程 + 作廢 token + 稽核；**不解除鎖定**（FR-07）。
門檻值（RESET_TOKEN_TTL_MIN / MIN_LEN / ADMIN_MIN_LEN / CHAR_TYPES / HISTORY_COUNT）讀平台級 DP_PARAM（SRVDP001）。

## 停用帳號完全不走本流程（#953，`spec_us3` FR-DP-US3-09 / AC 7）

`STATUS='DISABLED'` 的帳號：申請端比照「帳號不存在」早退，重設端與門檻查詢端回
`DP_PWD_007`「帳號已停用，請洽管理者」。**兩端都要擋**——只擋申請端的話，停用當下還在外面、
尚未過期的連結（TTL 預設 30 分鐘）仍然有效。

> 📌 #953 原本讓重設端回與 token 失效**逐字相同**的 `DP_PWD_005`，理由是防列舉；#958 裁示 1
> 推翻：能持有有效重設連結的人幾乎必然讀得到該帳號的登記信箱，告訴他「這個帳號停用了」
> 洩漏的是他自己帳號的狀態。等價的代價則是被停用者陷入「重新申請 → 收不到信 → 再申請」的
> 迴圈。⛔ **本裁示只動重設端**：申請端三種情況的回應仍逐字相同（那裡的請求者不需要任何
> 憑證，才是真正的列舉面），由 `test_forgot_request_endpoint_uniform_message` 釘住。

為什麼不是「反正停用帳號登不進去，改了也沒用」：重設連結的明文會留在寄出的信、寄件備份與
退信裡。讀得到那些信的人可以先把停用帳號的密碼改成自己知道的值（當下看起來無害，稽核只留
一筆 DP-FORGOT 成功），等日後管理者在 DP02 重新啟用該帳號——**重新啟用只改 `STATUS`、不動
密碼**——先前設定的密碼就直接生效。這是延遲生效的後門，不是當下可用的權限。

⛔ **鎖定（`LOCKED_UNTIL`）不在此列**：鎖定是暫時的，`spec_us3` 的用意就是讓使用者自己重設
密碼後等待解鎖。判定一律用 `is_account_disabled(status)`——⛔ 不要改用
`is_account_usable()`，它把鎖定也算進去，會讓鎖定中的使用者連自助重設的出路都沒有。

⚠️ **本流程不保證「檢查狀態」與「寫入密碼」之間的原子性**：管理者若恰好在這兩步之間按下停用，
密碼仍會被改掉。窗口自 `get_by_user_id` 到 `update_password`，含 `rules_for_user` 的數次查詢、
`is_reused_async`（**逐筆 bcrypt**，`PWD_POLICY.HISTORY_COUNT` 預設 3、上限 24 ⇒ 最壞約 4.4 秒）
與一次 `hash_password_async`，**預設組態下約 0.7 秒**。需要精準時序才撞得到，且停用後
`ensure_user_active`（`core/auth.py` 的每請求狀態閘）會讓該帳號的既有 JWT 與新登入一律
403 `DP_AUTH_004`，被改掉的密碼當下兌現不了，所以**不是**可利用的提權路徑。

> 📌 讓既有 JWT 失效的是上述**每請求狀態閘**，⛔ 不是 #941——#941 比的是「token 簽發時點 vs
> 密碼變更時點」，與帳號停用無關。兩者在同一支 `ensure_user_active` 裡相鄰，很容易記混。

寫在這裡是因為「停用後密碼就不可能再被改動」這句話太容易被當成無條件成立。要徹底關掉的話，
做法是在 `update_password` 的 UPDATE 補 `WHERE STATUS='ACTIVE'` 並檢查 rowcount；本案刻意不做，
因為那是把一個隱含條件塞進共用的寫入方法，而真正的根治是**停用當下就作廢該帳號所有未使用的
token**（見下）。

## 採「使用時才擋」而非「停用時作廢」——這是刻意的

停用不會去作廢該帳號名下未使用、未逾期的 token，它們仍留在 `DP_PWD_RESET`，由重設端每次
檢查帳號狀態來擋。兩個後果：

1. **停用後在 TTL 內重新啟用，舊連結可用**——⛔ 這是**預期行為**（#958 裁示 2），不是缺陷。
   管理者按下「啟用」本身就是「已判定該帳號沒問題」的決定；誤停用、隨後很快復原是常見的
   維運動作，讓使用者不必重新申請是合理的。
2. **`EMAIL_CHANGE` 型 token 尚未比照辦理**（追蹤於 #956）：`DP_PWD_RESET` 同表還存 Email
   變更 token，而 `email_change_service.verify()` **不檢查 `STATUS`**。在 ACTIVE 時申請把帳號
   Email 改成自己的、停用後才點連結，即可換走帳號的識別資訊，日後重新啟用再走忘記密碼。

⛔ #956 的修法方向是**在 `verify()` 補狀態判定**（與本檔同形），**不是**「停用時作廢所有
token」——後者會連帶把上面第 1 點的預期行為也關掉。
"""

import logging
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.log_redaction import mask_email
from app.core.password_hashing import hash_password_async, is_reused_async
from app.core.password_policy import validate_password_strength
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.dp.user.password_rules import PasswordRules, rules_for_user
from app.dp.user.repository import AuthRepository
from app.dp.user.token import generate_reset_token, hash_token
from app.dp.users.account_status import is_account_disabled, is_account_locked
from app.services import AuditLogService, NotifyService, ParamService

logger = logging.getLogger(__name__)

_TOKEN_TYPE = "PWD_RESET"  # noqa: S105 — DP_PWD_RESET.TOKEN_TYPE 值，非密碼
_TEMPLATE_CODE = "PWD_RESET"
_FUNC_NAME = "DP-FORGOT"
_DEFAULT_TTL_MIN = 30
_DEFAULT_HISTORY_COUNT = 3
_TOKEN_INVALID_MSG = "連結已失效，請重新申請"  # noqa: S105 — 使用者訊息，非密碼
#: 停用帳號持有效連結時的訊息（#958 裁示 1）。⛔ 兩支端點（`reset` / `password_rules_for_token`）
#: 必須共用本常數——各寫一句的話，同一個連結在載入頁與送出時會得到不同說法。
_ACCOUNT_DISABLED_MSG = "帳號已停用，請洽管理者"
#: 匿名路徑的稽核操作者：申請 / 重設端皆無登入身分，比照登入失敗對未知帳號的既有做法
#: （`dp/user/service.py`）。⚠️ `CREATED_USER` 為 VARCHAR(20)，本來就塞不下 Email。
_SYSTEM_USER = "SYSTEM"


class ForgotPasswordService:
    """申請忘記密碼（US3 T028）：防列舉 + 一次性時效 token + SRVDP002 寄信。"""

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

    async def request(self, db: AsyncSession, *, email: str) -> None:
        """申請重設：帳號存在**且未停用**才作廢舊 token、產新 token 並寄信；否則靜默（防列舉）。

        token 建立與 outbox 寫入於呼叫方交易內（flush），由 get_db 於請求成功時一併 commit（原子）。

        ⚠️ 停用的早退**必須排在 `invalidate_active_reset_tokens` 之前**：排在後面的話，對停用帳號
        連打本端點就成了一個無認證的「作廢他人既有連結」操作，而「沒產新 token、沒寄信」的測試
        仍會全綠（`test_forgot_disabled_does_not_invalidate_existing_token` 釘住此位置）。
        """
        ip = get_client_ip()
        user = await self._repo.get_by_email(db, email)
        if user is None:
            # 防帳號列舉：不產 token、不寄信，端點一律回相同訊息。
            # ⚠️ 稽核**記遮罩後的 Email**：此路徑沒有 user_id 可填（operator 為 SYSTEM），
            # 不記就只剩計數——問不出「哪些帳號被探測過」。遮罩規則沿用 `mask_email`
            # （規範禁記個資完整值），且稽核表 append-only、寫進去拿不掉。
            await self._audit_request(
                db, ip, operator_id=_SYSTEM_USER, target_id=mask_email(email), sent=False, reason="帳號不存在"
            )
            return
        if is_account_disabled(user.status):
            # 「查無此人」是真的沒事發生，「停用帳號被申請重設」是有人試了——後者正是 #953 的
            # 威脅模型，靜默丟掉會失去訊號。
            #
            # 📌 #958 之前這裡**刻意不寫稽核**，理由是「匿名端點寫稽核＝開放任何人灌
            # DP_AUDIT_LOG」。#958 推翻該決定：申請端三種情況一律寫稽核，因為「看不到有人
            # 申請過重設」本身就是缺口。灌量有上限——IP 維度與帳號維度都是 10 次／60 秒。
            #
            # ⚠️ log 仍保留且 `ip=` / `event=` 不可省：稽核是給稽核查詢用的，log 是給告警規則
            # 接的，兩者讀者不同。`router.py` 的同類 log 已載明「告警規則請抓 `event=` 字串
            # 而非整句」，而整句中文正是最容易被後人順手改掉的部分。
            logger.warning(
                "停用帳號申請忘記密碼已擋下 ip=%s email=%s event=forgot_blocked_disabled_account",
                ip,
                mask_email(email),
            )
            await self._audit_request(
                db, ip, operator_id=user.user_id, target_id=user.user_id, sent=False, reason="帳號已停用"
            )
            return

        now = utcnow()
        ttl_min = await self._params.get_int_param(db, "LOGIN", "RESET_TOKEN_TTL_MIN", _DEFAULT_TTL_MIN)
        await self._repo.invalidate_active_reset_tokens(db, user_id=user.user_id, token_type=_TOKEN_TYPE, now=now)

        plaintext = generate_reset_token()
        await self._repo.create_reset_token(
            db,
            token_hash=hash_token(plaintext),
            user_id=user.user_id,
            token_type=_TOKEN_TYPE,
            expires_date=now + timedelta(minutes=ttl_min),
            operator_id=user.user_id,
            now=now,
        )
        reset_link = f"{settings.FRONTEND_BASE_URL}/reset-password?token={plaintext}"
        await self._notify.send_email(
            db,
            recipients=[user.email],
            template_code=_TEMPLATE_CODE,
            module="DP",
            params={"user_name": user.user_name, "reset_link": reset_link, "expiry_minutes": str(ttl_min)},
            caller_module="DP",
        )
        await self._audit_request(
            db, ip, operator_id=user.user_id, target_id=user.user_id, sent=True, reason="已寄出重設信"
        )

    async def _audit_request(
        self,
        db: AsyncSession,
        ip: str | None,
        *,
        operator_id: str,
        target_id: str,
        sent: bool,
        reason: str,
    ) -> None:
        """申請端的稽核（#958）：三種情況各一筆，從 `result` 與 `description` 分得出是哪一種。

        ⛔ `description` 不得放 token、完整 Email、密碼。帳號不存在時由呼叫端先經 `mask_email`。

        `action_type` 用 `CREATE`：申請的實質是產生一枚重設 token。⛔ 不新增 `ACTION_TYPE` 值——
        `dp/audit/router.py` 的 `_Action` 是封閉 `Literal`，新增要同時改三處且有
        `test_dp_audit_action_type_coverage.py` 守門（#548）。

        ⚠️ 本方法**不 commit**：申請端三種情況都以 200 正常回應收尾，稽核隨請求的交易一起
        提交即可。重設端的失敗稽核不同——那裡會拋 `AppError`、交易會被 rollback，故需顯式
        commit（見 `ResetPasswordService._audit_reset_fail`）。
        """
        await self._audit.log_action(
            db,
            module="DP",
            func_name=_FUNC_NAME,
            action_type="CREATE",
            result="SUCCESS" if sent else "FAIL",
            operator_id=operator_id,
            target_id=target_id,
            description=reason,
            source_ip=ip,
        )


class ResetPasswordService:
    """以 token 重設密碼（US3 T029）：驗 token + 複雜度 + 重複性 + 更新 + 歷程 + 作廢 + 稽核。"""

    def __init__(
        self,
        repository: AuthRepository | None = None,
        params: ParamService | None = None,
        audit: AuditLogService | None = None,
    ) -> None:
        self._repo = repository or AuthRepository()
        self._params = params or ParamService()
        self._audit = audit or AuditLogService()

    async def _audit_reset_fail(
        self,
        db: AsyncSession,
        ip: str | None,
        *,
        operator_id: str,
        target_id: str | None,
        reason: str,
    ) -> None:
        """重設被擋下的稽核（#958）——**寫完立即 commit**，再由呼叫端拋 `AppError`。

        🔴 **commit 不可省**：`get_db` 對 `AppError` 會 rollback，稽核列會被一併抹除，
        結果是「程式有寫、DP05 查不到」。這個缺陷是靜默的——測試若在 service 層直接呼叫、
        或只驗「`log_action` 有被呼叫」，兩種寫法都會全綠。
        `test_reset_audit_失效token的FAIL稽核確實落地` **刻意走端點**來釘住它。

        同一理由與既有範式見 `dp/user/service.py::_fail`（登入失敗的鎖定計數與 FAIL 稽核）。

        ⚠️ 測試環境以 savepoint 隔離（`conftest` 的 `db` fixture），此處 commit 只釋放
        savepoint、不破壞隔離。

        ⛔ **只記安全相關的兩種**（token 失效、帳號停用）。密碼不一致 / 複雜度不足 /
        與近期重複是使用者打錯字，記了會把 DP05 變成流水帳，而稽核表 append-only、清不掉。
        """
        await self._audit.log_action(
            db,
            module="DP",
            func_name=_FUNC_NAME,
            action_type="UPDATE",
            result="FAIL",
            operator_id=operator_id,
            target_id=target_id,
            description=reason,
            source_ip=ip,
        )
        await db.commit()

    async def password_rules_for_token(self, db: AsyncSession, *, token: str) -> PasswordRules:
        """重設頁適用之門檻（#623）：依 token 對應帳號判定；token 失效則拒絕（#673）。

        ⛔ **失效一律回同一個錯誤，不得依其帳號分歧**——否則端點會替已作廢的連結報出
        「這是管理者」。本方法對「查無 / 已用 / 逾期」三種失效回完全相同的 `DP_PWD_005`，
        與帳號是否為管理者無關；`test_重設規則端點_失效token的回應不因是否為管理者而異`
        以同一個字面量斷言四個組合來釘住它。

        ### #673 之前：失效回一般門檻、不報錯

        原設計讓失效 token 回一般門檻（8 字元）「維持重設頁原有的提示時點」，連結失效留到
        送出時由 `reset` 告知。但 `spec_us3` AC 3 要求「token 已逾時或已被使用，**點連結**時
        拒絕並提示（DP-MSG-DP09-002）」——推遲到送出與該 AC 衝突，且使用者會先照著
        **錯的門檻**（管理者看到 8、實際要 12）打完一組密碼才被擋下。

        Raises:
            AppError: token 查無 / 已用 / 逾期（400 DP_PWD_005），訊息與 `reset` 同一常數。

        Returns:
            與 `reset` 檢核所用相同之門檻（同一支 `rules_for_user`）。
        """
        row = await self._repo.get_reset_token_by_hash(db, hash_token(token), _TOKEN_TYPE)
        if row is None or row.used_date is not None or row.expires_date <= utcnow():
            raise AppError(status_code=400, detail=_TOKEN_INVALID_MSG, error_code="DP_PWD_005")
        # 帳號於發信後被停用 → **明說**（#958 裁示 1，與 `reset` 共用同一常數與錯誤碼）。
        # ⚠️ 「查無此人」仍回 token 失效：那表示帳號已被軟刪，連結本身就不該再有意義，
        # 與「帳號還在、只是停用」是兩回事，不可合併成同一個分支。
        user = await self._repo.get_by_user_id(db, row.user_id)
        if user is None:
            raise AppError(status_code=400, detail=_TOKEN_INVALID_MSG, error_code="DP_PWD_005")
        if is_account_disabled(user.status):
            raise AppError(status_code=400, detail=_ACCOUNT_DISABLED_MSG, error_code="DP_PWD_007")
        return await rules_for_user(db, row.user_id, params=self._params)

    async def reset(self, db: AsyncSession, *, token: str, new_password: str, confirm_password: str) -> bool:
        """重設密碼；回傳該帳號**是否仍在鎖定中**（#958，供前端換提示文案）。

        Raises:
            AppError: 兩次不一致（422 DP_USER_002）、token 失效 / 已用 / 逾時（400 DP_PWD_005）、
                複雜度（422 DP_PWD_001/002）、重複性（422 DP_PWD_003）。
        """
        ip = get_client_ip()
        now = utcnow()
        if new_password != confirm_password:
            raise AppError(status_code=422, detail="兩次輸入之密碼不一致", error_code="DP_USER_002")

        token_hash = hash_token(token)
        row = await self._repo.get_reset_token_by_hash(db, token_hash, _TOKEN_TYPE)
        if row is None or row.used_date is not None or row.expires_date <= now:
            await self._audit_reset_fail(
                db, ip, operator_id=_SYSTEM_USER, target_id=None, reason="連結已失效，拒絕重設"
            )
            raise AppError(status_code=400, detail=_TOKEN_INVALID_MSG, error_code="DP_PWD_005")
        # 停用帳號與「查無此人」回同一個失效錯誤（#953）。位置在**消費 token 之前**，比照
        # 下方複雜度 / 重複性的處理——擋下時不白白作廢 token，且與 token 失效的拋出時點一致，
        # 使兩者連「先報哪個錯」都相同（密碼不一致仍先於兩者）。
        user = await self._repo.get_by_user_id(db, row.user_id)
        if user is None:
            # 帳號已軟刪：連結本身不該再有意義，回 token 失效（與「帳號還在、只是停用」不同）
            await self._audit_reset_fail(
                db, ip, operator_id=_SYSTEM_USER, target_id=row.user_id, reason="帳號不存在，拒絕重設"
            )
            raise AppError(status_code=400, detail=_TOKEN_INVALID_MSG, error_code="DP_PWD_005")
        if is_account_disabled(user.status):
            await self._audit_reset_fail(
                db, ip, operator_id=row.user_id, target_id=row.user_id, reason="帳號已停用，拒絕重設"
            )
            raise AppError(status_code=400, detail=_ACCOUNT_DISABLED_MSG, error_code="DP_PWD_007")

        # 複雜度 + 重複性（禁最近 HISTORY_COUNT 次）——於消費 token 前檢核，
        # 使複雜度 / 重複失敗時不白白作廢 token（使用者可用同連結重試）。
        # 長度門檻比照變更密碼依帳號判定（#623）：原本只讀 MIN_LEN，管理者可經忘記密碼繞過 12 字元。
        rules = await rules_for_user(db, user.user_id, params=self._params)
        validate_password_strength(new_password, min_length=rules.min_len, required_char_types=rules.char_types)
        history_count = await self._params.get_int_param(db, "PWD_POLICY", "HISTORY_COUNT", _DEFAULT_HISTORY_COUNT)
        recent = await self._repo.recent_pwd_hashes(db, user.user_id, history_count)
        if await is_reused_async(new_password, recent):
            raise AppError(status_code=422, detail="不可與最近使用過之密碼相同", error_code="DP_PWD_003")

        # 先算雜湊再進寫入段：雜湊為純 CPU、不依賴 DB 結果，放在 consume_reset_token 之後會讓
        # 該 UPDATE 的交易多持有 ~185ms 的執行緒往返（#214 review 附帶發現）。
        new_hash = await hash_password_async(new_password)

        # 原子消費 token（關閉「查→標用」TOCTOU；並發同 token 只有一個成功）→ 作為後續寫入的閘
        if await self._repo.consume_reset_token(db, token_hash=token_hash, token_type=_TOKEN_TYPE, now=now) is None:
            raise AppError(status_code=400, detail=_TOKEN_INVALID_MSG, error_code="DP_PWD_005")

        # 更新（不改鎖定 / 停用）+ 追加歷程 + 稽核
        # ⚠️ `PWD_CHANGED_DATE` 取寫入前的時間，理由同 `profile_service.change_password`（#941）：
        # 沿用函式開頭的 `now` 會讓「重設處理期間以舊密碼登入」取得的 token 在重設後仍有效。
        pwd_changed_at = utcnow()
        await self._repo.update_password(db, user=user, pwd_hash=new_hash, operator_id=user.user_id, now=pwd_changed_at)
        seq_no = await self._repo.next_pwd_seq_no(db, user.user_id)
        await self._repo.add_pwd_history(
            db, user_id=user.user_id, seq_no=seq_no, pwd_hash=new_hash, operator_id=user.user_id, now=now
        )
        await self._audit.log_action(
            db,
            module="DP",
            func_name=_FUNC_NAME,
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=user.user_id,
            target_id=user.user_id,
            description="密碼重設",
            source_ip=ip,
        )
        # 重設**不解除鎖定**（FR-DP-US3-07）。回傳鎖定狀態供前端換一句提示——否則鎖定中的
        # 使用者會看到「請以新密碼登入」，照做卻被 403 `DP_AUTH_005` 擋下（#958）。
        # ⚠️ 判定取 `user.locked_until` 的**當下值**：`update_password` 不碰該欄位（其 docstring
        # 明載「不動鎖定 / 停用狀態」），所以這裡讀到的仍是重設前的鎖定時間，正是要回報的。
        return is_account_locked(locked_until=user.locked_until, now=utcnow())
