"""核可查詢 Service（US17 / #385）——**唯讀，不寫任何東西**。

## 兩支端點刻意分開，而不是同一支加參數

`GET /approvals`（教師 / 管理者）與 `GET /approvals/mine`（學員）的授權模型、回應欄位
與資料範圍三者都不同。合併成一支之後，「學員誤拿到教師欄位」就只差一個判斷式——而那
個判斷式改壞了不會有任何東西變紅（回應多幾個欄位，前端照樣渲染）。

分開的附帶好處：`/mine` **不收任何 `user_id` 參數**，對象一律取自 token。
`FR-ET-US17-04`「學員竄改參數查他人」因此在介面上就沒有可竄改的參數，而不是靠一道
判斷式擋下。

## SA 裁示（2026-09-21）

- **Q1 = C**：教師（非管理者）依結果分流 ——⚠️ **已於 #548 裁示 1 推翻**：教師 ≡ 管理者，
  全部課程、全部結果。保留下來的是**欄位**維度（`RESULT_NOTE` / `REVOKE_REASON` 仍限
  owner + 管理者），見 `query_rules.can_see_private_notes`
- **Q2 = A**：`keyword` 必填，去空白後為空視為未填（#436 起可為姓名或 Email）
  ——⚠️ **已於 #439 換手段**（改為「至少給一個」＋課程擁有權閘），再於 **#548 裁示 3 / 4
  整組退役**。裁示 A 擋的目的（不可傾印員工名冊）**這次確實被放寬了**，不是換手段：
  留白查詢成為合法操作。🔴 承重轉到**讀取稽核**（裁示 5，見 `_audit_bulk_read`）
  ——從「擋下」改為「留痕」。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PaginatedResult, paginate_rows
from app.core.request_context import get_client_ip
from app.et.approval.query_repository import EtApprovalQueryRepository
from app.et.approval.query_rules import can_see_private_notes, normalize_keyword
from app.et.approval.schemas import (
    ApprovalCourseOption,
    ApprovalQueryRow,
    MyApprovalRow,
    _ApprovalCore,
)
from app.et.roles.authz import is_admin
from app.services import AuditLogService

_MODULE = "ET"
_FUNC_NAME = "ET-APPROVAL"


class EtApprovalQueryService:
    """核可紀錄查詢——教師 / 管理者依姓名查，學員查自己已通過。"""

    def __init__(
        self,
        repository: EtApprovalQueryRepository | None = None,
        audit: AuditLogService | None = None,
    ) -> None:
        self._repo = repository or EtApprovalQueryRepository()
        self._audit = audit or AuditLogService()

    async def search(
        self,
        db: AsyncSession,
        *,
        actor_id: str,
        roles: frozenset[str],
        keyword: str | None,
        course_id: int | None,
        result: str | None,
        revoked: bool | None,
        page: int,
        limit: int,
    ) -> PaginatedResult[ApprovalQueryRow]:
        """教師 / 管理者依學員姓名 / Email 與 / 或課程查詢核可紀錄。

        ## 無任何條件的限制（#548 裁示 3 / 4）

        關鍵字與課程皆可不給；課程篩選不分 owner。原本的兩道閘（422 `ET_APPROVAL_006`、
        403 `ET_APPROVAL_007`）連同裁示 C 的結果分流一起退役——理由見 `query_rules`
        的模組 docstring。

        🔴 **代價是防列舉只剩角色受控**，所以不指名的查詢一律留痕，見下方 `_audit_bulk_read`。

        ⛔ 別把關鍵字讀成一道防線：它從來不是。`approval/router.py` 的模組 docstring
        寫明真正在收斂的是母體限制與角色受控，而母體限制已於本次退役。
        """
        admin = is_admin(roles)
        keyword = normalize_keyword(keyword)
        stmt = self._repo.teacher_query_stmt(
            keyword=keyword,
            revoked=revoked,
            course_id=course_id,
            result=result,
        )
        # ⚠️ `paginate_rows` 而非 `paginate`：#464 起語句是兩側的 `UNION ALL`，結果是多欄
        # Row——`paginate()` 的 `scalars()` 會**靜默只取第一欄**。
        paged = await paginate_rows(db, stmt, page, limit)
        core = [_ApprovalCore.model_validate(dict(row._mapping)) for row in paged["data"]]
        rows = await self._enrich(db, core, actor_id=actor_id, is_admin=admin)
        if keyword is None:
            await self._audit_bulk_read(
                db,
                actor_id=actor_id,
                course_id=course_id,
                result=result,
                revoked=revoked,
                row_count=paged["meta"]["total"],
            )
        return {"data": rows, "meta": paged["meta"]}

    async def _audit_bulk_read(
        self,
        db: AsyncSession,
        *,
        actor_id: str,
        course_id: int | None,
        result: str | None,
        revoked: bool | None,
        row_count: int,
    ) -> None:
        """為「不指名的大量讀取」寫一筆稽核（#548 裁示 5）。

        ## 🔴 只記沒有關鍵字的查詢，不是每一次查詢

        要擋的風險是**整批取回**，而那正好等於不給關鍵字的查詢——給了關鍵字一次只命中
        一個人，且使用者是在輸入框打字（前端有 debounce），頻率高得多。

        ⚠️ 還有一個實務理由：`log_action` 的第一步是 `pg_advisory_xact_lock`，**全平台
        單一固定 key 且持有至外層交易 commit**，持鎖期間所有寫稽核的動作（**包含登入**）
        都會排隊。讓一支高頻讀取端點去取那把鎖不划算。

        ## ⛔ 不記關鍵字、不記姓名、不記任何回傳內容

        關鍵字就是姓名或 Email，而稽核表的保存期比業務資料長——寫進去是把暴露從一處
        搬到另一處，不是補上追蹤（#392 已點明）。記的是**這次撈了多廣**：誰、什麼條件、
        幾筆。要查「撈到了誰」得回頭比對當時的 `ET_APPROVAL`，那是刻意的取捨。

        ⚠️ `row_count` 取 `meta.total` 而非 `len(data)`：後者受分頁上限（100）截斷，
        翻 10 頁會留下 10 筆「100 筆」的紀錄，看不出實際規模。

        📌 `ACTION_TYPE = "QUERY"` 是本 issue 新增的值（migration `c7d2e4f9a8b1`）。
        ⛔ 不可借用 `EXPORT`——那語意是「產生檔案帶走」，借用會污染 DP06 的匯出篩選。
        """
        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME,
            action_type="QUERY",
            result="SUCCESS",
            operator_id=actor_id,
            # ⚠️ 無 target_id：本事件的對象是「一組條件」而非某一列，硬塞會讓
            # DP06 的「目標」欄出現看不懂的值。
            description="核可查詢（未指定學員）",
            after_value={
                "course_id": course_id,
                "result": result,
                "revoked": revoked,
                "row_count": row_count,
                # 記「有沒有給」而非給了什麼——用以辨識這是哪一條路徑，不洩露內容。
                "has_keyword": False,
            },
            source_ip=get_client_ip(),
        )

    async def filter_courses(
        self, db: AsyncSession, *, actor_id: str, roles: frozenset[str]
    ) -> list[ApprovalCourseOption]:
        """ET04 課程下拉的選項——**有核可紀錄的**課程，不分 owner（#439、#548 裁示 4）。

        `ApprovalCourseOption` 的 docstring 說明為何母體是核可紀錄而不是課程清單。

        ↔️ #548 之前非管理者只列自己開設的課，與 `search` 的擁有權閘是一組的。那道閘
        退役後，下拉再限自己的課只會讓「選得到的」少於「查得到的」——出現「這門課查
        得到卻選不到」這種無法解釋的狀態。

        ⚠️ 回傳空清單現在只有一種成因（系統裡還沒有任何核可紀錄），前端的說明文字
        因此不再需要分教師 / 管理者兩版，見 `TeacherApprovalQuery`。

        ⛔ `roles` 參數**刻意保留**：本方法仍是模組內唯一知道「誰在查」的地方，日後
        若要依身分調整母體，簽章不必再動一次呼叫端。
        """
        rows = await self._repo.filter_course_options(db, owner_id=None)
        return [ApprovalCourseOption(course_id=cid, course_name=name) for cid, name in rows]

    async def mine(self, db: AsyncSession, *, actor_id: str, page: int, limit: int) -> PaginatedResult[MyApprovalRow]:
        """學員自查：自己、已通過、未撤銷（`FR-ET-US17-03`）。

        不收 `user_id` 參數——對象恆為 `actor_id`。
        """
        stmt = self._repo.mine_stmt(user_id=actor_id)
        paged = await paginate_rows(db, stmt, page, limit)
        core = [_ApprovalCore.model_validate(dict(row._mapping)) for row in paged["data"]]
        courses = await self._repo.courses(db, [r.course_id for r in core])
        rows = [
            MyApprovalRow(
                course_id=r.course_id,
                course_name=courses[r.course_id].name if r.course_id in courses else "",
                approved_at=r.approved_at,
            )
            for r in core
        ]
        return {"data": rows, "meta": paged["meta"]}

    async def _enrich(
        self, db: AsyncSession, core: list[_ApprovalCore], *, actor_id: str, is_admin: bool
    ) -> list[ApprovalQueryRow]:
        """補上課程名稱與三個人名（學員 / 核可人 / 撤銷人），並遮蔽他人課程的考核評語。

        三種人名共用同一次 `user_names()` 查詢——它們都指向 `DP_USER`，分三次查只是
        多兩趟往返。

        ## 🔴 `RESULT_NOTE` 只對該課程 owner 與管理者顯示（SA 裁示 2026-09-21）

        裁示 C 原本只切了**結果**維度（不通過 / 已撤銷限自己 owner），沒切**欄位**維度。
        但 `ApproveReq.result_note` 明文允許 `PASS` 附備註（上限 1000 字），於是：

        > 教師甲在自己的課給某人 PASS，備註寫「第二次補考才通過，單採操作仍不穩」。
        > 教師乙（與該課程、該學員毫無關係）查該學員 → 完整讀到那段評語。

        裁示 C 的理由自己寫著「不通過與其 `RESULT_NOTE` 是考核評價，不該讓同儕教師隨意
        翻閱」——負面評語只要掛在 PASS 上就整份流出去。這與 `query_rules` 防的「撤銷原因
        從側門漏出」是同一類側門的另一半。

        ⚠️ 遮蔽在**後端**，回傳 `None` 而非交給前端不渲染。
        """
        if not core:
            return []
        courses = await self._repo.courses(db, [r.course_id for r in core])
        # ⚠️ 完課列的 `approved_by` 為 `None`（不需核可的課程沒有核可者），不可放進查詢集合。
        wanted = {r.user_id for r in core} | {r.approved_by for r in core if r.approved_by}
        wanted |= {r.revoked_by for r in core if r.revoked_by}
        people = await self._repo.user_names(db, list(wanted))

        def sees_notes(row: _ApprovalCore) -> bool:
            """這一列的兩個自由文字欄位是否對本查詢者可見。

            ⛔ `result_note` 與 `revoke_reason` **共用這一支**，不得各寫一份——理由見
            `query_rules.can_see_private_notes` 的 docstring。
            """
            course = courses.get(row.course_id)
            return can_see_private_notes(
                course_owner_id=course.owner_id if course is not None else None,
                actor_id=actor_id,
                is_admin=is_admin,
            )

        return [
            ApprovalQueryRow(
                user_id=r.user_id,
                user_name=people.get(r.user_id, ""),
                course_id=r.course_id,
                course_name=courses[r.course_id].name if r.course_id in courses else "",
                result=r.result,
                result_note=r.result_note if sees_notes(r) else None,
                approved_at=r.approved_at,
                # ⚠️ 完課列回 `None` 而非 `""`：空字串會被前端讀成「有核可人但姓名是空的」。
                approved_by_name=people.get(r.approved_by, "") if r.approved_by else None,
                # ⚠️ `is_revoked` / `revoked_by_name` / `revoked_at` **不遮蔽**——遮的只有
                # 原因文字。把撤銷這個事實一起藏起來，教師會把被撤銷的紀錄讀成有效核可，
                # 方向比洩漏原因更糟（#548 裁示 7）。
                is_revoked=r.is_revoked,
                revoke_reason=r.revoke_reason if sees_notes(r) else None,
                revoked_by_name=people.get(r.revoked_by) if r.revoked_by else None,
                revoked_at=r.revoked_at,
            )
            for r in core
        ]
