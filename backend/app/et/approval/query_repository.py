"""核可查詢之資料存取（US17 / #385）——**唯讀**。

## 為何與 `repository.py` 分檔

那一檔的六個方法全是寫入語意（`reapprove` / `insert_approval` / `mark_revoked`），
而本檔是跨三張表的查詢。混在一起會讓那一檔的職責變成「核可的所有事」，且日後改查詢
時得在一堆 `ON CONFLICT` 之間找路。

## `paginate()` 只取第一個欄位

`core/pagination.py:111` 是 `result.scalars().all()`——**JOIN 進來的額外欄位會被丟掉**。
所以分頁語句雖然 JOIN 了 `ET_COURSE`（範圍判定 + 課程名）與 `DP_USER`（姓名過濾），
`select()` 裡仍只放 `EtApproval`；其餘顯示用欄位在拿到該頁之後另以批次查詢補齊。

這與 `tracking/repository.py:182` 的既有作法一致（分頁主表、再查姓名），也順帶避開
「兩個一對多 JOIN 會灌大計數」那個坑——此處三個關聯都是多對一、不會膨脹，但分開查
之後連日後有人加上一對多 JOIN 都不會影響分頁數字。
"""

from typing import NamedTuple

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.like_escape import LIKE_ESCAPE_CHAR
from app.core.like_escape import contains as like_contains
from app.dp.users.models import DpUser  # 唯讀 join（報表/查詢例外，已列於 et/spec.md §外模組 table 引用清單）
from app.et.approval.models import EtApproval
from app.et.constants import APPROVAL_PASS
from app.et.course.models import EtCourse


class CourseBrief(NamedTuple):
    """本頁涉及課程的名稱與擁有者。

    `owner_id` **不是拿來顯示的**——它供 service 判斷「這筆紀錄是不是查詢者自己的課」，
    以決定 `RESULT_NOTE` 要不要遮蔽（SA 裁示 2026-09-21，見 `query_service._enrich`）。
    """

    name: str
    owner_id: str


class EtApprovalQueryRepository:
    """核可紀錄之查詢（教師 / 管理者依姓名查、學員查自己已通過）。"""

    def teacher_query_stmt(
        self,
        *,
        keyword: str | None,
        visible: ColumnElement[bool],
        course_id: int | None = None,
        result: str | None = None,
    ) -> Select:
        """教師 / 管理者依學員**姓名或 Email** 與 / 或**課程**查詢的語句（未套 offset/limit）。

        🔴 **兩邊的比對都必須跳脫 LIKE 萬用字元**：未跳脫時使用者輸入 `%` 會變成「查全部」，
        讓「關鍵字必填」（SA Q2 裁示 A）形同虛設，**而且沒有任何錯誤訊息**。真正在做事的是
        `like_contains()`——它把 `%` / `_` / 反斜線轉成字面。前例見 `course/repository.py:277`。

        ⚠️ **`escape=LIKE_ESCAPE_CHAR` 今天省略不會壞，別誤以為它是那道防線。**
        `core/like_escape.py` 的 `LIKE_ESCAPE_CHAR` 恰好**就是** PostgreSQL 的預設值
        （該檔註解自己寫著「PostgreSQL LIKE 之 ESCAPE 預設即反斜線，此處明確指定」），
        故拿掉它是語意上的 no-op——2026-09-29 以變異檢查實測：兩邊各拿掉一次，34 條全綠。

        ⭐ 明寫它的理由是**日後** `LIKE_ESCAPE_CHAR` 若改成別的字元（例如 `!`），沒寫的
        那一邊會安靜失效。⛔ 但別把「測試綠」讀成「這個參數有在守什麼」——它守的是未來，
        不是現在。本 docstring 的前一版把這件事寫反了（宣稱省略會立刻失效）。

        ⚠️ **`keyword` 與 `course_id` 可以只給一個**（#439），但**不可兩個都不給**——
        那就是 SA Q2 裁示 A 要擋的「留白查全部」。本層不檢核，由
        `query_rules.normalize_search_criteria` 在 service 進來之前擋下；這裡只負責
        「有給就加條件」。⛔ 不要在此補一道「都沒給就回空」的防禦——那會把 422 變成
        一個看起來正常的空清單。

        Args:
            keyword: 學員姓名或 Email 關鍵字，擇一命中即可；`None` 表不以關鍵字篩。
            visible: `query_rules.visible_clause()` 的結果。
            course_id: 選填的課程篩選；`None` 表不篩。非管理者的擁有權已由
                `query_rules.ensure_course_filter_allowed` 在 service 擋下。
            result: 選填的結果篩選（`PASS` / `FAIL`）；`None` 表不篩。

        Returns:
            已套 where / order_by 的 `Select`，**只 select `EtApproval`**（見模組 docstring）。
        """
        stmt = (
            select(EtApproval)
            .join(EtCourse, EtCourse.course_id == EtApproval.course_id)
            .join(DpUser, DpUser.user_id == EtApproval.user_id)
            .where(
                EtApproval.deleted == 0,
                EtCourse.deleted == 0,
                # ⚠️ 此處濾學員側的 `DELETED`，而下方 `user_names()` **刻意不濾**——兩者
                # 方向相反是有意的：這裡決定「誰會出現在查詢結果」，那裡只是把 id 換成
                # 姓名（核可人可能已離職，但那筆核可仍是歷史事實）。
                #
                # 🔴 今天兩邊行為一致只是因為 `DP_USER.DELETED` 從未被任何程式設為 1。
                # 一旦有人啟用該欄位，該學員的**所有核可紀錄會從連管理者的合規查詢裡一起
                # 消失，且無任何訊號**。要改成不濾之前請先確認那是想要的結果。
                DpUser.deleted == 0,
                visible,
            )
            .order_by(EtApproval.approved_at.desc(), EtApproval.approval_id.desc())
        )
        if keyword:
            # 姓名或 Email 擇一命中（#436）——同名同姓時姓名不足以定位，而 Email
            # 是帳號的唯一鍵。
            #
            # 🔴 **`or_` 的每一邊都要各自跳脫**：任一邊漏了，整條 `or_` 就恆真，
            # 於是 `%` 變成「查全部」而**沒有任何錯誤訊息**——「至少給一個條件」
            # （#439，原 SA Q2 裁示 A）也跟著形同虛設。多一個比對欄位就多一個會漏的地方。
            #
            # ⚠️ 用 `if keyword:` 而非 `if keyword is not None:`——空字串必須等同未給。
            # 後者會讓 `%` + `%` 組成 `%%`，命中全部且不報錯。上游已把全空白正規化為
            # `None`，這裡是第二層。
            stmt = stmt.where(
                or_(
                    DpUser.user_name.ilike(like_contains(keyword), escape=LIKE_ESCAPE_CHAR),
                    DpUser.email.ilike(like_contains(keyword), escape=LIKE_ESCAPE_CHAR),
                )
            )
        if course_id is not None:
            stmt = stmt.where(EtApproval.course_id == course_id)
        if result is not None:
            stmt = stmt.where(EtApproval.result == result)
        return stmt

    async def filter_course_options(self, db: AsyncSession, *, owner_id: str | None) -> list[tuple[int, str]]:
        """ET04 課程下拉的選項：**有核可紀錄的**課程（#439）。

        Args:
            owner_id: 限定課程擁有者；`None`（管理者）表不限。

        Returns:
            `(course_id, course_name)` 依課程名稱排序。

        ## 🔴 母體是核可紀錄，不是課程清單

        沿用 ET01 的課程清單會壞在管理者身上：`scope=all` 只給「已發布**且期間未過**」
        （`course/repository.build_list_stmt`），而核可紀錄絕大多數落在**已結束**的課程上
        ——管理者會發現最相關的課全部不在下拉裡，且畫面不會說明任何事。`scope=mine`
        則對管理者毫無意義（他多半沒有自己的課）。

        以 `ET_APPROVAL` 為母體同時解掉三件事：涵蓋已關閉課程、沒有「選了卻查無」的
        死選項、不隨課程總數無限成長。

        ⚠️ **不套 `visible_clause`**。教師側已由 `owner_id` 限成自己的課（比那道條件更嚴），
        管理者側本來就是 `true()`。硬套只會讓「通過且未撤銷」那一側把**他人**課程也拉進
        教師的下拉——而那正是本功能不打算開放的東西。
        """
        stmt = (
            select(EtApproval.course_id, EtCourse.course_name)
            .join(EtCourse, EtCourse.course_id == EtApproval.course_id)
            .where(EtApproval.deleted == 0, EtCourse.deleted == 0)
            .group_by(EtApproval.course_id, EtCourse.course_name)
            .order_by(EtCourse.course_name)
        )
        if owner_id is not None:
            stmt = stmt.where(EtCourse.owner_id == owner_id)
        rows = await db.execute(stmt)
        return [(cid, name) for cid, name in rows]

    def mine_stmt(self, *, user_id: str) -> Select:
        """學員自查：**自己**、`RESULT = PASS`、**未撤銷**（`FR-ET-US17-03`）。

        ⚠️ 三個條件缺一不可。少了 `IS_REVOKED = false`，一筆被撤銷的通過會出現在學員的
        「已通過課程」裡——而那個通過已經被教師推翻了。
        """
        return (
            select(EtApproval)
            .join(EtCourse, EtCourse.course_id == EtApproval.course_id)
            .where(
                EtApproval.user_id == user_id,
                EtApproval.result == APPROVAL_PASS,
                EtApproval.is_revoked.is_(False),
                EtApproval.deleted == 0,
                EtCourse.deleted == 0,
            )
            .order_by(EtApproval.approved_at.desc(), EtApproval.approval_id.desc())
        )

    async def courses(self, db: AsyncSession, course_ids: list[int]) -> dict[int, CourseBrief]:
        """本頁涉及的課程名稱與擁有者。

        `owner_id` 是為了 `RESULT_NOTE` 的遮蔽判定而一併取回——這支查詢本來就要讀
        `ET_COURSE`，多一個欄位不增加往返。

        ## ⚠️ 本方法**不濾 `DELETED`**，而兩個呼叫端餵進來的東西來源不同

        | 呼叫端 | 餵的 `course_ids` | 為何可以不濾 |
        |---|---|---|
        | `_enrich` / `mine` | 分頁結果的課程（語句已含 `EtCourse.deleted == 0`）| 已經篩過了 |
        | `search` 的擁有權判定（#439）| **使用者直接給的 `course_id`，未經任何篩選** | 見下 |

        第二種情形下「已軟刪除的課程」仍會回傳 `owner_id`，於是
        `ensure_course_filter_allowed` 對「自己名下但已刪除的課程」放行。**那不是漏洞**
        ——放行之後 `teacher_query_stmt` 的 `EtCourse.deleted == 0` 仍會把它濾成空結果；
        而他人的已刪除課程照樣 403（`owner_id` 不符），不洩漏存在性。

        ⛔ 不要為了「對稱」就在這裡加 `deleted == 0`：那會讓自己已刪除課程的擁有權判定
        變成 fail-closed 的 403，而使用者看到的是「僅能依您所開設的課程篩選」——一句
        **對他而言是假的**話。正常 UI 也走不到（下拉已濾掉已刪除課程）。
        """
        if not course_ids:
            return {}
        rows = await db.execute(
            select(EtCourse.course_id, EtCourse.course_name, EtCourse.owner_id).where(
                EtCourse.course_id.in_(course_ids)
            )
        )
        return {cid: CourseBrief(name=name, owner_id=owner) for cid, name, owner in rows}

    async def user_names(self, db: AsyncSession, user_ids: list[str]) -> dict[str, str]:
        """本頁涉及的使用者姓名（學員 / 核可人 / 撤銷人共用一次查詢）。

        ⚠️ **不濾 `DELETED`**：核可人可能已離職，但那筆核可仍是歷史事實，姓名要顯示得
        出來。（`DP_USER.DELETED` 在本系統實務上恆為 0，此處是語意宣告而非防禦。）
        """
        if not user_ids:
            return {}
        rows = await db.execute(select(DpUser.user_id, DpUser.user_name).where(DpUser.user_id.in_(user_ids)))
        # ⚠️ 不可寫成 `dict(rows)`——`Result` 本身不是可直接建字典的映射
        # （`TypeError: 'ChunkedIteratorResult' object is not subscriptable`），
        # 要先逐列取出。與上面的 `courses` 保持同一種寫法。
        return {uid: name for uid, name in rows}
