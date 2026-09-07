"""Email 邀請 Service（US8 / #273）。

## 一次性 token（#273 Q1 裁示）

**不比對登入者的帳號 Email 與 `ET_INVITATION.EMAIL`**：邀請學員的主要方式是發布課程時
依受訓單位標籤自動帶入，個別 Email 邀請屬少數補件路徑，不值得為它引入一條會卡到正常
使用者的規則（收信信箱與登入帳號不同是常見情形）。

改以「token 只能被消耗一次」收斂轉發風險。`accept` 的判斷順序**不可調換**：

| # | 條件 | 結果 |
|---|---|---|
| 1 | 查無該 token | `ET_INVITE_001` |
| 2 | 已 `REVOKED` | `ET_INVITE_001` |
| 3 | 非 `PENDING`（已消耗）且**呼叫者已在該課程名單內** | `already_joined` → 導向學習頁（AC 8） |
| 4 | 非 `PENDING` 且呼叫者不在名單內 | `ET_INVITE_001`（一次性生效） |
| 5 | 課程非 `PUBLISHED` | `ET_INVITE_002` |
| 6 | 原子消耗失敗（併發下輸掉競態） | 回到步驟 3/4 的判定 |
| 7 | 消耗成功 | 加入（upsert）+ 寫稽核 |

步驟 3/4 用「呼叫者是否在名單內」而非「誰消耗了 token」：後者需在 `ET_INVITATION` 新增
`JOINED_USER_ID`（＝一支 migration），而它換來的資訊在此無額外價值——步驟 3 放行的人
本來就是該課程學員，導向學習頁不多給任何權限；步驟 4 擋下的正是要擋的對象。

**步驟 3/4 刻意排在步驟 5（課程狀態）之前**：反過來的話，持有已消耗 token 的第三人在
課程關閉期間會收到 409「此課程目前關閉中」而非 404「連結無效」，等於向他確認這個 token
真實存在——與「查無 / 已消耗 / 已撤回共用同一碼」的用意相牴觸。

**步驟 6 不是理論情境**：消耗若不是原子的（先查後改），兩個請求會都讀到 `PENDING`、
各自建立選課列，於是**兩個人都加入成功**——一次性被並發繞過。詳見
`repository.consume_pending` 的說明。

⚠️ **一次性 ≠ 防轉發，實際語意是「先到先得」**：若受邀者在點擊前就把信轉出去，先點的
人會加入成功、原受邀者反而拿到死連結。Q1 裁示已接受此殘留風險（誤入者由教師於 US9
移除；標籤帶入那條路仍不會把被移除者帶回）。

## `SEND_STATUS_CODE` 記的是「排入結果」不是「真的寄到」（#273 Q3 裁示 A）

平台 `NotifyService` 為 outbox 架構：`send_email` 只把信寫進 `DP_EMAIL_LOG`（PENDING）
就返回，真正的 SMTP 由 worker 事後執行，且 DP 未提供回呼或查詢介面讓 ET 對照
（`add_log` 連 log id 都不回傳）。因此本欄只可能記錄**排入佇列的結果**。

後果要講明白：信箱打錯字或已停用時 SMTP 會退信，但本欄仍是 `QUEUED`——US12 待加入
清單看起來是「已寄出、等對方點」。故 US12 之「再次寄送」**對所有 `PENDING` 邀請一律
開放、不依賴本欄過濾**。真實寄送結果之回寫已列為 follow-up。
"""

from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.request_context import get_client_ip
from app.et.common.tokens import generate_invitation_token, hash_token
from app.et.constants import COURSE_PUBLISHED, INVITATION_PENDING, INVITATION_REVOKED
from app.et.course.rules import ensure_owner
from app.et.invitation.repository import EtInvitationRepository
from app.et.invitation.rules import ensure_invitable, parse_emails
from app.et.invitation.schemas import EmailInviteResult, InviteAcceptResult, InvitePreview
from app.et.notify.course_invite import (
    PREVIEW_NAME_MASK,
    build_course_invite_params,
    invite_link,
    preview_invite_link,
)
from app.et.notify.mailer import TEMPLATE_COURSE_INVITE
from app.et.notify.repository import EtNotifyRepository, Recipient
from app.et.notify.service import EtNotifier
from app.services import AuditLogService, NotifyService

_MODULE = "ET"
#: 稽核來源功能碼。`et/spec.md` §稽核來源功能碼 定義的是 `ET-ENROLL`，但 #247 之
#: `enrollment/service.py` 實際寫入 `ET-ENROLLMENT`。此處沿用**既有程式碼**的值——
#: 同一語意類別（學員邀請 / 加入 / 移除）在 `DP_AUDIT_LOG` 裡分裂成兩個碼，比對不上
#: 文件更難追查。差異已列給 SA 後續同步 spec。
_FUNC_NAME = "ET-ENROLLMENT"

_NOT_FOUND = AppError(status_code=404, detail="查無此課程", error_code="ET_COURSE_001")
#: 查無 / 已消耗 / 已撤回 / 格式不符**共用同一碼**——拆碼會告訴持有者「這個 token 曾經
#: 有效」，那正是轉發者想要的回饋。
_LINK_INVALID = AppError(status_code=404, detail="邀請連結無效或已失效", error_code="ET_INVITE_001")
_COURSE_CLOSED = AppError(status_code=409, detail="此課程目前關閉中", error_code="ET_INVITE_002")
_NO_EMAILS = AppError(status_code=422, detail="Email 格式不正確或數量超過上限", error_code="ET_INVITE_003")

#: 排入 outbox 的結果碼（`ET_INVITATION.SEND_STATUS_CODE`，VARCHAR(20)）。
STATUS_QUEUED: Final = "QUEUED"
STATUS_SEND_FAILED: Final = "SEND_FAILED"


class EtInvitationService:
    """Email 邀請之預覽、寄送與受邀加入。"""

    def __init__(
        self,
        repository: EtInvitationRepository | None = None,
        notify: NotifyService | None = None,
        notifier: EtNotifier | None = None,
        people: EtNotifyRepository | None = None,
        audit: AuditLogService | None = None,
    ) -> None:
        self._repo = repository or EtInvitationRepository()
        self._notify = notify or NotifyService()
        self._notifier = notifier or EtNotifier()
        self._people = people or EtNotifyRepository()
        self._audit = audit or AuditLogService()

    async def preview(self, db: AsyncSession, course_id: int, *, raw_emails: str, actor_id: str) -> InvitePreview:
        """依統一範本渲染邀請信預覽（唯讀，FR-ET-US8-07）。

        預覽**與收件人無關**：姓名以 `PREVIEW_NAME_MASK`、邀請連結以 `…` 取代——兩者都是
        逐收件人不同的東西，填任何一位的資料都會讓教師誤以為每封信都長那樣。其餘內容
        （課程名稱、閱課期間、邀請碼）本來就人人相同，所以這份預覽對整批收件人都成立。

        連結不給真值還有一個理由：預覽當下尚未產生任何 token，給出一條真的可以用的
        連結才是問題。

        Raises:
            AppError: 404 `ET_COURSE_001`；403 `ET_COURSE_002` 非擁有者；
                422 `ET_INVITE_003` Email 不合法；422 `ET_INVITE_004` 課程非已發布；
                422 `ET_INVITE_005` 有 Email 尚無 EDMS 帳號；
                404/409/422 `DP_MAIL_*` 範本問題。
        """
        course = await self._require_invitable_course(db, course_id, actor_id)
        emails = parse_emails(raw_emails)
        if not emails:
            raise _NO_EMAILS
        # 於此就擋下查無帳號者，教師不必等到按下「確認寄出」才發現打錯字。
        await self._require_known_recipients(db, emails)

        rendered = await self._notify.render_preview(
            db,
            template_code=TEMPLATE_COURSE_INVITE,
            module=_MODULE,
            params=build_course_invite_params(
                # 姓名以佔位字樣呈現、不填任何一位收件人的資料：預覽只有一份，而每封信
                # 代入的是各自的姓名。填第 1 筆會讓教師以為每封信都長那樣；填 Email 更糟
                # ——實際寄出用的是帳號姓名，預覽與收到的信對不起來。見 PREVIEW_NAME_MASK。
                user_name=PREVIEW_NAME_MASK,
                teacher_name=await self._people.user_name(db, course.owner_id) or "",
                course=course,
                course_url=preview_invite_link(),
                invitation_code=course.invitation_code,
            ),
        )
        return InvitePreview(subject=rendered.subject, body=rendered.body)

    async def send(
        self, db: AsyncSession, course_id: int, *, raw_emails: str, operator: OperatorInfo
    ) -> EmailInviteResult:
        """對每筆 Email 建立 / 更新 `ET_INVITATION` 並寄出邀請信（FR-ET-US8-08）。

        **邀請列先寫、寄信在後，且寄信失敗不回滾邀請**（data-model §ET_INVITATION：
        寄送失敗時 `STATUS` 維持 `PENDING`、列於 US12 待加入清單可重寄）。

        Returns:
            `sent`（成功排入 outbox 的封數）與 `failed`（排入失敗的 Email）。
        """
        course = await self._require_invitable_course(db, course_id, operator.user_id)
        emails = parse_emails(raw_emails)
        if not emails:
            raise _NO_EMAILS
        # **重跑預覽的全部驗證**——預覽是體驗，不是把關。順帶取得各人姓名，
        # 不必再逐筆查一次（單次上限 50 筆，逐筆查就是 50 趟往返）。
        recipients = await self._require_known_recipients(db, emails)

        teacher_name = await self._people.user_name(db, course.owner_id) or ""
        sent = 0
        failed: list[str] = []
        for recipient in recipients:
            # 每位收件人一組獨立 token：明文只入信中連結，DB 只存 SHA-256。
            plaintext = generate_invitation_token()
            result = await self._notifier.notify(
                db,
                template_code=TEMPLATE_COURSE_INVITE,
                recipients=[recipient.email],
                params=build_course_invite_params(
                    user_name=recipient.user_name,
                    teacher_name=teacher_name,
                    course=course,
                    course_url=invite_link(plaintext),
                    invitation_code=course.invitation_code,
                ),
            )
            queued = result.queued_count > 0
            await self._repo.upsert_pending(
                db,
                course_id=course_id,
                email=recipient.email,
                token_hash=hash_token(plaintext),
                send_status_code=STATUS_QUEUED if queued else STATUS_SEND_FAILED,
                operator=operator,
            )
            if queued:
                sent += 1
            else:
                failed.append(recipient.email)

        # 收件人**不寫進 description**：那是個資，而稽核表的保存期比業務資料長。
        # 需要知道寄給誰時查 `ET_INVITATION`（有 `COURSE_ID` 可對上本筆稽核的 target_id）。
        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME,
            action_type="CREATE",
            result="SUCCESS",
            operator_id=operator.user_id,
            target_id=str(course_id),
            description=f"寄送 Email 邀請 {len(emails)} 筆（成功排入 {sent} 筆）",
            source_ip=get_client_ip(),
        )
        return EmailInviteResult(sent=sent, failed=failed)

    async def accept(self, db: AsyncSession, *, token: str, operator: OperatorInfo) -> InviteAcceptResult:
        """受邀者以邀請連結加入課程（FR-ET-US8-09）。

        判斷順序見模組 docstring——**不可調換**。

        Raises:
            AppError: 404 `ET_INVITE_001` 連結無效 / 已被使用；409 `ET_INVITE_002` 課程關閉中。
        """
        invitation = await self._repo.get_by_token_hash(db, hash_token(token))
        if invitation is None or invitation.status == INVITATION_REVOKED:
            raise _LINK_INVALID

        course = await self._repo.get_course(db, invitation.course_id)
        if course is None:
            raise _LINK_INVALID

        # 「已消耗」判定**先於**課程狀態判定：反過來的話，持有已消耗 token 的第三人在課程
        # 關閉期間會拿到 409「此課程目前關閉中」而非 404「連結無效」——那等於向他確認這個
        # token 真實存在，與「查無 / 已消耗 / 已撤回共用同一碼」的用意相牴觸。
        if invitation.status != INVITATION_PENDING:
            return await self._already_consumed(db, course, user_id=operator.user_id)

        if course.status != COURSE_PUBLISHED:
            # 關閉期間連結暫時失效，再開課後恢復——與邀請碼同一規則（#273 Q2 裁示）。
            raise _COURSE_CLOSED

        # 先原子消耗、再加入：輸掉競態者不會建出第二筆選課列（見 repository 之說明）。
        if not await self._repo.consume_pending(db, invitation_id=invitation.invitation_id, operator=operator):
            return await self._already_consumed(db, course, user_id=operator.user_id)

        await self._repo.upsert_enrollment(db, user_id=operator.user_id, course_id=course.course_id, operator=operator)
        # 稽核是「先到先得」殘留風險的**補償控制**：Q1 裁示接受了連結可能被轉發後由他人
        # 使用，那麼事後查得出「是誰用這條連結進來的」就是唯一的追溯手段。
        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME,
            action_type="CREATE",
            result="SUCCESS",
            operator_id=operator.user_id,
            target_id=str(course.course_id),
            description="以邀請連結加入課程",
            source_ip=get_client_ip(),
        )
        return InviteAcceptResult(course_id=course.course_id, course_name=course.course_name, already_joined=False)

    # ── 內部 ────────────────────────────────────────────────────────────────

    async def _already_consumed(self, db: AsyncSession, course, *, user_id: str) -> InviteAcceptResult:
        """token 已被消耗——依「呼叫者是否已在課程名單內」分流（模組 docstring 步驟 5/6）。

        已在名單內 → 這是本人（或已由其他途徑加入者）重複點連結，導向學習頁即可，
        不多給任何權限。不在名單內 → 連結被轉發給第二個人，一次性於此生效。
        """
        enrollment = await self._repo.get_enrollment(db, user_id=user_id, course_id=course.course_id)
        if enrollment is None or enrollment.is_removed:
            raise _LINK_INVALID
        return InviteAcceptResult(course_id=course.course_id, course_name=course.course_name, already_joined=True)

    async def _require_invitable_course(self, db: AsyncSession, course_id: int, actor_id: str):
        """課程存在 + 呼叫者為擁有者 + 課程已發布。"""
        course = await self._repo.get_course(db, course_id)
        if course is None:
            raise _NOT_FOUND
        ensure_owner(owner_id=course.owner_id, actor_id=actor_id)
        ensure_invitable(course_status=course.status)
        return course

    async def _require_known_recipients(self, db: AsyncSession, emails: list[str]) -> list[Recipient]:
        """比對 `DP_USER`，**查無帳號者一律擋下**（不建邀請列、不寄信）。

        SA 裁示：Email 邀請的對象必須是既有的 EDMS 使用者。教師是用貼的，打錯一個字就會
        把課程資訊寄給系統外的陌生人，而他自己要到 US12 待加入清單才可能發現——且因
        `SEND_STATUS_CODE` 只記「排入佇列」（Q3 裁示 A），連退信都不會反映在那張清單上。
        擋在寄出之前是唯一看得見的時點。

        > 取捨：這使本端點可被用來「一次貼 50 筆 Email、得知哪些有 EDMS 帳號」。呼叫者是
        > 已認證的教師 / 管理者，且只得到有無帳號的布林值（不回姓名等個資），SA 已評估
        > 可接受；router 之使用者維度限流一併限制了探測速率。

        Returns:
            依 `emails` 原順序排列之收件人（含姓名，供寄信時個人化）。

        Raises:
            AppError: 任一筆查無帳號（422 `ET_INVITE_005`）。是哪幾筆放在
                `extra.unknown_emails`——`error_message` 依 `sti-error-codes` 不得嵌入動態值。
        """
        by_email = {r.email: r for r in await self._people.recipients_by_emails(db, emails)}
        unknown = [e for e in emails if e not in by_email]
        if unknown:
            raise AppError(
                status_code=422,
                detail="以下 Email 尚未建立 EDMS 帳號，請確認拼寫或請管理者先建立帳號",
                error_code="ET_INVITE_005",
                extra={"unknown_emails": unknown},
            )
        return [by_email[e] for e in emails]
