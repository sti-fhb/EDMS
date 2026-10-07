"""核可查詢之純業務規則（US17 / #385、#439、#548）——**不碰 DB**。

## ⚠️ 本檔曾經承載「可見範圍」，#548 之後沒有了

2026-09-21 的 SA Q1 裁示 C 要求教師依**結果**分流——「通過且未撤銷」看全部課程，
「不通過 / 已撤銷」僅限自己 owner 的課程——由一支 `visible_clause()` 回傳 SQL 條件實作。

**#548 裁示 1 推翻了分流**：只要具 `ET_TEACHER` 或 `ET_ADMIN` 其一，即可看到全部課程
的全部結果。理由不是分流做錯了，而是它**作為保密邊界站不住**：教師本來就能用姓名查到
他人課程的通過紀錄，課程篩選卻限制在自有課程，同一份資料兩條路兩種規則；而畫面完全
沒有傳達「課程篩選是成本控制」這件事。

於是 `visible_clause()` 整支退役——查詢不再有任何範圍條件，`teacher_query_stmt` 也
不再收 `visible` 參數。

🔴 **被保留的是欄位維度**：`RESULT_NOTE`（裁示 2）與 `REVOKE_REASON`（裁示 7）仍只對
該課程 owner 與管理者顯示，實作在 `query_service._enrich`。⛔ 那不是分流的殘餘，是
刻意留下的另一半——負面自由文字與「他通過了沒有」性質不同。

⛔ **要把範圍收回去就是推翻 #548，不是修 bug。** 反向斷言在
`tests/integration/et/test_et_approval_query.py::TestTeacherScope`，每一條都標了 ↔️。
"""

from app.core.exceptions import AppError

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
    """正規化 ET04 的查詢條件，並確保**至少給一個**（#439）。

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
    自己開設的課；選自己的課看到自己課的學員，是他本來就有的資訊（ET02 整頁就是做
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
    （ET02 核可、課程編輯）。本函式吃已算好的 `is_admin`、拋 `ET_APPROVAL_007`，且**查無
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


def can_see_private_notes(*, course_owner_id: str | None, actor_id: str, is_admin: bool) -> bool:
    """該查詢者是否看得到這一列的**負面自由文字**欄位（#548 裁示 2 + 7）。

    管的是兩個欄位，**而且只能有這一支判斷**：

    | 欄位 | 內容 |
    |---|---|
    | `RESULT_NOTE` | 教師寫的考核備註（「第二次補考才通過，單採操作仍不穩」）|
    | `REVOKE_REASON` | 撤銷原因（「核可對象誤植」「考核紀錄登記錯誤」）|

    Args:
        course_owner_id: 該列所屬課程的 `OWNER_ID`；**查無課程時為 `None`**。
        actor_id: 查詢者的 `USER_ID`。
        is_admin: 是否具 ET 管理者角色——管理者看得到全部。

    Returns:
        看得到回 `True`；否則 `False`（呼叫端 MUST 把欄位換成 `None`）。

    ## ⛔ 兩個欄位不得各寫一份條件

    `REVOKE_REASON` 原本**沒有**任何欄位層的遮蔽——它是靠已退役的 `visible_clause`
    「已撤銷的列只有 owner 看得到」**間接**保護的。#548 拿掉那個條件時，若只記得改
    `RESULT_NOTE` 那一支，撤銷原因就會對全體教師公開。

    各寫一份的後果是：日後有人改其中一個的條件（例如放寬給協同教師），另一個會靜默
    留在舊規則上，**而兩者各自的測試都還會過**。
    `TestRevokeReasonRedaction::test_兩個欄位用同一個判斷` 釘住這件事。

    ⚠️ **遮的只有原因文字**：「已撤銷」這個事實、撤銷時間與撤銷人仍對全體教師可見。
    把 `is_revoked` 一起遮掉會讓教師把被撤銷的紀錄讀成有效核可——方向比洩漏原因更糟。

    ⚠️ 查無課程時 **fail-closed**（遮蔽）。
    """
    if is_admin:
        return True
    return course_owner_id is not None and course_owner_id == actor_id
