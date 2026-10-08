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

## #464 起：查詢是兩個來源的聯集

「通過」有兩種成立方式（2026-09-30 裁示，見 #464）：

| 側 | 來源 | 條件 |
|---|---|---|
| **核可側** | `ET_APPROVAL` | 關鍵字 + 課程 + 結果 + 撤銷狀態（#548 起**無任何可見範圍條件**）|
| **完課側** | `ET_ENROLLMENT` × `completed_pairs()` | 不需核可課程 + 全部項目完成 + **沒有核可紀錄** |

因為結果是多欄 Row、不是 ORM 實體，這兩支查詢改由 `paginate_rows()` 分頁
（`paginate()` 的 `scalars()` 會靜默只取第一欄）。

🔴 **完課側要排除已有核可紀錄者**：`REQUIRE_APPROVAL` 發布後仍可切換
（`course/service.update_basic` 無狀態守門）。一門課先需核可、核可了某人、之後切成不需
核可——不排除的話，同一人同一課會出現兩列。處置是**以核可紀錄為準**：教師的明確判斷
（含不通過與撤銷）不該被事後切一個勾選框就靜默覆蓋。
"""

from typing import NamedTuple

from sqlalchemy import (
    BigInteger,
    DateTime,
    Select,
    String,
    and_,
    cast,
    exists,
    false,
    func,
    literal,
    null,
    or_,
    select,
    union_all,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.like_escape import LIKE_ESCAPE_CHAR, escape_like
from app.core.like_escape import contains as like_contains
from app.dp.users.models import DpUser  # 唯讀 join（報表/查詢例外，已列於 et/spec.md §外模組 table 引用清單）
from app.et.approval.models import EtApproval
from app.et.constants import APPROVAL_PASS
from app.et.course.models import EtCourse
from app.et.progress.completion_sql import completed_pairs
from app.et.progress.models import EtEnrollment


class CourseBrief(NamedTuple):
    """本頁涉及課程的名稱與擁有者。

    `owner_id` **不是拿來顯示的**——它供 service 判斷「這筆紀錄是不是查詢者自己的課」，
    以決定 `RESULT_NOTE` 要不要遮蔽（SA 裁示 2026-09-21，見 `query_service._enrich`）。
    """

    name: str
    owner_id: str


def _approval_projection():
    """核可側的投影——與完課側**欄位名、順序、型別**必須逐一對齊（`UNION ALL` 的要求）。"""
    return (
        EtApproval.course_id.label("course_id"),
        EtApproval.user_id.label("user_id"),
        EtApproval.result.label("result"),
        EtApproval.result_note.label("result_note"),
        EtApproval.is_revoked.label("is_revoked"),
        EtApproval.revoke_reason.label("revoke_reason"),
        EtApproval.approved_by.label("approved_by"),
        EtApproval.approved_at.label("approved_at"),
        EtApproval.revoked_by.label("revoked_by"),
        EtApproval.revoked_at.label("revoked_at"),
        EtApproval.approval_id.label("approval_id"),
    )


def _completion_side(*, course_id: int | None = None, user_id: str | None = None) -> Select:
    """完課側：**不需核可**課程中、**全部項目完成**、且**沒有核可紀錄**的 (課程, 學員)。

    ## 三個條件各擋什麼

    | 條件 | 少了它會怎樣 |
    |---|---|
    | `REQUIRE_APPROVAL IS FALSE` | 需核可課程的「完課但未核可」者被列為通過——違反 Q2 裁示 A |
    | `completed_pairs()` | 未完課者被列為通過 |
    | `NOT EXISTS ET_APPROVAL` | 切換過 `REQUIRE_APPROVAL` 的課程，同一人出現兩列；明確的 FAIL 被完課翻成 PASS |

    ⚠️ **不濾在籍（`IS_REMOVED`）**：完課是歷史事實，與已移除者的核可紀錄照列一致
    （`approval/schemas.py` 的 `NOT_ENROLLED` 說明）。寫入端 `stamp_completed_at` 同樣不濾。

    ⚠️ **NULL 欄位一律 `CAST`**：`UNION ALL` 兩側型別要能對齊，而未定型的 NULL 綁定參數
    在 asyncpg 下會撞 `could not determine data type of parameter`。

    Args:
        course_id: 限定課程（下推進 `completed_pairs()`，只聚合那門課）。
        user_id: 限定學員（學員自查用）。
    """
    pairs = completed_pairs(course_id=course_id, user_ids=[user_id] if user_id is not None else None)
    stmt = (
        select(
            EtEnrollment.course_id.label("course_id"),
            EtEnrollment.user_id.label("user_id"),
            # 完課**就是**通過（Q3 裁示：兩種通過不區分）
            cast(literal(APPROVAL_PASS), String).label("result"),
            cast(null(), String).label("result_note"),
            false().label("is_revoked"),
            cast(null(), String).label("revoke_reason"),
            # 不需核可的課程**事實上沒有核可者**——不是遮蔽、也不是忘了填
            cast(null(), String).label("approved_by"),
            # 通過時間＝第一次完課的時間（#464 活化）；活化前已完課的既有資料為 NULL
            EtEnrollment.completed_at.label("approved_at"),
            cast(null(), String).label("revoked_by"),
            cast(null(), DateTime(timezone=True)).label("revoked_at"),
            cast(null(), BigInteger).label("approval_id"),
        )
        .join(pairs, and_(pairs.c.course_id == EtEnrollment.course_id, pairs.c.user_id == EtEnrollment.user_id))
        .join(EtCourse, EtCourse.course_id == EtEnrollment.course_id)
        .join(DpUser, DpUser.user_id == EtEnrollment.user_id)
        .where(
            EtEnrollment.deleted == 0,
            EtCourse.deleted == 0,
            DpUser.deleted == 0,
            EtCourse.require_approval.is_(False),
            ~exists().where(
                EtApproval.course_id == EtEnrollment.course_id,
                EtApproval.user_id == EtEnrollment.user_id,
                EtApproval.deleted == 0,
            ),
        )
    )
    if course_id is not None:
        stmt = stmt.where(EtEnrollment.course_id == course_id)
    if user_id is not None:
        stmt = stmt.where(EtEnrollment.user_id == user_id)
    return stmt


def _ordered(*sides: Select) -> Select:
    """把兩側 `UNION ALL` 後排序。

    🔴 **`NULLS LAST` 不可省**：PostgreSQL 的 `DESC` 預設 **NULLS FIRST**。活化前就已完課
    的既有資料 `COMPLETED_AT` 為 NULL，不明寫的話它們會**全部浮到最上面**——正式機從頭建
    不會有這種資料，但**測試環境會**，而手測就在那裡做。

    ⚠️ 後三個鍵是為了**決定性**：同一時間的多列順序必須穩定，否則翻頁時同一列可能重複或
    被漏掉。`approval_id DESC` 排在 `course_id` 之前，使核可列之間的相對順序與 #464 之前
    （`approved_at DESC, approval_id DESC`）**完全相同**。
    """
    u = union_all(*sides).subquery("training_completion")
    return select(u).order_by(
        u.c.approved_at.desc().nulls_last(),
        u.c.approval_id.desc().nulls_last(),
        u.c.course_id,
        u.c.user_id,
    )


class EtApprovalQueryRepository:
    """核可紀錄之查詢（教師 / 管理者依姓名查、學員查自己已通過）。"""

    def teacher_query_stmt(
        self,
        *,
        keyword: str | None,
        course_id: int | None = None,
        result: str | None = None,
        revoked: bool | None = None,
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
            course_id: 選填的課程篩選；`None` 表不篩。
            result: 選填的結果篩選（`PASS` / `FAIL`）；`None` 表不篩。
            revoked: 選填的撤銷狀態篩選；`None` 表不篩。**與 `result` 正交**
                ——被撤銷的紀錄其 `RESULT` 仍是 `PASS` 或 `FAIL`，見下方該段的 🔴。

        ⚠️ **本語句不再有任何可見範圍條件**（#548 裁示 1）。原本的 `visible` 參數承載
        裁示 C 的結果分流，已隨 `query_rules.visible_clause()` 一併退役；欄位層的遮蔽
        （`RESULT_NOTE` / `REVOKE_REASON`）改由 `query_service._enrich` 在取出後處理
        ——那是**欄位**維度，不影響列的進出，所以不需要進 `WHERE`。

        Returns:
            兩側 `UNION ALL` 後已排序的 `Select`（欄位見 `_approval_projection`），
            供 `paginate_rows()` 使用。⚠️ #464 起**不再**只 select `EtApproval`。
        """
        approval_side = (
            select(*_approval_projection())
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
            )
        )
        completion_side = _completion_side(course_id=course_id)
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
            #
            # 兩側都 JOIN 了 `DpUser`，所以同一個條件套兩次即可——**必須兩側都套**，否則
            # 關鍵字查詢會把另一側的全部列帶出來。
            #
            # 🔴 **Email 只比對 `@` 之前（local part），不比對網域**（#456）
            #
            # `DP_USER.EMAIL` 為 `NOT NULL`，而全體使用者的網域是同一串字。對整個
            # Email 做 contains 比對時，`@`、`.`、`com`、`tw` 這類字串**單獨一個就命中
            # 全體**——一次請求加翻頁即可取走可見範圍內的全部核可／完課紀錄。
            #
            # 判準是「**這個字元能不能識別一個人**」：網域對每個人都一樣，拿它比對的
            # 結果只可能是「全部人」或「沒有人」，對「找某位學員」毫無幫助。把它排除在
            # 比對範圍外**不損失任何正當用途**——contains 語意在 local part 上保留，
            # 教師記得帳號中段（`chiang`）照樣查得到。
            #
            # ⚠️ **這不是安全邊界**，別把它當成防列舉的控制。它擋掉的是「打一個字就
            # 全撈」，擋不住有心人逐字掃。真正在收斂的仍是**母體限制與角色受控**
            # （#392 裁示 C 已接受教師可查全部課程），見 `router` 的模組 docstring。
            #
            # ⛔ 不要為此改用前綴比對（`startswith`）：那會讓「記得帳號中段」的查法失效，
            # 而它擋掉的東西與本寫法相同。
            #
            # ## 第三條：**完整 Email 走精準比對**
            #
            # 只比 local part 會讓「貼上一整串 Email」查不到（`s_lin` 不 contains
            # `s_lin@edms.local`）——那是正當且常見的用法（從別處複製帳號來查）。
            #
            # 補一條**相等**比對即可兩全：相等最多命中一個人，不具列舉價值，所以把網域
            # 放回來是安全的。⚠️ 關鍵在於 **contains 與相等的風險完全不同**——前者的命中
            # 數隨關鍵字變短而暴增，後者恆為 0 或 1。
            #
            # ⛔ 不可改回 `email.ilike(contains(keyword))`「順便涵蓋」這條：那正是本 issue。
            email_local_part = func.split_part(DpUser.email, "@", 1)
            matches = or_(
                DpUser.user_name.ilike(like_contains(keyword), escape=LIKE_ESCAPE_CHAR),
                email_local_part.ilike(like_contains(keyword), escape=LIKE_ESCAPE_CHAR),
                # `ilike` 而非 `==`：Email 大小寫不敏感（既有查詢亦以 ilike 處理）。
                # 模式中不含 `%`，故此處是相等比對而非 contains；跳脫仍要做——否則
                # 關鍵字裡的 `%` / `_` 會變成萬用字元，把這條也變成範圍比對。
                DpUser.email.ilike(escape_like(keyword), escape=LIKE_ESCAPE_CHAR),
            )
            approval_side = approval_side.where(matches)
            completion_side = completion_side.where(matches)
        if course_id is not None:
            approval_side = approval_side.where(EtApproval.course_id == course_id)
        if result is not None:
            approval_side = approval_side.where(EtApproval.result == result)
            # 🔴 完課側沒有 `RESULT` 欄，篩選要**在這一側另外表達**：完課就是通過，
            # 所以「僅通過」全收、「僅不通過」全排除。若把 `RESULT = 'PASS'` 直接套在
            # 聯集上，完課列會被全數濾掉——症狀是「選了僅通過反而少了一半資料」，
            # 而且**不選篩選時完全正常**，很容易被當成偶發。
            if result != APPROVAL_PASS:
                completion_side = completion_side.where(false())
        if revoked is not None:
            # 🔴 `IS_REVOKED` 與 `RESULT` 是**兩個正交的維度**（#548 裁示 6）。
            #
            # 改制前這裡只有上面那段 `RESULT` 條件，於是「僅通過」會列出**已撤銷的通過**
            # ——撤銷只設 `IS_REVOKED`，`RESULT` 仍是 `PASS`。諷刺的是已退役的
            # `visible_clause` docstring 早就警告過同一個陷阱（「『通過』那一側必須同時
            # 要求未撤銷」），但那道警告只套用在可見範圍，沒人把它套到結果篩選。
            approval_side = approval_side.where(EtApproval.is_revoked.is_(revoked))
            # 完課側同樣沒有 `IS_REVOKED` 欄：完課是事實事件，**不存在被撤銷的完課**。
            # 故「僅未撤銷」全收、「僅已撤銷」全排除——與上面 `RESULT` 的處理同一形狀。
            # ⛔ 不可把 `IS_REVOKED = false` 直接套在聯集上，完課列會被全數濾掉。
            if revoked:
                completion_side = completion_side.where(false())
        return _ordered(approval_side, completion_side)

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

        ⚠️ **#548 起 `owner_id` 恆為 `None`**（裁示 4）：下拉列出所有有核可紀錄的課程，
        不分 owner。原本「非管理者僅列自有課程」擋的是「不指名地整批取回他人課程名單」，
        而裁示 3 讓留白查詢本身成為合法操作後，那道限制已無承重對象——留著只會讓同一份
        資料在「用姓名查」與「用課程篩」兩條路上有兩種規則。

        ⛔ 參數本身**保留**：日後若要再收斂，改呼叫端傳值即可，不必重寫查詢。

        ⚠️ **#464 起母體是「核可紀錄 ∪ 完課側」**：只看 `ET_APPROVAL` 的話，不需核可的課程
        **永遠選不到**——而那正是 #464 要納入的那些。完課側沿用 `_completion_side()`，
        與查詢本身是**同一個定義**，下拉列得出的課程就一定查得出東西。
        """
        approved = select(EtApproval.course_id.label("course_id")).where(EtApproval.deleted == 0)
        completed = _completion_side().with_only_columns(EtEnrollment.course_id.label("course_id"))
        source = union_all(approved, completed).subquery("option_source")
        stmt = (
            select(EtCourse.course_id, EtCourse.course_name)
            .where(EtCourse.course_id.in_(select(source.c.course_id)), EtCourse.deleted == 0)
            .order_by(EtCourse.course_name)
        )
        if owner_id is not None:
            stmt = stmt.where(EtCourse.owner_id == owner_id)
        rows = await db.execute(stmt)
        return [(cid, name) for cid, name in rows]

    def mine_stmt(self, *, user_id: str) -> Select:
        """學員自查：**自己**的通過（`FR-ET-US17-03`，#464 擴充）。

        核可側：`RESULT = PASS` 且**未撤銷**。⚠️ 三個條件缺一不可——少了 `IS_REVOKED = false`，
        一筆被撤銷的通過會出現在學員的「已通過課程」裡，而那個通過已經被教師推翻了。

        完課側（#464 Q4 裁示 A）：不需核可課程完課即通過。⚠️ 有核可紀錄者以核可紀錄為準
        （`_completion_side` 的 `NOT EXISTS`）——所以一位在切換過 `REQUIRE_APPROVAL` 的課程
        被評為**不通過**的學員，不會因為完課而在自己的清單上看到「通過」。
        """
        approval_side = (
            select(*_approval_projection())
            .join(EtCourse, EtCourse.course_id == EtApproval.course_id)
            .where(
                EtApproval.user_id == user_id,
                EtApproval.result == APPROVAL_PASS,
                EtApproval.is_revoked.is_(False),
                EtApproval.deleted == 0,
                EtCourse.deleted == 0,
            )
        )
        return _ordered(approval_side, _completion_side(user_id=user_id))

    async def courses(self, db: AsyncSession, course_ids: list[int]) -> dict[int, CourseBrief]:
        """本頁涉及的課程名稱與擁有者。

        `owner_id` 是為了 `RESULT_NOTE` 的遮蔽判定而一併取回——這支查詢本來就要讀
        `ET_COURSE`，多一個欄位不增加往返。

        ## ⚠️ 本方法**不濾 `DELETED`**，而兩個呼叫端餵進來的東西來源不同

        | 呼叫端 | 餵的 `course_ids` | 為何可以不濾 |
        |---|---|---|
        | `_enrich` / `mine` | 分頁結果的課程（語句已含 `EtCourse.deleted == 0`）| 已經篩過了 |
        | `search` 的擁有權判定（#439）| **使用者直接給的 `course_id`，未經任何篩選** | 見下 |

        ↔️ **第二種情形已於 #548 裁示 4 消失**：擁有權閘（`ensure_course_filter_allowed`）
        整支退役，`search` 不再為了判定擁有權而查課程，`course_id` 直接進 `WHERE`。

        於是「已軟刪除的課程」這件事由 `teacher_query_stmt` 的 `EtCourse.deleted == 0`
        單獨承擔——指定一門已刪除的課程得到空結果，與指定不存在的課程**無從區分**，
        而那正是我們要的：⛔ 本端點不得成為課程存在性的 oracle。

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
