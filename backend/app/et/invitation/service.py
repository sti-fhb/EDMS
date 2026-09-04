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
| 3 | 課程非 `PUBLISHED` | `ET_INVITE_002` |
| 4 | `PENDING` | 加入（upsert）→ 轉 `JOINED` |
| 5 | `JOINED` 且**呼叫者已在該課程名單內** | `already_joined` → 導向學習頁（AC 8） |
| 6 | `JOINED` 且呼叫者不在名單內 | `ET_INVITE_001`（一次性生效） |

步驟 5/6 用「呼叫者是否在名單內」而非「誰消耗了 token」：後者需在 `ET_INVITATION` 新增
`JOINED_USER_ID`（＝一支 migration），而它換來的資訊在此無額外價值——步驟 5 放行的人
本來就是該課程學員，導向學習頁不多給任何權限；步驟 6 擋下的正是要擋的對象。

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

import logging
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.et.common.tokens import generate_invitation_token, hash_token
from app.et.constants import COURSE_PUBLISHED, INVITATION_PENDING, INVITATION_REVOKED
from app.et.course.rules import ensure_owner
from app.et.invitation.repository import EtInvitationRepository
from app.et.invitation.rules import ensure_invitable, parse_emails
from app.et.invitation.schemas import EmailInviteResult, InviteAcceptResult, InvitePreview
from app.et.notify.course_invite import (
    build_course_invite_params,
    invite_link,
    preview_invite_link,
)
from app.et.notify.mailer import TEMPLATE_COURSE_INVITE
from app.et.notify.repository import EtNotifyRepository
from app.et.notify.service import EtNotifier
from app.services import NotifyService

logger = logging.getLogger(__name__)

_MODULE = "ET"

_NOT_FOUND = AppError(status_code=404, detail="查無此課程", error_code="ET_COURSE_001")
#: 查無 / 已消耗 / 已撤回 / 格式不符**共用同一碼**——拆碼會告訴持有者「這個 token 曾經
#: 有效」，那正是轉發者想要的回饋。
_LINK_INVALID = AppError(status_code=404, detail="邀請連結無效或已失效", error_code="ET_INVITE_001")
_COURSE_CLOSED = AppError(status_code=409, detail="此課程目前關閉中", error_code="ET_INVITE_002")

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
    ) -> None:
        self._repo = repository or EtInvitationRepository()
        self._notify = notify or NotifyService()
        self._notifier = notifier or EtNotifier()
        self._people = people or EtNotifyRepository()

    async def preview(self, db: AsyncSession, course_id: int, *, raw_emails: str, actor_id: str) -> InvitePreview:
        """依統一範本渲染邀請信預覽（唯讀，FR-ET-US8-07）。

        以**第 1 筆**收件人為範例：每位收件人的邀請連結不同，逐封預覽沒有意義。
        連結以佔位字樣呈現（`preview_invite_link`）——預覽當下尚未產生任何 token，
        給出一條真的可以用的連結才是問題。

        Raises:
            AppError: 404 `ET_COURSE_001`；403 `ET_COURSE_002` 非擁有者；
                422 `ET_INVITE_003` Email 不合法；422 `ET_INVITE_004` 課程非已發布；
                404/409/422 `DP_MAIL_*` 範本問題。
        """
        course = await self._require_invitable_course(db, course_id, actor_id)
        emails = parse_emails(raw_emails)
        if not emails:
            raise AppError(status_code=422, detail="Email 格式不正確或數量超過上限", error_code="ET_INVITE_003")

        sample = emails[0]
        rendered = await self._notify.render_preview(
            db,
            template_code=TEMPLATE_COURSE_INVITE,
            module=_MODULE,
            params=build_course_invite_params(
                user_name=await self._display_name(db, sample),
                teacher_name=await self._people.user_name(db, course.owner_id) or "",
                course=course,
                course_url=preview_invite_link(),
                invitation_code=course.invitation_code,
            ),
        )
        return InvitePreview(
            subject=rendered.subject,
            body=rendered.body,
            recipient_sample=sample,
            recipient_count=len(emails),
        )

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
            raise AppError(status_code=422, detail="Email 格式不正確或數量超過上限", error_code="ET_INVITE_003")

        teacher_name = await self._people.user_name(db, course.owner_id) or ""
        sent = 0
        failed: list[str] = []
        for email in emails:
            # 每位收件人一組獨立 token：明文只入信中連結，DB 只存 SHA-256。
            plaintext = generate_invitation_token()
            result = await self._notifier.notify(
                db,
                template_code=TEMPLATE_COURSE_INVITE,
                recipients=[email],
                params=build_course_invite_params(
                    user_name=await self._display_name(db, email),
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
                email=email,
                token_hash=hash_token(plaintext),
                send_status_code=STATUS_QUEUED if queued else STATUS_SEND_FAILED,
                operator=operator,
            )
            if queued:
                sent += 1
            else:
                failed.append(email)
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
        if course.status != COURSE_PUBLISHED:
            # 關閉期間連結暫時失效，再開課後恢復——與邀請碼同一規則（#273 Q2 裁示）。
            raise _COURSE_CLOSED

        if invitation.status != INVITATION_PENDING:
            return await self._already_consumed(db, course, user_id=operator.user_id)

        await self._repo.upsert_enrollment(db, user_id=operator.user_id, course_id=course.course_id, operator=operator)
        await self._repo.mark_joined(db, invitation, operator=operator)
        logger.info("受邀者以邀請連結加入課程 user=%s course_id=%s", operator.user_id, course.course_id)
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

    async def _display_name(self, db: AsyncSession, email: str) -> str:
        """`{USER_NAME}` 之值：有帳號用姓名，沒有就用 Email 原字串。

        Email 邀請的對象**可能尚無帳號**（那正是它存在的理由）。範本開頭是
        「{USER_NAME} 您好：」，留空會變成「 您好：」。
        """
        recipient = await self._people.recipient_by_email(db, email)
        return recipient.user_name if recipient is not None else email
