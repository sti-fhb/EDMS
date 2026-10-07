"""核可查詢之純業務規則（US17 / #385、#439、#548）。

## ⚠️ 本檔曾有三個 class 在守「可見範圍」，#548 之後沒有了

2026-09-21 的 SA Q1 裁示 C 要求教師依結果分流（通過看全部、不通過與已撤銷僅限自己
owner），由 `visible_clause()` 回傳一段 SQL 條件實作，本檔以編譯後的 SQL 字串驗證它
——包含一條專門釘住 `A AND B OR C` 運算子結合順序的測試。

**#548 裁示 1 推翻了分流**，`visible_clause()` 整支退役，那三個 class 隨之移除：
`TestAdminScope`、`TestTeacherScope`、`TestClauseIsReusable`。

反向斷言在 `tests/integration/et/test_et_approval_query.py::TestTeacherScope`，每條
都標了 ↔️ 並寫明原本是什麼。**那裡是現在唯一記得「曾經有過分流」的地方**，因為條件
已不存在、無法再以 unit 驗證。

🔴 **被保留的是欄位維度**：`can_see_private_notes` 管 `RESULT_NOTE`（裁示 2）與
`REVOKE_REASON`（裁示 7），由下方 `TestPrivateNotesVisibility` 守。

> 📌 為何退役的是「範圍」而不是「欄位」：教師本來就能用姓名查到他人課程的通過紀錄，
> 範圍限制作為保密邊界站不住；但另一位教師對具名學員寫的**負面自由文字**是另一回事。
"""

import pytest

from app.et.approval.query_rules import can_see_private_notes, normalize_keyword

pytestmark = pytest.mark.unit


class TestPrivateNotesVisibility:
    """🔴 `RESULT_NOTE` 與 `REVOKE_REASON` 只對該課程 owner 與管理者顯示。

    ⛔ 兩個欄位**共用這一支判斷**。`REVOKE_REASON` 原本沒有任何欄位層的遮蔽——它是靠
    已退役的 `visible_clause` 間接保護的，#548 若只記得改 `RESULT_NOTE` 那一支，撤銷
    原因就會對全體教師公開。
    """

    def test_管理者看得到全部(self) -> None:
        assert can_see_private_notes(course_owner_id="t_other", actor_id="adm01", is_admin=True) is True

    def test_該課程_owner_看得到(self) -> None:
        assert can_see_private_notes(course_owner_id="t_own", actor_id="t_own", is_admin=False) is True

    def test_他人課程的教師看不到(self) -> None:
        assert can_see_private_notes(course_owner_id="t_other", actor_id="t_own", is_admin=False) is False

    def test_查無課程時對教師_fail_closed(self) -> None:
        """⚠️ 查無 → 遮蔽，不是放行。

        `courses` 是以結果集的 `course_id` 另查的 dict，理論上必定查得到；但「理論上
        不會發生」正是 fail-open 最容易混進來的地方——真的發生時沒有任何訊號。
        """
        assert can_see_private_notes(course_owner_id=None, actor_id="t_own", is_admin=False) is False

    def test_查無課程時管理者仍看得到(self) -> None:
        """管理者不受課程歸屬影響，查無課程也不該因此被遮蔽。"""
        assert can_see_private_notes(course_owner_id=None, actor_id="adm01", is_admin=True) is True


class TestKeywordNormalization:
    """關鍵字的正規化。**#548 裁示 3 之後本函式不再有「至少給一個」的檢核。**

    ↔️ 原名 `normalize_search_criteria`，還收 `course_id` 並在兩者皆未給時拋 422
    `ET_APPROVAL_006`。它曾是母體限制的三道之一（另兩道：裁示 C 的結果分流、
    `ET_APPROVAL_007` 的課程擁有權閘）——三道一起退役是刻意的，只留這一道會讓
    「用姓名逐個查」與「一次列出」在能力上相同、在操作成本上差很多。

    🔴 **剩下的唯一職責是型別正規化**：空白 → `None`（不是 `""`）。
    """

    def test_回傳去空白後的值(self) -> None:
        assert normalize_keyword("  林佳蓉 ") == "林佳蓉"

    def test_未給時回_none(self) -> None:
        """↔️ 原本在「課程也沒給」時會拋 422 `ET_APPROVAL_006`。"""
        assert normalize_keyword(None) is None

    def test_全空白回_none_而不是空字串(self) -> None:
        """🔴 本函式現在唯一在守的東西。

        repository 以 `if keyword:` 決定要不要加那段 `ilike`。空字串雖然同樣 falsy，
        卻讓「沒給」與「給了空白」在型別上無從分辨，下一個人很容易改寫成
        `keyword is not None`——那會讓比對變成 `%%`。

        ⚠️ 留白本來就回全部，所以那個 bug 的**結果**看起來正常；但 `%%` 與「不加條件」
        在 SQL 上不同（前者會排除 `EMAIL IS NULL` 的列），差異只在邊界現形。
        ⛔ 故斷言用 `is None` 而非 `not normalize_keyword(...)`——後者對 `""` 也成立。
        """
        assert normalize_keyword("   ") is None

    def test_中間的空白不被移除(self) -> None:
        """只去頭尾：姓名中間可能有空格（外籍人士），全部拿掉會查不到。"""
        assert normalize_keyword("  林 佳蓉  ") == "林 佳蓉"


# ⚠️ `TestCourseFilterOwnership` 已於 #548 裁示 4 移除（`ensure_course_filter_allowed`
# 整支退役）。它曾守著「非管理者只能依自己開設的課程篩選」，拋 403 `ET_APPROVAL_007`。
#
# 反向斷言在 `tests/integration/et/test_et_approval_query.py::TestCourseFilterAnyCourse`
# ——那裡是現在唯一記得「曾經有過擁有權閘」的地方。
