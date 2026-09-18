"""Email 邀請 Service（US8 / #273、#362）。

## 邀請即加入——「待加入」與一次性 token 已整組移除（#362）

原設計是：寄信時寫一列 `ET_INVITATION`（`PENDING` + token 雜湊），受邀者點信中連結
呼叫 `accept` 才建 `ET_ENROLLMENT`；教師另有待加入清單可重寄 / 撤回。

2026-09-17 裁示取消整段中間狀態，理由是它**在學員端沒有對應的行為差異**：SA 早先已
裁示 Email 邀請只收**平台既有帳號**（見 `_require_known_recipients`），而既有帳號一旦
有 `ET_ENROLLMENT` 列就能在「我的課程」看到課程——受邀者從來不需要那封信才能進課程。
於是「待加入」只存在於教師端，且是會誤導他的那一端：被邀請的人**不會**出現在學員
清單裡，教師以為邀請失敗（2026-09-17 手測回報）。

隨之消失的東西要講明白，因為它們是真的能力，不是冗餘：

| 移除的 | 原本用途 | 現在 |
|---|---|---|
| 待加入清單 | 看誰還沒點 | 沒有「還沒點」這件事，人已在學員清單 |
| 再次寄送 | 信沒寄成功時補救 | **無補救途徑**，見 `send` 的取捨說明 |
| 撤回邀請 | 寄錯人時止血 | 改用 US9 既有的「移除學員」 |
| 一次性 token | `accept` 的憑證 | 沒有 accept，信中連結改為學習頁 |

⚠️ 已寄出的舊信裡那條 `/et/invite?token=…` 連結**會壞掉**（前端路由一併移除）。裁示
明示接受——邀請對象是既有帳號，他在「我的課程」看得到，死連結不會讓任何人進不了課程。

🔴 **本決策的前提是「只邀請既有帳號」。** 若日後改為可邀請尚未註冊的外部 Email，
「待加入」就會重新有意義（那時的受邀者確實需要一條連結才進得來），本決策必須重新檢討。

## 寄信結果記的是「排入佇列」不是「真的寄到」（#273 Q3 裁示 A）

平台 `NotifyService` 為 outbox 架構：`send_email` 只把信寫進 `DP_EMAIL_LOG`（PENDING）
就返回，真正的 SMTP 由 worker 事後執行，且 DP 未提供回呼或查詢介面讓 ET 對照
（`add_log` 連 log id 都不回傳）。因此 `mail_failed` 只涵蓋**排不進佇列**者（例如範本
被停用），信箱雖存在但 SMTP 退信的情況此處看不見，真實寄送結果之回寫仍是 follow-up。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.dp.users.account_status import is_account_disabled
from app.et.course.rules import ensure_owner
from app.et.invitation.repository import EtInvitationRepository
from app.et.invitation.rules import ensure_invitable, parse_emails
from app.et.invitation.schemas import (
    EmailInviteResult,
    InvitePreview,
)
from app.et.notify.course_invite import (
    PREVIEW_NAME_MASK,
    build_course_invite_params,
    learn_link,
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
_NO_EMAILS = AppError(status_code=422, detail="Email 格式不正確或數量超過上限", error_code="ET_INVITE_003")


class EtInvitationService:
    """Email 邀請之預覽與寄送（#362 起「寄送」即「加入」，無受邀加入這一步）。"""

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

        預覽**與收件人無關**：姓名以 `PREVIEW_NAME_MASK` 取代——那是逐收件人不同的
        東西，填任何一位的資料都會讓教師誤以為每封信都長那樣。其餘內容（課程名稱、
        閱課期間、邀請碼、學習連結）本來就人人相同，所以這份預覽對整批收件人都成立。

        ⚠️ 連結給的是**真值**（`learn_link`）。#362 之前它是遮罩過的 `…`，因為那時每人
        的一次性 token 不同、預覽當下也尚未產生。改為學習頁連結後人人相同，遮起來反而
        讓預覽與實際寄出的信對不起來。

        Raises:
            AppError: 404 `ET_COURSE_001`；403 `ET_COURSE_002` 非擁有者；
                422 `ET_INVITE_003` Email 不合法；422 `ET_INVITE_004` 課程非已發布；
                422 `ET_INVITE_005` 有 Email 尚無 EDMS 帳號；422 `ET_INVITE_008` 有帳號已停用；
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
                course_url=learn_link(course.course_id),
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
            await self._repo.upsert_enrollment(db, user_id=recipient.user_id, course_id=course_id, operator=operator)
            if not await self._deliver(db, course=course, recipient=recipient, teacher_name=teacher_name):
                mail_failed.append(recipient.email)
        joined = len(recipients)

        await self._write_audit(db, course_id=course_id, recipients=recipients, operator=operator)
        return EmailInviteResult(joined=joined, mail_failed=mail_failed)

    async def _write_audit(
        self, db: AsyncSession, *, course_id: int, recipients: list[Recipient], operator: OperatorInfo
    ) -> None:
        """逐人一列稽核——**但一定在加入迴圈結束之後才寫**。

        ## 為何逐人而非一筆彙總

        「把某人加進課程」是不需要他同意的動作，而他會因此出現在具名的問卷結果、核可
        名單與完訓統計裡。事後若有人問「誰把我加進去的」，彙總列（`target_id = 課程`、
        `description = 加入 N 位`）答不出來。

        同模組的**移除**學員早就是逐人一列、`target_id = f"{course_id}:{user_id}"`
        （`tracking/service.py`）——減人可追溯、加人不可追溯，這個不對稱正好反了。

        原本的說法是「需要知道加了誰時查 `ET_ENROLLMENT`」，但那張表是**可變的業務
        資料**：同一支 `send()` 的 upsert 會改寫 `JOIN_SOURCE` 與 `JOINED_AT`，事後查到
        的值不保證對應到某一次動作。稽核表的保存期比業務資料長，追溯責任不該外包給它。

        ## 🔴 為何不在迴圈裡直接寫

        `AuditLogService.log_action` 會取一把**全平台單一固定 key** 的交易級 advisory
        lock（`dp/audit/repository.acquire_chain_lock`），持有到外層交易 commit 為止。
        在逐筆迴圈裡呼叫，第一筆就取走鎖，之後整批的 DB 往返與**寄信**都在持鎖狀態下
        進行——期間所有寫稽核的動作（**包含登入**）全平台排隊。#352 踩過一次，作法同
        `approval/service.py::approve`：迴圈只累積、結束後統一寫。

        `source_ip` 也在迴圈外取一次：同一個請求的來源不會變，逐筆取只是重複工作。
        """
        source_ip = get_client_ip()
        for recipient in recipients:
            # `description` / `target_id` 只放 `USER_ID`，**不放 Email 或姓名**——
            # 那是個資，而稽核表的保存期比業務資料長（移除路徑同此作法）。
            await self._audit.log_action(
                db,
                module=_MODULE,
                func_name=_FUNC_NAME,
                action_type="CREATE",
                result="SUCCESS",
                operator_id=operator.user_id,
                target_id=f"{course_id}:{recipient.user_id}",
                description="Email 邀請加入課程",
                source_ip=source_ip,
            )

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

    async def _require_invitable_course(self, db: AsyncSession, course_id: int, actor_id: str):
        """課程存在 + 呼叫者為擁有者 + 課程已發布。"""
        course = await self._repo.get_course(db, course_id)
        if course is None:
            raise _NOT_FOUND
        ensure_owner(owner_id=course.owner_id, actor_id=actor_id)
        ensure_invitable(course_status=course.status, open_end_at=course.open_end_at, now=utcnow())
        return course

    async def _require_known_recipients(self, db: AsyncSession, emails: list[str]) -> list[Recipient]:
        """比對 `DP_USER`，**查無帳號或帳號已停用者一律擋下**（不加入、不寄信）。

        SA 裁示：Email 邀請的對象必須是既有的 EDMS 使用者。教師是用貼的，打錯一個字就會
        把課程資訊寄給系統外的陌生人，而他**永遠不會發現**——寄信結果只記「排入佇列」
        （Q3 裁示 A），退信不會回寫任何地方，#362 之後連待加入清單那個事後查看的位置也
        沒有了。擋在寄出之前是唯一看得見的時點。

        🔴 這道檢核同時是 #362「取消待加入」的前提：正因為收件人一定是既有帳號，才能
        在寄信當下就把人加進 `ET_ENROLLMENT`。放寬它之前請先重讀模組 docstring。

        ## 停用帳號擋下（#347 第一項，隨 #362 一併處理）

        `DP_USER.DELETED` **從來沒有任何 code path 會設成 1**（EDMS 無刪除使用者功能），
        離職／轉調／閒置 90 天自動禁用走的都是 `STATUS`——所以 `recipients_by_emails` 的
        `DELETED = 0` 對停用者完全無效。

        #362 之前這個缺口的後果有限：停用者收到信也登不進來（`core/auth.py` 每請求查
        `STATUS`，非 `ACTIVE` 回 403），他只會停在「待加入」清單上讓教師看見。**取消待
        加入之後後果變嚴重**——他會被直接寫進 `ET_ENROLLMENT`，而 ET03 清單與週報只濾
        `IS_REMOVED` / `DELETED`，於是一個永遠不可能完課的帳號會**永久坐在完訓率的分母
        裡**，還會出現在具名 CSV 中。

        ⚠️ 只擋「停用」，**不擋「鎖定中」**：`LOCKED_UNTIL` 是連續登入失敗的暫時性鎖，
        幾分鐘後自動解除。因為某人剛才打錯密碼就拒絕教師邀請他，教師完全無從理解。
        故用 `is_account_disabled()` 而非 `is_account_usable()`。

        Returns:
            依 `emails` 原順序排列之收件人（含姓名，供寄信時個人化）。

        Raises:
            AppError: 任一筆查無帳號（422 `ET_INVITE_005`，明細在 `extra.unknown_emails`）；
                任一筆帳號已停用（422 `ET_INVITE_008`，明細在 `extra.disabled_emails`）。
                `error_message` 依 `sti-error-codes` 不得嵌入動態值，故明細一律走 `extra`。
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
        # 🔴 與 `ET_INVITE_005` **分碼**：兩者的下一步完全不同——「請管理者建帳號」對一個
        # 已經有帳號的人是錯的指示，教師照做會得到一個重複帳號。
        disabled = [e for e in emails if is_account_disabled(by_email[e].status)]
        if disabled:
            raise AppError(
                status_code=422,
                detail="以下帳號已停用，無法邀請；請確認名單或請管理者先啟用帳號",
                error_code="ET_INVITE_008",
                extra={"disabled_emails": disabled},
            )
        return [by_email[e] for e in emails]
