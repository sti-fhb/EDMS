"""核可查詢之純業務規則（US17 / #385、#439）——**不碰 DB**。

兩組規則：**可見範圍**（誰看得到哪些紀錄，裁示 C）與**查詢條件**（要給什麼才查得動，
#439 取代裁示 A）。兩者刻意放同一檔——它們一起決定一次查詢的結果集，而且都是純函式，
拆開只會讓「改了範圍卻忘了條件」更容易發生。

## SA Q1 裁示 C（2026-09-21）

教師（非管理者）查詢時依**結果**分流：

| 紀錄 | 教師可見範圍 |
|---|---|
| `RESULT = PASS` 且 `IS_REVOKED = false` | **全部課程** |
| `RESULT = FAIL` | 僅自己 owner 的課程 |
| `IS_REVOKED = true`（不論原 `RESULT`）| 僅自己 owner 的課程 |

管理者不受此分流（`FR-ET-US17-02`、場景 3）。

**為何不是「教師只能查自己的課」（選項 A）或「教師可查全部」（選項 B）**：客戶原始需求
是「用姓名查學員**通過**了哪些課程」——那天生跨課程（排班的人需要知道某人受訓完整
與否）。但「不通過」與其 `RESULT_NOTE`（如「實機操作需再加強」）是考核評價，不該讓
同儕教師隨意翻閱。C 讓兩者各歸各位。

⚠️ C 的已知缺點：教師看到某門課「沒出現」時，分不清是「還沒考」還是「考了沒過」。
故教師視角 MUST 常駐提示「不通過與已撤銷的紀錄僅顯示您所開設的課程」——**那句話是
本裁示的配套，不是可選的 UX 潤飾**。少了它，C 比 A 更容易誤導：A 至少整份清單範圍
一致，C 是兩種範圍混在同一張表裡。

## 🔴 為何回傳「條件」而不是「布林」

範圍判定必須進 SQL 的 `WHERE`。若改成「取出資料後在 Python 裡濾掉不該看的」，
`paginate()` 的 `meta.total` 算的是**過濾前**的筆數（它以同一個 `stmt` 產生 count），
每頁也會少於 `limit`——教師看到「共 40 筆」卻只翻得出 12 筆，而且不會有任何錯誤訊息。
"""

from sqlalchemy import and_, or_, true
from sqlalchemy.sql.elements import ColumnElement

from app.core.exceptions import AppError
from app.et.approval.models import EtApproval
from app.et.constants import APPROVAL_PASS
from app.et.course.models import EtCourse

#: 查詢條件不足（#439 取代 SA Q2 裁示 A 的「關鍵字必填」）。
#:
#: ⚠️ **沿用 `006` 不另編新號**：情境沒有變——它一直都是「查詢條件不足」，只是「足夠」
#: 的定義從「有姓名」放寬為「有關鍵字或有課程」。訊息隨之更新（`docs/ref/error-codes.md`
#: 已同步）。前端顯示的是後端回傳的 `error_message`、不做 code → 字串的本地對照，
#: 故舊前端不會顯示過期文案。
_CRITERIA_REQUIRED = AppError(
    status_code=422,
    detail="請輸入關鍵字或選擇課程",
    error_code="ET_APPROVAL_006",
)

#: 非管理者以他人課程篩選（#439）。
_COURSE_NOT_OWNED = AppError(
    status_code=403,
    detail="僅能依您所開設的課程篩選",
    error_code="ET_APPROVAL_007",
)


def normalize_search_criteria(*, keyword: str | None, course_id: int | None) -> str | None:
    """正規化 ET10 的查詢條件，並確保**至少給一個**（#439）。

    Args:
        keyword: 學員姓名或 Email 關鍵字，未填為 `None`。
        course_id: 課程篩選，未選為 `None`。

    Returns:
        去空白後的關鍵字；未填或全空白時為 `None`（**不是空字串**，見下）。

    Raises:
        AppError: 兩者皆未提供（422 `ET_APPROVAL_006`）。

    ## 這是「換手段、保目的」，不是把裁示 A 拿掉

    SA Q2 裁示 A 要求關鍵字必填，理由兩半：「留白查全部**沒有對應需求**」與「**會傾印
    員工名冊**」。前者已被 #439 推翻（使用者常常正是不知道有誰可以查），後者**在課程
    路徑上仍然成立**——所以兩者皆不給依舊回 422，那才是原本的「留白查全部」。

    課程之所以能取代關鍵字，是因為 `ensure_course_filter_allowed` 把非管理者限制在
    自己開設的課；選自己的課看到自己課的學員，是他本來就有的資訊（ET03 整頁就是做
    這件事）。**兩者是一組的**——少了那道閘，本函式就等於單純開放留白查詢。

    ## 🔴 ⛔ 別把本函式讀成防列舉的防線——關鍵字那一側有一個已知缺口

    `DP_USER.EMAIL` 是 `NOT NULL`，而關鍵字走 `contains` 比對且 `@` **不在** `like_escape`
    的跳脫集合裡（那裡只跳 `%` / `_` / `\\`）。於是單一請求 `keyword = "@"` 就對全體
    使用者命中，可在可見範圍內整批取回名單——**一個字元，不需要課程，跨全部課程**。

    由 #436（關鍵字加入 Email 比對）引入，追蹤於 **#456**。`approval/router.py` 的模組
    docstring 早就寫明真正在收斂列舉的是**母體限制**與**角色受控**，不是這道必填；
    本函式只是把「什麼算條件充足」的定義放寬，沒有、也從來沒有承擔過防列舉的責任。

    ## 🔴 未填回 `None` 而非 `""`

    repository 以 `if keyword:` 決定要不要加那段 `ilike`。空字串雖然同樣 falsy，卻讓
    「沒給」與「給了空白」在型別上無從分辨，下一個人很容易改寫成 `keyword is not None`
    ——那會讓比對變成 `%%`，命中全部且**沒有任何錯誤訊息**。
    """
    normalized = (keyword or "").strip() or None
    if normalized is None and course_id is None:
        raise _CRITERIA_REQUIRED
    return normalized


def ensure_course_filter_allowed(*, owner_id: str | None, actor_id: str, is_admin: bool) -> None:
    """非管理者只能依**自己開設的課程**篩選（#439）。

    Args:
        owner_id: 該課程的 `OWNER_ID`；**查無該課程時為 `None`**。
        actor_id: 查詢者的 `USER_ID`。
        is_admin: 是否具 ET 管理者角色——管理者不受此限。

    Raises:
        AppError: 非管理者且該課程不屬於他（403 `ET_APPROVAL_007`）。

    ## 🔴 為何要有這道閘：下拉是 UI，API 才是邊界

    #439 的「不構成傾印名冊」論證整個建立在「課程下拉只列教師自己開的課」之上。但下拉
    擋不住直接送出的請求——少了這道閘，教師可以用 `{course_id: 別人的課}` 一次撈出**該
    課全部通過者的名單**，不需要知道任何名字。那正是裁示 A 要擋的東西改以課程為單位重演，
    而且它會正常運作、不會有任何東西變紅。

    ⚠️ 本閘是**收斂**方向，沒有動到可見範圍（裁示 C）：教師依然能以關鍵字查到全部課程
    的「通過且未撤銷」。變的只是「能不能不指名地整批取回」。

    ⚠️ 查無課程時對非管理者 **fail-closed**。放行的話，隨便給一個不存在的 `course_id`
    就會退化成「沒有課程條件」的查詢——而那條路徑在關鍵字也沒給時本該是 422。

    ## ⚠️ 這是 `course/rules.ensure_owner_or_admin` 的**第二份**「owner ∪ 管理者」判定

    那一份吃 `actor_roles` 自己算 `is_admin`、拋 `ET_COURSE_002`，是**寫入**路徑用的
    （ET03 核可、課程編輯）。本函式吃已算好的 `is_admin`、拋 `ET_APPROVAL_007`，且**查無
    課程時擋下**而不是回「課程不存在」——因為本情境的 `course_id` 直接來自使用者、未經
    任何篩選，回 404 等於一支課程存在性的 oracle。

    ⛔ 不要把兩份合併成一個共用函式：訊息與 fail 行為不同，硬合會讓其中一邊的語意遷就
    另一邊。但**兩份的規則若要改，必須一起看**——日後若引入共同授課 / 代理教師，這裡會
    先變成「能核可、卻不能依該課篩選」（fail-closed 方向，不是漏洞，但會是個怪現象）。
    """
    if is_admin:
        return
    if owner_id != actor_id:
        raise _COURSE_NOT_OWNED


def visible_clause(*, actor_id: str, is_admin: bool) -> ColumnElement[bool]:
    """教師 / 管理者查詢核可紀錄時的可見範圍條件（SA Q1 裁示 C）。

    Args:
        actor_id: 查詢者的 `USER_ID`，用於比對 `ET_COURSE.OWNER_ID`。
        is_admin: 是否具 ET 管理者角色。管理者不受任何範圍限制。

    Returns:
        可直接放進 `.where()` 的條件。**呼叫端的 SELECT 必須已 JOIN `ET_COURSE`**
        ——本條件會比對 `EtCourse.owner_id`，未 JOIN 會產生笛卡兒積而不是錯誤。

    ⚠️ 「通過」那一側**必須同時要求未撤銷**。被撤銷的通過其 `RESULT` 仍是 `PASS`，
    只依 `RESULT` 分流會讓它對全體教師可見**並顯示撤銷原因**——而撤銷原因正是負面判斷
    （誤植、考核有問題），那是本裁示要擋的東西從側門漏出去。
    """
    if is_admin:
        return true()
    return or_(
        and_(EtApproval.result == APPROVAL_PASS, EtApproval.is_revoked.is_(False)),
        EtCourse.owner_id == actor_id,
    )
