"""線下核可 Service（US16 / #352）。

**授權兩層**：router 掛 `require_et_roles(ET_TEACHER, ET_ADMIN)`，service 以
`ensure_owner_or_admin` 判定擁有權——`FR-ET-US16-07` 明訂執行者限該課程 owner（教師）
或管理者，非 owner 之其他教師不得核可。

## 🔴 稽核不是附加動作，是歷程的唯一載體

`ET_APPROVAL` 因 `(COURSE_ID, USER_ID)` 唯一而以 update 覆寫，**前一次的結果被蓋掉之後
就不存在了**。`data-model` §ET_APPROVAL 因此明訂完整歷程（含撤銷後重核所覆寫的前次
結果）另寫入 `DP_AUDIT_LOG`（`FUNC_NAME=ET-APPROVAL`）。

所以每一條寫入路徑都必須帶 `before_value` / `after_value`。漏寫的表現是：本表看起來
一切正常，但「這個人被撤銷過幾次、上一次是誰核可的」永遠查不回來。

## 核可獨立於完課（`FR-ET-US16-09`）

本模組**不碰** `ET_ENROLLMENT` 的任何欄位，也不參與完課率 / 平均成績 / 問卷開放 /
週報的任何聚合。隔離靠的是結構而非小心——`tracking` 另查一次核可、在 service 層合併，
絕不把 `ET_APPROVAL` 併進 `completion_counts_by_student` 的 `GROUP BY`（那裡已為
「兩個一對多 JOIN 互相灌大計數」設了兩道防禦，核可是第三個一對多關聯）。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.et.approval.repository import EtApprovalRepository
from app.et.approval.rules import ensure_revoke_reason, is_active_approval
from app.et.approval.schemas import ApprovalRow, ApproveReq, ApproveResult, RevokeReq, SkippedItem
from app.et.constants import APPROVAL_PASS
from app.et.course.models import EtCourse
from app.et.course.rules import ensure_owner_or_admin, is_effectively_closed
from app.et.enrollment.rules import is_course_completed
from app.et.notify.approval_passed import ApprovalPassedMailer
from app.et.notify.repository import EtNotifyRepository
from app.et.tracking.repository import EtTrackingRepository
from app.services import AuditLogService

_NOT_FOUND = AppError(status_code=404, detail="查無此課程", error_code="ET_COURSE_001")
_NOT_REQUIRED = AppError(status_code=409, detail="此課程未啟用線下核可", error_code="ET_APPROVAL_001")
_COURSE_CLOSED = AppError(status_code=409, detail="課程已關閉，無法執行此管理動作", error_code="ET_APPROVAL_002")
_APPROVAL_NOT_FOUND = AppError(status_code=404, detail="查無核可紀錄", error_code="ET_APPROVAL_003")
_VERSION_CONFLICT = AppError(
    status_code=409, detail="核可狀態已被其他人變更，請重新整理後再試", error_code="ET_APPROVAL_004"
)

# ⚠️ **沒有「學員尚未完課」的錯誤碼**，這是刻意的。
#
# `ET-MSG-ET03-304`「學員尚未完課，無法核可」在 spec 裡歸類為**錯誤**、觸發情境是
# 「場景 3：對未完課學員核可」——但同一個場景 3 又明訂那顆按鈕根本不顯示。也就是說
# 它是防繞過用的訊息，正常 UI 產生不出來。
#
# 本模組讓單筆與批次走**同一條路徑**（單筆即 `user_ids` 長度為 1），未完課一律回
# `skipped[reason=NOT_COMPLETED]`。前端據筆數選訊息：單筆顯示 `304`（錯誤），
# 批次顯示 `303`（提示，帶筆數）。後端因此沒有產生 `ET_APPROVAL_002` 的路徑，
# 註冊一個沒人 raise 的碼只會讓下一個人去找它的呼叫點。
#
# 代價是「請求了一件事、什麼都沒發生」時仍回 200。可以接受：回應明白寫著
# `approved=0` 與逐筆理由，沒有任何東西被寫入，且分兩種回應格式的成本更高
# ——那會讓前端對同一支端點維護兩套解析。

_MODULE = "ET"
#: `spec.md` §稽核來源功能碼：「`ET-APPROVAL` — 線下核可通過 / 不通過 / 撤銷（US16）」。
#: 本 issue 是這個碼的第一個使用者。
_FUNC_NAME = "ET-APPROVAL"


class EtApprovalService:
    """線下考核核可與撤銷。"""

    def __init__(
        self,
        repository: EtApprovalRepository | None = None,
        tracking: EtTrackingRepository | None = None,
        mailer: ApprovalPassedMailer | None = None,
        people: EtNotifyRepository | None = None,
        audit: AuditLogService | None = None,
    ) -> None:
        self._repo = repository or EtApprovalRepository()
        # 重用 tracking 的完課計數——那支已為「刪除項目讓進度變成 200%」與「兩個一對多
        # JOIN 互相灌大計數」各設一道防禦，另寫一份等於把那兩道防禦複製一遍再各自腐化。
        # 方向與 `reports/service.py` 引用同一支相同。
        self._tracking = tracking or EtTrackingRepository()
        self._mailer = mailer or ApprovalPassedMailer()
        self._people = people or EtNotifyRepository()
        self._audit = audit or AuditLogService()

    async def approve(
        self,
        db: AsyncSession,
        course_id: int,
        payload: ApproveReq,
        *,
        actor_id: str,
        actor_roles: frozenset[str],
        operator: OperatorInfo,
    ) -> ApproveResult:
        """核可一位或多位學員（`FR-ET-US16-04` / `-05`）。

        單筆即 `user_ids` 長度為 1——**與批次共用同一條路徑**，否則「跳過」會有兩種回應
        格式，而那正是最容易分岔的地方。

        ## 三種跳過，各自有不同的下一步

        | 理由 | 教師該做什麼 |
        |---|---|
        | `NOT_COMPLETED` | 等他完課（`FR-ET-US16-03`）|
        | `ALREADY_APPROVED` | 先撤銷（須填原因）再重核（SA 裁示 Q2 = A）|
        | `NOT_ENROLLED` | 他已不在這門課，重新邀請 |

        ## 逐筆寄信，不合批

        `FR-ET-US16-05` 明訂「逐一寫入並各自套用通知規則」，且範本內文含 `{USER_NAME}`
        而平台 `send_email` 對整批收件人只渲染一次——合批會讓所有人收到同一個名字的信。

        **只有 PASS 寄信**（`FR-ET-US16-08`）；FAIL 與撤銷不寄。

        Raises:
            AppError: 404 `ET_COURSE_001`；403 `ET_COURSE_002`；
                409 `ET_APPROVAL_001` 未啟用線下核可；409 `ET_APPROVAL_002` 課程已關閉。

        Notes:
            **未完課不拋錯**，回 `skipped[reason=NOT_COMPLETED]`——理由見本檔上方
            「沒有『學員尚未完課』的錯誤碼」的說明。
        """
        course = await self._require_approvable_course(db, course_id, actor_id=actor_id, actor_roles=actor_roles)

        user_ids = list(dict.fromkeys(payload.user_ids))  # 去重但保順序，讓回應可預期
        enrolled = await self._repo.enrolled_user_ids(db, course_id=course_id, user_ids=user_ids)
        counts = await self._tracking.completion_counts_by_student(db, course_id=course_id, user_ids=user_ids)
        existing = await self._repo.rows_by_course(db, course_id=course_id, user_ids=user_ids)

        approver_name = await self._people.user_name(db, operator.user_id) or ""
        approved = 0
        skipped: list[SkippedItem] = []
        # 🔴 稽核**累積到迴圈結束後才寫**，不在迴圈內逐筆呼叫 `log_action`。
        #
        # `AuditLogService.log_action` 的第一步是 `pg_advisory_xact_lock`——**單一固定
        # key 的交易層級鎖，持有到外層交易 commit 為止**（見 `acquire_chain_lock` 的
        # docstring）。在迴圈內呼叫的話，鎖從第一位學員就被取走，然後在持鎖狀態下再跑
        # 完剩下 99 輪的 UPDATE / INSERT / 寄信。
        #
        # 那把鎖是**全平台共用**的：期間所有寫稽核的動作都會排隊，其中包含 `DP-AUTH`
        # 的登入成功 / 失敗。也就是一位教師跑大批次時全站登入會卡住，而且不需要惡意
        # ——一個 100 人的班加一次不耐煩的重複點擊就會發生。
        #
        # 移出迴圈後，持鎖窗從「整批處理 + 逐筆寄信」縮成「N 次稽核寫入 + commit」。
        # 交易語意不變：仍與核可寫入同一個交易，一起成功或一起回滾。
        pending_audits: list[dict] = []

        for user_id in user_ids:
            if user_id not in enrolled:
                skipped.append(SkippedItem(user_id=user_id, reason="NOT_ENROLLED"))
                continue
            done, total = counts.get(user_id, (0, 0))
            if not is_course_completed(done=done, total=total):
                skipped.append(SkippedItem(user_id=user_id, reason="NOT_COMPLETED"))
                continue

            before = existing.get(user_id)
            # 🔴 `is_active_approval` 的 `is_revoked` 那半段不可省：省了會把「已撤銷」
            # 也算成有效紀錄，於是 `FR-ET-US16-06` 的「撤銷後可重新核可」整條路徑會
            # 靜默死掉——教師按下通過，系統回「已跳過」，而那位學員顯示「待核可」。
            if before is not None and is_active_approval(result=before.result, is_revoked=before.is_revoked):
                skipped.append(SkippedItem(user_id=user_id, reason="ALREADY_APPROVED"))
                continue

            written = await self._write_approval(
                db, course_id=course_id, user_id=user_id, payload=payload, operator=operator
            )
            if not written:
                # 條件式寫入雙雙落空＝另一位教師在本交易讀取之後搶先寫入。如實回報，
                # 不重試——重試等於覆寫他剛寫下的結果，而那正是條件式寫入要防的事。
                skipped.append(SkippedItem(user_id=user_id, reason="ALREADY_APPROVED"))
                continue

            after = await self._repo.get_one(db, course_id=course_id, user_id=user_id)
            pending_audits.append(
                {
                    "action_type": "UPDATE" if before is not None else "CREATE",
                    "target_id": f"{course_id}:{user_id}",
                    # `before` 已是 Pydantic 副本（`rows_by_course` 回的是 `ApprovalRow`），
                    # 不會被後續的 ORM update 就地改掉——`revoke()` 踩過那個坑。
                    "before_value": before.model_dump(mode="json") if before is not None else None,
                    "after_value": {"result": payload.result, "version": after.version if after else None},
                }
            )
            approved += 1

            if payload.result == APPROVAL_PASS and after is not None:
                await self._mailer.send_approval_passed(
                    db,
                    course=course,
                    approved_by_name=approver_name,
                    approved_at=after.approved_at,
                    user_id=user_id,
                )

        source_ip = get_client_ip()
        for entry in pending_audits:
            await self._audit.log_action(
                db,
                module=_MODULE,
                func_name=_FUNC_NAME,
                result="SUCCESS",
                operator_id=operator.user_id,
                description="線下核可",
                source_ip=source_ip,
                **entry,
            )

        return ApproveResult(approved=approved, skipped=skipped)

    async def revoke(
        self,
        db: AsyncSession,
        course_id: int,
        user_id: str,
        payload: RevokeReq,
        *,
        actor_id: str,
        actor_roles: frozenset[str],
        operator: OperatorInfo,
    ) -> None:
        """撤銷核可（`FR-ET-US16-06`）——**原因必填**，撤銷後綜合狀態回「待核可」。

        **不寄信**（`FR-ET-US16-08`）：學員不該收到一封「你的核可被撤銷了」的自動信，
        那需要教師當面說明，而 spec 明訂只有 PASS 寄信。

        ## 順序：原因檢核在擁有權之後

        反過來會讓他人課程的請求以「請填寫撤銷原因」vs 403 的差異洩漏「該課程存在且
        該學員有核可紀錄」。`ET_APPROVAL` 沒有可猜的識別碼，但 `(course_id, user_id)`
        兩者都是可列舉的。

        Raises:
            AppError: 404 `ET_COURSE_001` / 403 `ET_COURSE_002`；
                409 `ET_APPROVAL_001` 未啟用線下核可 / `ET_APPROVAL_002` 課程已關閉；
                422 `ET_APPROVAL_005` 原因未填；404 `ET_APPROVAL_003` 查無核可紀錄；
                409 `ET_APPROVAL_004` 版本不符或已被撤銷。
        """
        await self._require_approvable_course(db, course_id, actor_id=actor_id, actor_roles=actor_roles)
        reason = ensure_revoke_reason(payload.reason)

        current = await self._repo.get_one(db, course_id=course_id, user_id=user_id)
        # 查無列 → 404；查得到但已撤銷 → 交給條件式 UPDATE 回 409（`ET-MSG-ET03-308`
        # 「已被其他人變更，請重新整理」正是這個情境的文案）。兩者分流，因為前者是
        # 「這個人從來沒被核可過」、後者是「你看到的畫面過期了」。
        if current is None:
            raise _APPROVAL_NOT_FOUND

        # 🔴 **必須在 UPDATE 之前就轉成脫離的副本**。`mark_revoked` 走的是 ORM-enabled
        # `update()`，SQLAlchemy 會同步 session 內的實體——`current` 那個物件會被就地
        # 改成撤銷後的值。留著它到 UPDATE 之後才 dump，稽核的 before 會等於 after，
        # 而那正是本表唯一能回答「上一次是什麼結果」的地方（本表 update 覆寫、不留歷程）。
        before = ApprovalRow.model_validate(current)

        ok = await self._repo.mark_revoked(
            db, course_id=course_id, user_id=user_id, version=payload.version, reason=reason, operator=operator
        )
        if not ok:
            raise _VERSION_CONFLICT

        after = await self._repo.get_one(db, course_id=course_id, user_id=user_id)
        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME,
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=operator.user_id,
            target_id=f"{course_id}:{user_id}",
            # 原因**不寫進 description**：那是自由文字，寫進來就把 log injection 的面
            # 打開了（`sti-error-codes` §安全）。原因本身存在 `ET_APPROVAL.REVOKE_REASON`，
            # 由 target_id 對得回來。
            description="撤銷線下核可",
            before_value=before.model_dump(mode="json"),
            after_value={"is_revoked": True, "version": after.version if after else None},
            source_ip=get_client_ip(),
        )

    async def _write_approval(
        self,
        db: AsyncSession,
        *,
        course_id: int,
        user_id: str,
        payload: ApproveReq,
        operator: OperatorInfo,
    ) -> bool:
        """先試重核、再試新建——兩者皆為條件式，都落空即「已有未撤銷紀錄」。

        Returns:
            True 表示本次確實寫入了一列。

        ## 為何是「先 UPDATE 再 INSERT」而不是先查後寫

        兩位教師同時對同一位學員按「通過」，先查後寫會讓第二個 INSERT 撞
        `UQ_ET_APPROVAL_COURSE_USER` 變成 500。條件式的兩步各自原子，第二位安靜地
        拿到 False，呼叫端如實回報「已跳過」。

        順序不可對調：先 INSERT 的話，撤銷後重核會撞唯一鍵而永遠走不到 UPDATE。
        """
        reapproved = await self._repo.reapprove(
            db,
            course_id=course_id,
            user_id=user_id,
            result=payload.result,
            result_note=payload.result_note,
            operator=operator,
        )
        if reapproved:
            return True
        return await self._repo.insert_approval(
            db,
            course_id=course_id,
            user_id=user_id,
            result=payload.result,
            result_note=payload.result_note,
            operator=operator,
        )

    async def _require_approvable_course(
        self, db: AsyncSession, course_id: int, *, actor_id: str, actor_roles: frozenset[str]
    ) -> EtCourse:
        """課程存在、操作者有權、已啟用線下核可、且未關閉。

        ## 關閉判定用 `is_effectively_closed`，不只看 `STATUS`

        ET-16 的 SCHET002 執行前，**閱課期間已過的課程 `STATUS` 仍是 `PUBLISHED`**。
        只看 `STATUS` 會讓教師在一門對學員已經關閉的課程上繼續核可。比照 ET-9 / ET-12。

        ## 撤銷也受 `REQUIRE_APPROVAL` 管

        教師若把「需線下核可」關掉，ET03 的整個核可欄會消失，此時不該還能從 API 撤銷
        ——畫面上看不到的東西不該能操作。重新勾選即恢復，既有核可列不受影響。
        """
        course = await self._tracking.get_course(db, course_id)
        if course is None:
            raise _NOT_FOUND
        ensure_owner_or_admin(owner_id=course.owner_id, actor_id=actor_id, actor_roles=actor_roles)
        if not course.require_approval:
            raise _NOT_REQUIRED
        if is_effectively_closed(status=course.status, open_end_at=course.open_end_at, now=utcnow()):
            raise _COURSE_CLOSED
        return course


__all__ = ["EtApprovalService"]
