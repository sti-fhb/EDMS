"""忘記密碼服務（US3）：申請（產 token + 寄信）與重設（驗 token + 更新密碼）。

token 明文僅入信中連結、DB 存 SHA-256（research §5）；一次性（USED_DATE）+ 時效（EXPIRES_DATE），
同帳號重新申請作廢舊 token。防帳號列舉：申請一律成功語氣、帳號不存在不產 token / 不寄信。
重設更新密碼 + 追加歷程 + 作廢 token + 稽核；**不解除鎖定**（FR-07）。
門檻值（RESET_TOKEN_TTL_MIN / MIN_LEN / ADMIN_MIN_LEN / CHAR_TYPES / HISTORY_COUNT）讀平台級 DP_PARAM（SRVDP001）。

## 停用帳號完全不走本流程（#953，`spec_us3` FR-DP-US3-09 / AC 7）

`STATUS='DISABLED'` 的帳號：申請端比照「帳號不存在」早退，重設端與門檻查詢端一律回與 token
失效相同的 `DP_PWD_005`。**兩端都要擋**——只擋申請端的話，停用當下還在外面、尚未過期的連結
（TTL 預設 30 分鐘）仍然有效。

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

## 🔴 本修法擋不到的兩種情形（已知殘留，追蹤於 #956）

本案採「**使用時才擋**」而非「停用時作廢」，因此停用帳號名下未使用、未逾期的 token 仍留在
`DP_PWD_RESET`。兩個後果：

1. **停用後在 TTL 內重新啟用**：誤停用、隨後很快復原（相當常見的維運動作），停用前寄出的
   連結在 TTL（`LOGIN.RESET_TOKEN_TTL_MIN`，預設 30 分、可設至 120 分）內**仍然有效**。
   本修法在這個區間不生效——這不需要精準時序。
2. **`EMAIL_CHANGE` 型 token 完全不在本案範圍**：`DP_PWD_RESET` 同表還存 Email 變更 token，
   而 `email_change_service.verify()` **不檢查 `STATUS`**。在 ACTIVE 時申請把帳號 Email 改成
   自己的、停用後才點連結，即可換走帳號的識別資訊，日後重新啟用再走忘記密碼——與本案同形
   而更隱蔽。

兩者的根治是同一個：**停用動作當下作廢該帳號所有未使用的 token 並清 `PENDING_EMAIL`**
（管理者已認證，不會重開「匿名作廢他人連結」的問題）。⛔ 不要在本檔逐條補判定去追它——
那會變成「每個讀 `DP_PWD_RESET` 的人都要記得檢查狀態」，而這正是 `EMAIL_CHANGE` 漏掉的原因。

> 📌 #956 完成後，本節即可整段移除——屆時這兩段就是過期的敘述。
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
from app.dp.users.account_status import is_account_disabled
from app.services import AuditLogService, NotifyService, ParamService

logger = logging.getLogger(__name__)

_TOKEN_TYPE = "PWD_RESET"  # noqa: S105 — DP_PWD_RESET.TOKEN_TYPE 值，非密碼
_TEMPLATE_CODE = "PWD_RESET"
_FUNC_NAME = "DP-FORGOT"
_DEFAULT_TTL_MIN = 30
_DEFAULT_HISTORY_COUNT = 3
_TOKEN_INVALID_MSG = "連結已失效，請重新申請"  # noqa: S105 — 使用者訊息，非密碼


class ForgotPasswordService:
    """申請忘記密碼（US3 T028）：防列舉 + 一次性時效 token + SRVDP002 寄信。"""

    def __init__(
        self,
        repository: AuthRepository | None = None,
        params: ParamService | None = None,
        notify: NotifyService | None = None,
    ) -> None:
        self._repo = repository or AuthRepository()
        self._params = params or ParamService()
        self._notify = notify or NotifyService()

    async def request(self, db: AsyncSession, *, email: str) -> None:
        """申請重設：帳號存在**且未停用**才作廢舊 token、產新 token 並寄信；否則靜默（防列舉）。

        token 建立與 outbox 寫入於呼叫方交易內（flush），由 get_db 於請求成功時一併 commit（原子）。

        ⚠️ 停用的早退**必須排在 `invalidate_active_reset_tokens` 之前**：排在後面的話，對停用帳號
        連打本端點就成了一個無認證的「作廢他人既有連結」操作，而「沒產新 token、沒寄信」的測試
        仍會全綠（`test_forgot_disabled_does_not_invalidate_existing_token` 釘住此位置）。
        """
        user = await self._repo.get_by_email(db, email)
        if user is None:
            return  # 防帳號列舉：不產 token、不寄信，端點一律回相同訊息
        if is_account_disabled(user.status):
            # 「查無此人」是真的沒事發生，「停用帳號被申請重設」是有人試了——後者正是本功能的
            # 威脅模型（#953），靜默丟掉會失去唯一的訊號。⛔ 只留 log，不寫稽核、不改回應內容
            # （本端點匿名可打，寫稽核等於開放任何人以他人 Email 灌 DP_AUDIT_LOG）。
            #
            # ⚠️ 既然這是**唯一**的訊號，`ip=` 與 `event=` 都不可省：少了 ip 只知道「有人試了」
            # 分不出是離職者本人誤觸還是外部探測；少了 event 則接不上告警規則——`router.py` 的
            # 同類 log 已載明「告警規則請抓 `event=` 字串而非整句」，而整句中文正是最容易被
            # 後人順手改掉的部分。
            logger.warning(
                "停用帳號申請忘記密碼已擋下 ip=%s email=%s event=forgot_blocked_disabled_account",
                get_client_ip(),
                mask_email(email),
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
        # 帳號於發信後被停用：回**完全相同**的失效錯誤（#953）。分歧的話，持有連結者即可
        # 據此判斷「這個帳號被停用了」——防列舉會在重設端破一個洞。
        user = await self._repo.get_by_user_id(db, row.user_id)
        if user is None or is_account_disabled(user.status):
            raise AppError(status_code=400, detail=_TOKEN_INVALID_MSG, error_code="DP_PWD_005")
        return await rules_for_user(db, row.user_id, params=self._params)

    async def reset(self, db: AsyncSession, *, token: str, new_password: str, confirm_password: str) -> None:
        """重設密碼。

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
            raise AppError(status_code=400, detail=_TOKEN_INVALID_MSG, error_code="DP_PWD_005")
        # 停用帳號與「查無此人」回同一個失效錯誤（#953）。位置在**消費 token 之前**，比照
        # 下方複雜度 / 重複性的處理——擋下時不白白作廢 token，且與 token 失效的拋出時點一致，
        # 使兩者連「先報哪個錯」都相同（密碼不一致仍先於兩者）。
        user = await self._repo.get_by_user_id(db, row.user_id)
        if user is None or is_account_disabled(user.status):
            raise AppError(status_code=400, detail=_TOKEN_INVALID_MSG, error_code="DP_PWD_005")

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
