"""管理者代為轉讓課程擁有者（ET-13 / US1 補強 / #303）。

`ET_COURSE.OWNER_ID` 於建立當下記錄、**本欄位永久不可變更**（`data-model` §ET_COURSE
第 7 欄）。`spec.md:177` §擁有權判定明訂唯一例外：

> **例外**：擁有者離職 / 帳號失能時，**管理者可代為轉讓擁有者**至其他教師（破例變更，
> 需寫入 `DP_AUDIT_LOG`（`FUNC_NAME=ET-OWNER`）記錄轉讓人 / 接收人 / 時間 / 原因，
> 並另存 `ET_OWNER_TRANSFER` 業務紀錄）

## 🔴 本 service 刻意**不呼叫 `ensure_owner`**

ET 其餘所有課程寫入的形狀都是「先 `_require_owned` → `ensure_owner`」。轉讓在定義上
**由非擁有者執行**——管理者處理的正是別人的課程，擁有權檢核在這裡是反的。

把關因此完全落在 router 的 `require_et_roles(ET_ADMIN)` 那一道 dependency 上。
漏掉它的後果不是「少一層防護」，而是**任何教師都能搬走任何人的課程**，且擁有權檢核
擋不住他（它已被刻意移除）。`tests/integration/et/test_et_owner_transfer.py::TestAuthorization`
用學員、一般教師、以及**擁有者本人**三種身分釘住這道閘。

> #288 的 Security Review 剛發現 `PUT` / `DELETE /courses/{id}` 漏掉 `require_et_roles`
> 而沒有任何測試變紅（測試全用教師帳號跑），已開 #301。此處的負向測試就是為了不重演。

## 為何不檢核「原擁有者是否已離職 / 帳號失能」

#303 SA Q2 裁示 A。`spec.md:177` 的「離職 / 帳號失能時」是這個例外**存在的動機**，不是
後端必須檢核的前提。強制檢核會擋掉轉調、留職停薪代管、部門重組等合理情境，而這些都不
會讓帳號變成非 `ACTIVE`。控制手段是**必填轉讓原因** + 雙寫稽核，且轉讓可逆。

## 雙寫必須在同一交易

`ET_COURSE.OWNER_ID` 的 UPDATE、`ET_OWNER_TRANSFER` 的 INSERT、`DP_AUDIT_LOG` 三者
任一失敗即全部回滾。分開提交會出現「擁有者變了但查不到是誰轉的」——而那正是這張表
存在的理由。
"""

from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.dp.users.models import DpUser  # 唯讀 join（報表/查詢例外，已列於 et/spec.md §外模組 table 引用清單）
from app.et.common.optimistic_lock import ensure_version_matched
from app.et.constants import ROLE_TEACHER
from app.et.course.repository import EtCourseRepository
from app.et.course.rules import ensure_transferable
from app.et.course.schemas import TeacherOption, TransferOwnerReq, TransferOwnerResult
from app.et.invitation.models import EtOwnerTransfer
from app.et.roles.models import EtUserRole
from app.services import AuditLogService

_MODULE: Final = "ET"
_FUNC_NAME: Final = "ET-OWNER"

_NOT_FOUND = AppError(status_code=404, detail="查無此課程", error_code="ET_COURSE_001")
_NOT_TEACHER = AppError(status_code=422, detail="接收者須具教師角色", error_code="ET_OWNER_001")


class EtOwnerTransferService:
    """課程擁有者轉讓。"""

    def __init__(self, courses: EtCourseRepository | None = None, audit: AuditLogService | None = None) -> None:
        self._courses = courses or EtCourseRepository()
        self._audit = audit or AuditLogService()

    async def transfer(
        self, db: AsyncSession, course_id: int, req: TransferOwnerReq, *, operator: OperatorInfo
    ) -> TransferOwnerResult:
        """把課程擁有者改為 `req.to_owner_id`，並寫入兩份紀錄。

        判斷順序：課程存在 → 接收者具教師角色 → 接收者非現任擁有者 → 樂觀鎖。
        **擁有權不在其中**（見模組 docstring）。

        Raises:
            AppError: 404 `ET_COURSE_001` 查無課程；422 `ET_OWNER_001` 接收者不具教師
                角色（含查無帳號）；409 `ET_OWNER_002` 接收者已是擁有者；
                409 `ET_LOCK_001` 版本不符。
        """
        course = await self._courses.get(db, course_id)
        if course is None:
            raise _NOT_FOUND

        if not await self._has_teacher_role(db, req.to_owner_id):
            # 查無帳號者自然不具教師角色，走同一個碼——管理者的下一步相同（換一個人），
            # 且不揭露「這個 ID 存不存在」。
            raise _NOT_TEACHER

        ensure_transferable(to_owner_id=req.to_owner_id, current_owner_id=course.owner_id)

        from_owner_id = course.owner_id
        executed_at = utcnow()
        new_version = await self._courses.transfer_owner(
            db, course_id, req.version, to_owner_id=req.to_owner_id, operator=operator
        )
        ensure_version_matched(rowcount=0 if new_version is None else 1, entity="ET_COURSE")

        db.add(
            EtOwnerTransfer(
                course_id=course_id,
                from_owner_id=from_owner_id,
                to_owner_id=req.to_owner_id,
                reason=req.reason,
                executed_by=operator.user_id,
                executed_at=executed_at,
                created_user=operator.user_id,
                created_date=executed_at,
            )
        )
        await db.flush()

        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME,
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=operator.user_id,
            target_id=str(course_id),
            # 靜態文案——`sti-error-codes` 不得嵌入動態值。
            description="轉讓課程擁有者",
            # 轉讓前後擁有者走 `before_value` / `after_value`，**不是** `description`。
            #
            # `spec.md:177` 要求 `DP_AUDIT_LOG` 記錄「轉讓人 / 接收人 / 時間 / 原因」。
            # 只寫 `target_id` + 靜態 description 的話那一列只說得出「某管理者對課程 X 做了
            # 一次 ET-OWNER UPDATE」，連換給誰都查不到，而：
            #
            # 1. `ET_OWNER_TRANSFER` **沒有雜湊鏈**（append-only 僅靠應用層約定），把唯一
            #    的實質證據放在那裡，等於 ET 權限面最高的操作沒有防竄改稽核；
            # 2. 稽核 CSV 匯出的欄位**不含 `description`**（`query_service._CSV_COLUMNS`
            #    只有時間 / 操作者 / 功能 / 類別 / 結果 / 對象 / IP / 異動前值 / 異動後值），
            #    稽核人員匯出時前後值兩欄會是空的。
            #
            # 這兩欄會併入鏈式 `ROW_HASH`、經 `_mask_sensitive` 遮罩後 `json.dumps`，
            # 不存在格式注入面（`dp/users/service.py`、`dm/roles/assign_service.py` 同用法）。
            #
            # ⚠️ `reason` **刻意不放進來**：它是使用者自由文字，留在
            # `ET_OWNER_TRANSFER.REASON` 即可，沒必要塞進 append-only 的雜湊鏈。
            before_value={"owner_id": from_owner_id},
            after_value={"owner_id": req.to_owner_id},
            source_ip=get_client_ip(),
        )
        return TransferOwnerResult(
            course_id=course_id,
            owner_id=req.to_owner_id,
            version=new_version,  # type: ignore[arg-type]
        )

    async def list_teachers(self, db: AsyncSession) -> list[TeacherOption]:
        """可接收課程的教師清單（轉讓視窗的下拉來源）。

        **不分頁**：EDMS 為單一組織，教師人數是數十的量級，與 `list_tag_options` 同一
        判斷（`sti-frontend-modules` 的 client-side 分頁門檻為 200 筆）。

        **排除停用角色**（比照 `_has_teacher_role` 與 `deps.require_et_roles`）：否則
        下拉會列出一個選了必定回 422 `ET_OWNER_001` 的人。

        **不排除現任擁有者**：本端點不知道是為哪一門課開的（它沒有 `course_id`）。
        「已是擁有者」由 `ensure_transferable` 於送出時回 409 `ET_OWNER_002`，前端亦可
        自行以 `course.owner_id` 過濾——兩者都比讓這支端點去理解課程脈絡乾淨。
        """
        rows = await db.execute(
            select(DpUser.user_id, DpUser.user_name)
            .join(EtUserRole, EtUserRole.user_id == DpUser.user_id)
            .where(
                EtUserRole.role == ROLE_TEACHER,
                EtUserRole.is_active.is_(True),
                EtUserRole.deleted == 0,
                DpUser.deleted == 0,
                # 與 `_has_teacher_role` **必須同一組條件**：下拉列得出來、送出卻被擋，
                # 或反過來（下拉沒有、直呼 API 卻成功），兩種都是 bug。
                DpUser.status == "ACTIVE",
            )
            .order_by(DpUser.user_name, DpUser.user_id)
            .distinct()
        )
        return [TeacherOption(user_id=uid, user_name=name) for uid, name in rows]

    async def _has_teacher_role(self, db: AsyncSession, user_id: str) -> bool:
        """接收者是否具**啟用中**的教師角色。

        課程擁有者必須是教師——轉讓給非教師者會產生一門沒有人能編輯的課程（ET02 的
        編輯端點皆要求 `ET_TEACHER` 或 `ET_ADMIN`，而擁有權判定只認 `OWNER_ID`）。

        比對 `IS_ACTIVE`（比照 `deps.require_et_roles`）：被停用的角色不算有，否則可以
        把課程轉給一位實質上已無教師權限的人。

        ## 也要看 `DP_USER` 的帳號狀態

        只查 `ET_USER_ROLE` 不夠：帳號已刪或已停用時，那列角色可能還在。而
        `get_jwt_payload` 每個請求都擋掉 deleted / 非 `ACTIVE` 的帳號，接收者因此
        **永遠登不進來**——結果正是本檢核要避免的那件事：一門沒有人能編輯的課程。
        「離職接手」這個 use case 會一步踏進那個狀態。

        ⚠️ **不納入 `LOCKED_UNTIL`**：帳號鎖定是暫時狀態（連續登入失敗），擋掉它只會
        製造新的誤擋——那位教師過幾分鐘就能登入了。

        > 與 #303 SA Q2 裁示 A 無關：那條談的是**原**擁有者是否須已離職，此處是
        > **接收者**能不能用。兩者是不同的人、不同的問題。
        """
        found = await db.scalar(
            select(EtUserRole.user_id)
            .join(DpUser, DpUser.user_id == EtUserRole.user_id)
            .where(
                EtUserRole.user_id == user_id,
                EtUserRole.role == ROLE_TEACHER,
                EtUserRole.is_active.is_(True),
                EtUserRole.deleted == 0,
                DpUser.deleted == 0,
                DpUser.status == "ACTIVE",
            )
        )
        return found is not None
