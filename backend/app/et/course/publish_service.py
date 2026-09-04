"""ET02 課程發布 Service（US3 / #204、#247、#273）。

發布是本模組唯一**有外部後果**的動作：通過檢核即產生邀請碼、觸發標籤自動邀請，並對
所有被帶入的學員寄信（FR-ET-US3-12）。檢核放過一門空課程，代價是全體學員收到通知去
看一門沒有內容的課——故 `publish()` **必定**重跑檢核，不因前端已呼叫過 `check()` 而略過。

## 發布的四件事

1. 狀態變更 + 首次發布時間
2. 產生邀請碼
3. **依受訓單位標籤帶入學員**（#247 追加，見下）
4. **對本次被帶入者逐人寄通知信**（#273 追加）

### 標籤帶入與寄信為何分兩次交付

#204 交付時把整個 FR-ET-US3-12 都推給 `ET-8`、只留接點。實測後發現那樣不成立：
課程掛了「護理師」標籤發布出去，具該標籤的學員**不會被帶進課程**，教師只能把 8 碼
邀請碼一個一個發。受訓單位標籤在發布流程裡等於沒有作用，而 `ET-4` 的我的課程對多數
學員永遠是空的——故 #247 先補上帶入本身。

當時未一併寄信，是為了避免臨時寄信邏輯與 `ET-8` 自己鋪的範本 / 寄送路徑打架。#273
落地後兩者收斂於 `app/et/notify/`（範本、params 組法、失敗不回滾皆在該處），本檔只
負責在正確的時點呼叫它。

仍不在本檔的：Email 邀請（另一種 `JOIN_SOURCE`，見 `app/et/invitation/`）、
`ET_INVITATION` 待加入清單（`ET-12`）。
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
from app.et.enrollment.tag_invite import EtTagInviteRepository
from app.et.notify.mailer import CourseInviteMailer
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
        tag_invite: EtTagInviteRepository | None = None,
        invite_mailer: CourseInviteMailer | None = None,
    ) -> None:
        self._courses = courses or EtCourseRepository()
        self._publish = publish_repo or EtPublishRepository()
        self._params = params or ParamService()
        self._audit = audit or AuditLogService()
        self._tag_invite = tag_invite or EtTagInviteRepository()
        self._invite_mailer = invite_mailer or CourseInviteMailer()

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

        # 依受訓單位標籤帶入學員（FR-ET-US3-12 前半，#247 追加）。已在課程中者略過、
        # 已被移除者不會被帶回來（見 `tag_invite` docstring）。
        invited_ids = await self._tag_invite.bulk_enroll_returning(
            db, course_id, await self._tag_invite.target_user_ids(db, course_id), operator=operator
        )
        if invited_ids:
            await self._log(db, operator.user_id, course_id, f"依受訓單位標籤帶入 {len(invited_ids)} 位學員")

        # 寄通知信（FR-ET-US3-12 後半 / FR-ET-US8-03，#273 補上）。**只寄給本次真的被加
        # 進來的人**——重新發布時已在課程中者不該再收到一次「您已被加入」。
        #
        # `invitation_code` 傳新產生的 `code` 而非 `course.invitation_code`：`mark_published`
        # 是一道 UPDATE，手上的 `course` 仍是更新前的快照（邀請碼當時還是 None）。
        #
        # 寄信失敗不回滾加入（AC 3）——由 `EtNotifier` 吞掉 `AppError`，此處不需 try/except。
        await self._invite_mailer.send_course_invite(db, course=course, invitation_code=code, user_ids=invited_ids)

        return PublishResult(
            course_id=course_id,
            status=COURSE_PUBLISHED,
            invitation_code=code,
            version=course.version + 1,
            invited_count=len(invited_ids),
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
