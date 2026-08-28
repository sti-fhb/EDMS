"""ET02 課程發布 Service（US3 / #204）。

發布是本模組唯一**有外部後果**的動作：通過檢核即產生邀請碼並（於 `ET-8`）觸發標籤
自動邀請、對所有符合標籤的學員寄信（FR-ET-US3-12）。檢核放過一門空課程，代價是
全體學員收到通知去看一門沒有內容的課——故 `publish()` **必定**重跑檢核，不因前端
已呼叫過 `check()` 而略過。

## 本 issue 只做到「狀態變更 + 邀請碼產生」

標籤自動邀請與寄通知信屬 `ET-8`（`issues.md` 編號）。此處刻意留下接點但不實作——
硬塞一套臨時寄信邏輯，等 `ET-8` 真的做時會與它自己鋪的範本 / 寄送路徑打架。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.common.dm_client import get_dm_document_client
from app.et.common.invitation_code import generate_invitation_code
from app.et.constants import COURSE_DRAFT, COURSE_PUBLISHED
from app.et.course.publish_repository import EtPublishRepository
from app.et.course.publish_rules import PublishBlocker, evaluate_publish
from app.et.course.repository import EtCourseRepository
from app.et.course.rules import ensure_owner
from app.et.course.schemas import PublishBlockerRow, PublishCheckResult, PublishResult
from app.services import AuditLogService, ParamService

_MODULE = "ET"
_FUNC_NAME = "ET-COURSE"

#: 邀請碼長度之參數代碼（`data-model.md` §DP_PARAM）。單值參數，明細碼固定 `VALUE`。
_CODE_LENGTH_PARAM = "ET_INVITATION_CODE_LENGTH"
_DEFAULT_CODE_LENGTH = 8

_NOT_FOUND = AppError(status_code=404, detail="查無此課程", error_code="ET_COURSE_001")


class EtPublishService:
    """課程發布檢核與狀態變更。"""

    def __init__(
        self,
        courses: EtCourseRepository | None = None,
        publish_repo: EtPublishRepository | None = None,
        params: ParamService | None = None,
        audit: AuditLogService | None = None,
    ) -> None:
        self._courses = courses or EtCourseRepository()
        self._publish = publish_repo or EtPublishRepository()
        self._params = params or ParamService()
        self._audit = audit or AuditLogService()

    async def check(self, db: AsyncSession, course_id: int, *, actor_id: str) -> PublishCheckResult:
        """發布預檢：回傳缺漏清單，**不改變任何狀態**。

        讓前端能在按下發布之前就把缺漏標示出來（比照 #203 的逐欄回饋）。
        """
        course = await self._require_owned(db, course_id, actor_id)
        blockers = await self._evaluate(db, course)
        return PublishCheckResult(
            can_publish=not blockers,
            blockers=[PublishBlockerRow(code=b.code, message=b.message, target_id=b.target_id) for b in blockers],
        )

    async def publish(self, db: AsyncSession, course_id: int, *, operator: OperatorInfo) -> PublishResult:
        """發布課程：檢核 → 狀態變更 → 寫入首次發布時間 → 產生邀請碼。

        Raises:
            AppError: 409 `ET_PUBLISH_002` 課程非草稿狀態；
                422 `ET_PUBLISH_001` 檢核未通過（body 另帶 `blockers` 清單）。
        """
        course = await self._require_owned(db, course_id, operator.user_id)
        if course.status != COURSE_DRAFT:
            # 已發布課程的後續編輯**即時生效、不需重新發布**（AC 28），故這裡不是
            # 「再發布一次」的入口。關閉 / 再開課屬 `ET-11`。
            raise AppError(status_code=409, detail="課程狀態不允許發布", error_code="ET_PUBLISH_002")

        blockers = await self._evaluate(db, course)
        if blockers:
            raise AppError(
                status_code=422,
                detail="發布條件未滿足",
                error_code="ET_PUBLISH_001",
                extra={
                    "blockers": [{"code": b.code, "message": b.message, "target_id": b.target_id} for b in blockers]
                },
            )

        code = await self._generate_code(db)
        rowcount = await self._courses.mark_published(
            db, course_id, course.version, invitation_code=code, published_at=utcnow(), operator=operator
        )
        if not rowcount:
            # 版本在檢核與寫入之間被改動——此時整份檢核結果都已過時，回 409 讓教師
            # 重新載入再發一次，而不是用舊結果硬寫。
            raise AppError(
                status_code=409,
                detail="資料已被其他使用者修改，請重新載入後再試",
                error_code="ET_LOCK_001",
            )
        await self._log(db, operator.user_id, course_id, "發布課程")

        # 標籤自動邀請與寄通知信屬 `ET-8`（FR-ET-US3-12 後半）——本 issue 只到這裡。
        return PublishResult(
            course_id=course_id, status=COURSE_PUBLISHED, invitation_code=code, version=course.version + 1
        )

    # ── 內部 ────────────────────────────────────────────────────────────────

    async def _evaluate(self, db: AsyncSession, course) -> tuple[PublishBlocker, ...]:
        """組快照 → 問 DM 廢止狀態 → 交給純函式判斷。"""
        snapshot = await self._publish.snapshot(db, course)
        return evaluate_publish(snapshot, obsolete_doc_ids=await self._obsolete_doc_ids(db, snapshot.doc_ids))

    async def _obsolete_doc_ids(self, db: AsyncSession, doc_ids: frozenset[str]) -> frozenset[str]:
        """向 DM 逐一問廢止狀態（經 `app/services` 唯一跨模組出口）。

        **取不到的文件不列入廢止**（DM 端以 `AppError` 表達查無 / 無發布版）：DM 沒有
        刪除文件的操作，已發布文件只有「編輯上傳新版本」與「廢止」兩種動作，且教師
        能選到的必然是已發布文件——因此「取不到」是正常操作到不了的狀態
        （#204 SA Q2 撤回時已核對）。這裡不讓例外冒上去只是防禦：一份查詢失敗的引用
        不該讓整個發布流程炸掉。
        """
        if not doc_ids:
            return frozenset()
        client = get_dm_document_client()
        obsolete: set[str] = set()
        for doc_id in sorted(doc_ids):
            try:
                current = await client.get_current_by_doc_id(db, doc_id)
            except AppError:
                continue
            if current.obsolete:
                obsolete.add(doc_id)
        return frozenset(obsolete)

    async def _generate_code(self, db: AsyncSession) -> str:
        """產生全域唯一之邀請碼。

        `exists` 須為**同步** callable（`generate_invitation_code` 之約束），故先把
        既有邀請碼一次撈成集合再包成 lambda——在其中等待非同步 I/O 會與既有事件迴圈
        衝突。

        長度取自 `DP_PARAM.ET_INVITATION_CODE_LENGTH`；> 8 時 `generate_invitation_code`
        **fail-fast 不得靜默截斷**（欄位為 `VARCHAR(8)`，截斷會破壞唯一性假設並產生
        難以追查的碰撞）。
        """
        length = await self._params.get_int_param(db, _CODE_LENGTH_PARAM, "VALUE", _DEFAULT_CODE_LENGTH)
        used = await self._courses.list_invitation_codes(db)
        return generate_invitation_code(length=length, exists=lambda code: code in used)

    async def _require_owned(self, db: AsyncSession, course_id: int, actor_id: str):
        course = await self._courses.get(db, course_id)
        if course is None:
            raise _NOT_FOUND
        ensure_owner(owner_id=course.owner_id, actor_id=actor_id)
        return course

    async def _log(self, db: AsyncSession, operator_id: str, course_id: int, description: str) -> None:
        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME,
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=operator_id,
            target_id=str(course_id),
            description=description,
        )
