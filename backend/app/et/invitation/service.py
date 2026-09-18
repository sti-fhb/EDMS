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
from app.core.pagination import PaginatedResult, paginate
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.et.common.tokens import generate_invitation_token, hash_token
from app.et.constants import COURSE_PUBLISHED, INVITATION_PENDING, INVITATION_REVOKED
from app.et.course.rules import ensure_owner, is_effectively_closed
from app.et.invitation.repository import EtInvitationRepository
from app.et.invitation.rules import ensure_invitable, parse_emails
from app.et.invitation.schemas import (
    EmailInviteResult,
    InviteAcceptResult,
    InvitePreview,
    PendingInviteRow,
)
from app.et.notify.course_invite import (
    PREVIEW_NAME_MASK,
    build_course_invite_params,
    learn_link,
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
#: 查無 / 格式不符**共用同一碼**——拆碼會告訴持有者「這個 token 曾經有效」，那正是
#: 轉發者想要的回饋。
#:
#: ⚠️ **「已撤回」自 2026-09-16 起分流至 `_LINK_REVOKED`**（SA 裁示，`FR-ET-US12-05`）。
#: 那次放寬接受的是「**持有有效 token 者**可知其狀態」——邀請 token 寄到特定信箱，能拿到
#: 它的人本來就知道它存在。**查無 token 仍必須回本碼**，否則亂數試探即可列舉曾存在的
#: token 空間（`test_查無token仍回001` 釘住）。
_LINK_INVALID = AppError(status_code=404, detail="邀請連結無效或已失效", error_code="ET_INVITE_001")
#: 已撤回——**只在「查得到該列且 `STATUS = REVOKED`」時使用**（`ET-MSG-ET03-104`）。
#: 410 Gone 而非 404：資源確實存在過、已被擁有者主動移除，這正是 410 的語意。
_LINK_REVOKED = AppError(status_code=410, detail="此邀請已撤回", error_code="ET_INVITE_006")
_COURSE_CLOSED = AppError(status_code=409, detail="此課程目前關閉中", error_code="ET_INVITE_002")
#: 重寄時排入信件佇列失敗。**必須讓整筆交易回滾**——token 在此之前已換新，不回滾的話
#: 淨效果是「一鍵讓對方的連結失效，而且沒有新信寄出」，比什麼都不做更糟。
#: 與 `send()` 的不對稱是刻意的：初次寄送失敗只是「沒建成」，重寄失敗會**毀掉一條還能用的連結**。
_RESEND_FAILED = AppError(status_code=503, detail="邀請信寄送失敗，請稍後再試", error_code="ET_INVITE_007")
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
        """對每筆 Email **直接加入課程**並寄出邀請信（FR-ET-US8-08、#362）。

        ## 邀請即加入，不再有「待加入」中間狀態

        原流程是寫一列 `ET_INVITATION` PENDING、等對方點信中連結才建 `ET_ENROLLMENT`。
        裁示取消那一段（2026-09-17）的理由：**邀請對象限平台既有帳號**，被邀請者不需要
        任何動作就能在「我的課程」看到課程，所以「待加入」與「已加入」在**學員端沒有
        任何行為差異**，只在教師端多一個要記得去看的頁面——而教師看不到被邀請的人出現
        在學員清單裡，會以為邀請失敗（2026-09-17 手測回報）。

        ## 🔴 加入先寫、寄信在後，且**寄信失敗不回滾加入**

        與原本「寄信失敗不回滾邀請列」同一個方向，但代價不同：原本失敗者留在待加入
        清單、教師可重寄；**現在沒有重寄的途徑**（US12 的補救隨功能一起移除）。

        接受這個代價的理由是學員**不依賴那封信**——他在「我的課程」就看得到。信只是
        提醒，不是加入的必要條件。信沒到最壞是他晚一點才發現，而非加不進來。

        ⚠️ 故回應的 `joined` 與 `mail_failed` **必須分開**，見 `EmailInviteResult`。

        Returns:
            `joined`（實際加入人數，與學員清單一致）與 `mail_failed`（信件排入失敗者）。
        """
        course = await self._require_invitable_course(db, course_id, operator.user_id)
        emails = parse_emails(raw_emails)
        if not emails:
            raise _NO_EMAILS
        # **重跑預覽的全部驗證**——預覽是體驗，不是把關。順帶取得各人姓名，
        # 不必再逐筆查一次（單次上限 50 筆，逐筆查就是 50 趟往返）。
        recipients = await self._require_known_recipients(db, emails)

        teacher_name = await self._people.user_name(db, course.owner_id) or ""
        mail_failed: list[str] = []
        for recipient in recipients:
            # 🔴 **加入在寄信之前**。反過來寫（寄信成功才加入）會讓「範本被停用」這種
            # 與學員無關的設定問題擋掉整批加入，而加入是教師真正要的那件事。
            #
            # `upsert_enrollment` 而非 INSERT：被移除的學員那一列還在
            # （`UQ_ET_ENROLLMENT_USER_COURSE` 為全表唯一），INSERT 會撞鍵。且教師的
            # **明確重新邀請**得以把他帶回來——那是 #247 SA Q1 裁示 C 的一側，與標籤
            # 帶入的 `DO NOTHING` 刻意不共用實作（見該函式 docstring）。
            await self._repo.upsert_enrollment(
                db, user_id=recipient.user_id, course_id=course_id, operator=operator
            )
            if not await self._deliver(db, course=course, recipient=recipient, teacher_name=teacher_name):
                mail_failed.append(recipient.email)
        joined = len(recipients)

        # 收件人**不寫進 description**：那是個資，而稽核表的保存期比業務資料長。
        # 需要知道加了誰時查 `ET_ENROLLMENT`（`JOIN_SOURCE = EMAIL_INVITE` + `COURSE_ID`
        # 可對上本筆稽核的 target_id）。`ET_INVITATION` 已隨 #362 移除。
        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME,
            action_type="CREATE",
            result="SUCCESS",
            operator_id=operator.user_id,
            target_id=str(course_id),
            description=f"Email 邀請加入 {joined} 位（信件排入失敗 {len(mail_failed)} 筆）",
            source_ip=get_client_ip(),
        )
        return EmailInviteResult(joined=joined, mail_failed=mail_failed)

    async def resend(self, db: AsyncSession, invitation_id: int, *, operator: OperatorInfo) -> None:
        """再次寄送同一封邀請信（`FR-ET-US12-03`）。

        ## 「同一封」指同一範本、同一收件人，**不是同一條連結**

        `TOKEN_HASH` 存的是雜湊，原始 token 不可還原，技術上也做不到沿用。而
        `upsert_pending()` 的 docstring 已裁定**必須換新 token**：舊 token 已隨信流出，
        沿用會讓「一次性」只是延後生效。副作用是受邀者手上的舊信會失效（點了得
        `ET_INVITE_001`），這是既有設計的必然結果，前端確認框會明說。

        ## 三個順序都是刻意的

        1. **擁有權檢查在狀態檢查之前**——反過來會讓他人課程的邀請以 403/404 的差異
           洩漏「該 id 是否仍為 `PENDING`」，而 `INVITATION_ID` 是連號的
        2. **`rotate_token` 在寄信之前**——它以主鍵 + `STATUS=PENDING` 為條件，能擋下
           「重寄與撤回交錯」；寄信在後才能在失敗時一起回滾
        3. **排入失敗直接拋錯**（`_RESEND_FAILED`）讓整筆交易回滾。不回滾的話 token 已換
           新而信沒寄出，等於一鍵讓對方的連結失效且無人知情——比什麼都不做更糟。與
           `send()`「寄信失敗不回滾邀請」的不對稱是刻意的：初次寄送失敗只是沒建成，
           重寄失敗會**毀掉一條還能用的連結**

        走 `_require_invitable_course`（含關閉守門）——關閉期間不該再招生
        （`FR-ET-US12-06`）。與 `revoke()` 的差別見 `_require_owned_course` 的 docstring。

        Raises:
            AppError: 404 `ET_COURSE_001` 查無課程；403 `ET_COURSE_002` 非擁有者；
                409 `ET_INVITE_002` / 422 `ET_INVITE_004` 課程不可邀請；
                404 `ET_INVITE_001` 查無邀請或已非待加入；
                422 `ET_INVITE_005` 收件人已無 EDMS 帳號；503 `ET_INVITE_007` 排入失敗。
        """
        invitation = await self._repo.get_by_id(db, invitation_id)
        if invitation is None:
            raise _LINK_INVALID
        course = await self._require_invitable_course(db, invitation.course_id, operator.user_id)
        if invitation.status != INVITATION_PENDING:
            raise _LINK_INVALID

        recipients = await self._require_known_recipients(db, [invitation.email])
        recipient = recipients[0]
        teacher_name = await self._people.user_name(db, course.owner_id) or ""
        plaintext = generate_invitation_token()
        rotated = await self._repo.rotate_token(
            db,
            invitation_id=invitation_id,
            token_hash=hash_token(plaintext),
            send_status_code=STATUS_QUEUED,
            operator=operator,
        )
        if not rotated:
            # 輸掉與 accept / revoke 的競態——該邀請已被消耗或撤回，不該再寄。
            raise _LINK_INVALID
        if not await self._deliver(
            db, course=course, recipient=recipient, teacher_name=teacher_name, plaintext=plaintext
        ):
            raise _RESEND_FAILED

        # 收件人不寫進 description（個資；稽核表保存期比業務資料長），比照 `send()`。
        # `target_id` 帶 invitation_id：一門課一天可能多次重寄，只有 course_id 無法定位。
        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME,
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=operator.user_id,
            target_id=f"{invitation.course_id}:{invitation_id}",
            description="再次寄送邀請信",
            source_ip=get_client_ip(),
        )

    async def revoke(self, db: AsyncSession, invitation_id: int, *, operator: OperatorInfo) -> None:
        """撤回邀請（`FR-ET-US12-04`）——原連結即刻失效。

        🔴 **走 `_require_owned_course`，刻意不含關閉守門**（SA 裁示 2026-09-16）。理由與
        「不可合併這兩支」的說明見 `_require_owned_course` 的 docstring。

        擁有權檢查排在狀態檢查之前，理由同 `resend()`（避免以 403/404 的差異洩漏狀態）。

        **撤回本身是原子的**（`mark_revoked` 把 `STATUS=PENDING` 寫在 `WHERE` 裡）：與
        `accept()` 交錯時只會有一方成功，不會把已寫入的 `JOINED` 蓋成 `REVOKED`。輸掉
        競態回 404——那代表學員已經加入了，教師該改用 US9 的「移除學員」。

        Raises:
            AppError: 404 `ET_COURSE_001` 查無課程；403 `ET_COURSE_002` 非擁有者；
                404 `ET_INVITE_001` 查無邀請、已加入或已撤回。
        """
        invitation = await self._repo.get_by_id(db, invitation_id)
        if invitation is None:
            raise _LINK_INVALID
        await self._require_owned_course(db, invitation.course_id, operator.user_id)
        if not await self._repo.mark_revoked(db, invitation_id=invitation_id, operator=operator):
            raise _LINK_INVALID
        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME,
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=operator.user_id,
            target_id=f"{invitation.course_id}:{invitation_id}",
            description="撤回邀請",
            source_ip=get_client_ip(),
        )

    async def accept(self, db: AsyncSession, *, token: str, operator: OperatorInfo) -> InviteAcceptResult:
        """受邀者以邀請連結加入課程（FR-ET-US8-09）。

        判斷順序見模組 docstring——**不可調換**。

        Raises:
            AppError: 404 `ET_INVITE_001` 連結無效 / 查無；410 `ET_INVITE_006` 此邀請已撤回；
                409 `ET_INVITE_002` 課程關閉中。
        """
        invitation = await self._repo.get_by_token_hash(db, hash_token(token))
        # 🔴 兩個分支**必須分開**：查無 → 001（不洩漏存在性）；查得到且已撤回 → 006。
        # 合併成 `invitation is None or ... REVOKED` 再回 006，會讓從未存在過的 token 也
        # 被告知「已撤回」——那是存在性 oracle 的放大版，不是 SA 裁示接受的範圍。
        if invitation is None:
            raise _LINK_INVALID
        if invitation.status == INVITATION_REVOKED:
            raise _LINK_REVOKED

        course = await self._repo.get_course(db, invitation.course_id)
        if course is None:
            raise _LINK_INVALID

        # 「已消耗」判定**先於**課程狀態判定：反過來的話，持有已消耗 token 的第三人在課程
        # 關閉期間會拿到 409「此課程目前關閉中」，那等於向他確認這個 token 真實存在。
        #
        # 走到這裡的非 `PENDING` 只剩 `JOINED`（`REVOKED` 已於上方分流），回 200 +
        # `already_joined`（US8 AC 8：不重複加入、直接導向），不是錯誤。
        if invitation.status != INVITATION_PENDING:
            return await self._already_consumed(db, course, user_id=operator.user_id)

        # 關閉期間連結暫時失效，再開課後恢復——與邀請碼同一規則（#273 Q2 裁示）。
        # #288：**閱課期間已過亦視同關閉**。少了後者，教師在期間內寄出的連結會在期間過後
        # 仍可被接受，受邀者加入的卻是一門他進去後什麼都不能做的課程。
        if course.status != COURSE_PUBLISHED or is_effectively_closed(
            status=course.status, open_end_at=course.open_end_at, now=utcnow()
        ):
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

    async def _deliver(self, db: AsyncSession, *, course, recipient, teacher_name: str) -> bool:
        """把一封邀請信排入 outbox。

        ## 信中連結改為學習頁，不再是一次性 token（#362）

        原本 `COURSE_URL` 塞 `invite_link(plaintext)`——那條連結的用途是讓受邀者
        「接受邀請」。邀請即加入之後沒有要接受的東西了，故改塞 `learn_link`，與**標籤
        自動邀請**那條路徑統一（`notify/mailer.py` 本來就是這樣）。

        ⚠️ 這也是為什麼 `ET_INVITATION` 連同 token 一起移除得掉：token 存在的唯一理由
        是 accept 流程。

        Returns:
            True 表示已排入 outbox。**非** SMTP 真實結果（平台為 outbox 架構）。
        """
        result = await self._notifier.notify(
            db,
            template_code=TEMPLATE_COURSE_INVITE,
            recipients=[recipient.email],
            params=build_course_invite_params(
                user_name=recipient.user_name,
                teacher_name=teacher_name,
                course=course,
                course_url=learn_link(course.course_id),
                invitation_code=course.invitation_code,
            ),
        )
        return result.queued_count > 0

    async def _require_owned_course(self, db: AsyncSession, course_id: int, actor_id: str):
        """課程存在 + 呼叫者為擁有者。**刻意不含 `ensure_invitable`（關閉判定）。**

        🔴 **不要與 `_require_invitable_course()` 合併**——兩者差一個關閉守門，而那個差別
        是刻意的：

        | 用途 | 關閉時 |
        |---|---|
        | 待加入清單（唯讀）| 照常可看（`FR-ET-US12-06` 明訂）|
        | 撤回邀請 | **仍可執行**（SA 裁示 2026-09-16）|
        | 再次寄送 | 擋（用 `_require_invitable_course`）|

        撤回是**止血**動作：教師發現邀請寄錯人（例如打錯 Email 寄到外部單位）時，若課程
        剛好到期自動關閉而撤回被擋，那條錯誤連結會一直有效到再開課為止，且再開課當下
        立刻可用。限制它只會讓錯誤持續更久。

        `test_課程關閉時仍可撤回邀請` 釘住這件事——少了它，日後有人依 ET 模組「寫全停」
        的慣例把守門補上，不會有任何測試變紅。
        """
        course = await self._repo.get_course(db, course_id)
        if course is None:
            raise _NOT_FOUND
        ensure_owner(owner_id=course.owner_id, actor_id=actor_id)
        return course

    async def list_pending(
        self, db: AsyncSession, course_id: int, *, actor_id: str, page: int, limit: int
    ) -> PaginatedResult[PendingInviteRow]:
        """ET-12 待加入清單（`FR-ET-US12-01`）。

        唯讀，故走 `_require_owned_course`——課程關閉時照常可看。
        """
        await self._require_owned_course(db, course_id, actor_id)
        stmt = self._repo.build_pending_list_stmt(course_id=course_id)
        return await paginate(db, stmt, page=page, limit=limit, schema=PendingInviteRow)

    async def _require_invitable_course(self, db: AsyncSession, course_id: int, actor_id: str):
        """課程存在 + 呼叫者為擁有者 + 課程已發布。"""
        course = await self._repo.get_course(db, course_id)
        if course is None:
            raise _NOT_FOUND
        ensure_owner(owner_id=course.owner_id, actor_id=actor_id)
        ensure_invitable(course_status=course.status, open_end_at=course.open_end_at, now=utcnow())
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
