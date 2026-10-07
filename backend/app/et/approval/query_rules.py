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


# ⚠️ **`ET_APPROVAL_006` 與 `ET_APPROVAL_007` 已於 #548 退役**（裁示 3 / 4）。
#
# | 碼 | 原本擋什麼 | 為何不再需要 |
# |---|---|---|
# | `006` | 關鍵字與課程皆未給（「留白查全部」）| 裁示 3：留白查詢成為合法操作 |
# | `007` | 非管理者以他人課程篩選 | 裁示 4：課程篩選不分 owner |
#
# ⛔ **兩個編號不得重用於別的情境**：舊前端與舊測試可能還認得它們，重用會讓錯誤訊息
# 對不上。`docs/ref/error-codes.md` 保留編號並標記已退役。


def normalize_keyword(keyword: str | None) -> str | None:
    """正規化 ET04 的查詢關鍵字。

    Args:
        keyword: 學員姓名或 Email 關鍵字，未填為 `None`。

    Returns:
        去空白後的關鍵字；未填或全空白時為 `None`（**不是空字串**，見下）。

    ## ↔️ 本函式曾經還負責「至少給一個條件」，#548 裁示 3 拿掉了

    原名 `normalize_search_criteria`，兩者皆不給時拋 422 `ET_APPROVAL_006`。那是母體
    限制的三道之一，另兩道是裁示 C 的結果分流與 `ET_APPROVAL_007` 的課程擁有權閘。

    **三道一起退役是刻意的。** 只留這一道，會讓「用姓名逐個查」與「一次列出」在能力
    上相同、在操作成本上差很多，而畫面從不解釋為什麼。⚠️ 代價是全量取回變成一鍵可達，
    由**讀取稽核**承接（裁示 5）——不能出現「能全量取回但零軌跡」的空窗期。

    ⛔ 要把「至少給一個」加回來，請連同另外兩道一起考慮；單獨加回來擋不住任何東西。

    ## 🔴 未填回 `None` 而非 `""`——這是本函式現在唯一在守的東西

    repository 以 `if keyword:` 決定要不要加那段 `ilike`。空字串雖然同樣 falsy，卻讓
    「沒給」與「給了空白」在型別上無從分辨，下一個人很容易改寫成 `keyword is not None`
    ——那會讓比對變成 `%%`。

    ⚠️ 留白本來就回全部，所以那個 bug 的**結果**看起來正常；但 `%%` 與「不加條件」在
    SQL 上不同（前者會排除 `EMAIL IS NULL` 的列），差異只在邊界現形。
    """
    return (keyword or "").strip() or None


# ⚠️ `ensure_course_filter_allowed` 已於 #548 裁示 4 移除。它曾要求非管理者只能依
# 自己開設的課程篩選（403 `ET_APPROVAL_007`），論證是「下拉是 UI、API 才是邊界」。
#
# 拿掉的理由不是那個論證錯了，而是它擋的是**取得成本**而非**可見資料**——教師本來就能
# 用姓名查到他人課程的紀錄。同一份資料兩條路兩種規則，而畫面從不解釋為什麼。
#
# 反向斷言：`tests/integration/et/test_et_approval_query.py::TestCourseFilterAnyCourse`。


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
