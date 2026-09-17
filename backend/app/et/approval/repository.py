"""線下核可之資料存取（US16 / #352）。

## 🔴 兩條寫入路徑的防護**刻意不對稱**

**核可**（可批次、非破壞性）

- 防護：條件式 `UPDATE ... WHERE IS_REVOKED = true`，落空再
  `INSERT ... ON CONFLICT DO NOTHING`
- 衝突表現：**跳過**（`ALREADY_APPROVED`），不報錯

**撤銷**（單筆、破壞性）

- 防護：`WHERE VERSION = :version AND IS_REVOKED = false`
- 衝突表現：409 `ET_APPROVAL_004`

核可不收 `version`，是因為批次的對象多半是「待核可」的學員——他們根本還沒有列、沒有
版本號可帶。要求逐人給版本號會讓批次端點無法使用。

`FR-ET-US16-11`「寫入 MUST 以 VERSION 樂觀鎖檢核並防並發覆寫」的**防並發覆寫**由每一條
寫入路徑的 `WHERE` 保證（沒有任何一條會蓋掉它沒檢查過的狀態）；**VERSION 檢核**落在
操作者確實「看著某個狀態才動手」的那一條，也就是撤銷——那是唯一會把既有核可結果作廢
的動作，也是唯一該讓他重新整理再確認一次的動作。

## 條件一律寫在 `WHERE` 裡，不可先查後改

比照同模組 `invitation/repository.mark_revoked` 與 `consume_pending` 的裁定。
PostgreSQL 在 READ COMMITTED 下，被鎖的列釋放後會**重新求值 `WHERE`**
（EvalPlanQual），所以條件放在 `WHERE` 裡才擋得住交錯；先在 Python 判斷再發出不帶
條件的 `UPDATE` 會是 lost update。

本表的具體後果：教師 A 正在撤銷、教師 B 同時重核，先查後改會讓其中一方的寫入被靜默
蓋掉，而**被蓋掉的那次結果只存在 `DP_AUDIT_LOG`**（本表因唯一鍵而 update 覆寫），
畫面上不會有任何訊號。
"""

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.approval.models import EtApproval
from app.et.approval.schemas import ApprovalRow
from app.et.progress.models import EtEnrollment


class EtApprovalRepository:
    """`ET_APPROVAL` 之查詢與原子寫入。"""

    async def rows_by_course(self, db: AsyncSession, *, course_id: int, user_ids: list[str]) -> dict[str, ApprovalRow]:
        """`{user_id: ApprovalRow}`——**一次查回整頁**，不逐筆。

        供 `tracking` 把核可狀態併進學員清單。回 dict 而非 list：呼叫端是逐列組裝，
        用 `.get(user_id)` 取才不必自己建索引。

        ⚠️ 本查詢**絕不可**併進 `tracking.completion_counts_by_student` 的 `GROUP BY`
        ——那裡已為「兩個一對多 JOIN 互相灌大計數」設了兩道防禦，核可是第三個一對多
        關聯。另查一次、在 service 層合併（同 ET-9 對平均成績的處理）。
        """
        if not user_ids:
            return {}
        rows = await db.scalars(
            select(EtApproval).where(
                EtApproval.course_id == course_id,
                EtApproval.user_id.in_(user_ids),
                EtApproval.deleted == 0,
            )
        )
        return {row.user_id: ApprovalRow.model_validate(row) for row in rows.all()}

    async def enrolled_user_ids(self, db: AsyncSession, *, course_id: int, user_ids: list[str]) -> set[str]:
        """這批人之中**仍在籍**（未被移除）者。

        ## 為何核可必須自己查一次在籍

        `tracking.completion_counts_by_student` 數的是 `ET_PROGRESS` 的列，**完全不看
        `ET_ENROLLMENT`**——而移除學員走 `IS_REMOVED`、學習歷史刻意保留下來
        （`progress/models.py` 明載「`DELETED` 與 `IS_REMOVED` 是兩件事」）。

        所以一位「曾經完課、之後被教師移除」的學員，完課判定 `done >= total` 仍然成立。
        少了這道閘，核可會替一個不在班上的人建立 `ET_APPROVAL` 列，而他在 US17 核可
        查詢裡查得到自己「已通過」一門早就被移出的課。

        正常 UI 走不到——ET03 的清單本來就不列已移除者。這道閘擋的是直接打 API 與
        「教師開著頁面，另一位教師把人移除」的競態。
        """
        if not user_ids:
            return set()
        rows = await db.scalars(
            select(EtEnrollment.user_id).where(
                EtEnrollment.course_id == course_id,
                EtEnrollment.user_id.in_(user_ids),
                EtEnrollment.is_removed.is_(False),
                EtEnrollment.deleted == 0,
            )
        )
        return set(rows.all())

    async def get_one(self, db: AsyncSession, *, course_id: int, user_id: str) -> EtApproval | None:
        """取單一學員於該課程的核可列（0～1 筆）。

        用途有二：撤銷前取現況（`ET_APPROVAL_003` 判定與稽核的 before 值）、核可後取
        結果回傳。**不作為寫入的守門**——守門一律在 `WHERE` 裡。
        """
        return await db.scalar(
            select(EtApproval).where(
                EtApproval.course_id == course_id,
                EtApproval.user_id == user_id,
                EtApproval.deleted == 0,
            )
        )

    async def reapprove(
        self,
        db: AsyncSession,
        *,
        course_id: int,
        user_id: str,
        result: str,
        result_note: str | None,
        operator: OperatorInfo,
    ) -> bool:
        """撤銷後重新核可——**只有該列目前為已撤銷才成功**（`FR-ET-US16-06`）。

        Returns:
            True 表示本次重核成功；False 表示查無該列**或**該列目前並非已撤銷
            （呼叫端據此改走 INSERT，再不成才是「已有未撤銷紀錄」）。

        🔴 **必須清空 `REVOKE_REASON` / `REVOKED_BY` / `REVOKED_AT`**。不清的話畫面
        上會出現「已通過」卻帶著撤銷原因的列，而那筆撤銷早已被本次重核推翻；更糟的是
        下一次撤銷若失敗，畫面會顯示一個來自更早之前的舊原因。
        """
        now = utcnow()
        outcome = await db.execute(
            update(EtApproval)
            .where(
                EtApproval.course_id == course_id,
                EtApproval.user_id == user_id,
                EtApproval.is_revoked.is_(True),
                EtApproval.deleted == 0,
            )
            .values(
                result=result,
                result_note=result_note,
                is_revoked=False,
                revoke_reason=None,
                revoked_by=None,
                revoked_at=None,
                approved_by=operator.user_id,
                approved_at=now,
                version=EtApproval.version + 1,
                updated_user=operator.user_id,
                updated_date=now,
            )
        )
        await db.flush()
        return (outcome.rowcount or 0) > 0

    async def insert_approval(
        self,
        db: AsyncSession,
        *,
        course_id: int,
        user_id: str,
        result: str,
        result_note: str | None,
        operator: OperatorInfo,
    ) -> bool:
        """首次核可——`ON CONFLICT DO NOTHING`，撞唯一鍵即視為已有紀錄。

        Returns:
            True 表示本次新建成功；False 表示 `(COURSE_ID, USER_ID)` 已存在。

        ## 為何用 `ON CONFLICT DO NOTHING` 而不是先查再 INSERT

        先查再 INSERT 之間有視窗：兩位教師同時對同一位學員按「通過」，兩邊都查到
        「沒有列」，第二個 INSERT 會撞 `UQ_ET_APPROVAL_COURSE_USER` 而變成 500，而
        教師看到的是一個指向資料庫約束的錯誤訊息。交給 DB 判定則第二筆安靜地回
        False，呼叫端如實回報「已有核可紀錄，已跳過」。
        """
        now = utcnow()
        outcome = await db.execute(
            pg_insert(EtApproval)
            .values(
                COURSE_ID=course_id,
                USER_ID=user_id,
                RESULT=result,
                RESULT_NOTE=result_note,
                IS_REVOKED=False,
                APPROVED_BY=operator.user_id,
                APPROVED_AT=now,
                VERSION=1,
                CREATED_USER=operator.user_id,
                CREATED_DATE=now,
                DELETED=0,
            )
            .on_conflict_do_nothing(constraint="UQ_ET_APPROVAL_COURSE_USER")
        )
        await db.flush()
        return (outcome.rowcount or 0) > 0

    async def mark_revoked(
        self,
        db: AsyncSession,
        *,
        course_id: int,
        user_id: str,
        version: int,
        reason: str,
        operator: OperatorInfo,
    ) -> bool:
        """撤銷核可——**版本相符且目前未撤銷才成功**（`FR-ET-US16-06` / `-11`）。

        Returns:
            True 表示本次撤銷完成；False 表示版本不符或該列已被撤銷，呼叫端回
            409 `ET_APPROVAL_004`（`ET-MSG-ET03-308`「已被其他人變更，請重新整理」）。

        `IS_REVOKED = false` 那半段不只是樂觀鎖的補強：少了它，兩次帶同一個版本號的
        撤銷請求中第二次會**覆寫第一次的 `REVOKE_REASON` 與 `REVOKED_BY`**——第一位
        教師填的原因與他的署名就這樣被換掉，而兩次的 `VERSION` 都對得上。
        """
        now = utcnow()
        outcome = await db.execute(
            update(EtApproval)
            .where(
                EtApproval.course_id == course_id,
                EtApproval.user_id == user_id,
                EtApproval.version == version,
                EtApproval.is_revoked.is_(False),
                EtApproval.deleted == 0,
            )
            .values(
                is_revoked=True,
                revoke_reason=reason,
                revoked_by=operator.user_id,
                revoked_at=now,
                version=EtApproval.version + 1,
                updated_user=operator.user_id,
                updated_date=now,
            )
        )
        await db.flush()
        return (outcome.rowcount or 0) > 0
