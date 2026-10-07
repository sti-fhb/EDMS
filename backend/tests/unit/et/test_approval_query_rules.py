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

from app.core.exceptions import AppError
from app.et.approval.query_rules import (
    can_see_private_notes,
    ensure_course_filter_allowed,
    normalize_search_criteria,
)

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


class TestSearchCriteria:
    """「關鍵字與課程至少給一個」（#439，取代 SA Q2 裁示 A 的關鍵字必填）。

    ⚠️ 換的是**手段**不是目的：裁示 A 擋的是「留白＝傾印員工名冊」，而課程下拉只列
    教師自己開的課，選自己的課看到自己課的學員是他本來就有的資訊。兩者皆不給仍須擋下
    ——那才是原本的「留白查全部」。
    """

    def test_只給關鍵字時回傳去空白後的值(self) -> None:
        assert normalize_search_criteria(keyword="  林佳蓉 ", course_id=None) == "林佳蓉"

    def test_只給課程時關鍵字為_none_而不是空字串(self) -> None:
        """🔴 回 `None` 不回 `""`。

        repository 以 `if keyword:` 決定要不要加那段 `ilike`，空字串雖然也是 falsy，
        但它會讓「沒給關鍵字」與「給了空白字串」在型別上長得一樣，下一個人很容易寫出
        `keyword is not None` 而讓比對變成 `%%`（命中全部）。
        """
        assert normalize_search_criteria(keyword=None, course_id=11) is None
        assert normalize_search_criteria(keyword="   ", course_id=11) is None

    def test_兩者皆給時兩個條件都保留(self) -> None:
        assert normalize_search_criteria(keyword="林", course_id=11) == "林"

    def test_兩者皆不給回_422(self) -> None:
        with pytest.raises(AppError) as exc:
            normalize_search_criteria(keyword=None, course_id=None)
        assert exc.value.status_code == 422
        assert exc.value.error_code == "ET_APPROVAL_006"

    def test_關鍵字全空白且未選課程同樣回_422(self) -> None:
        """全空白必須與未填等價，否則前端送一個空格就繞過了「至少給一個」。"""
        with pytest.raises(AppError) as exc:
            normalize_search_criteria(keyword="   ", course_id=None)
        assert exc.value.error_code == "ET_APPROVAL_006"


class TestCourseFilterOwnership:
    """🔴 非管理者**只能依自己開設的課程**篩選（#439 實作時收斂，見 PR 說明）。

    issue 的「不構成傾印名冊」論證整個建立在「下拉只列自己的課」之上——但下拉是 UI。
    若 API 收任何 `course_id`，教師可以用 `{course_id: 別人的課}` 一次撈出**該課全部
    通過者的名單**，不需要知道任何名字，而那正是 SA Q2 裁示 A 要擋的東西改以課程為單位
    重演。可見範圍（裁示 C）未被放寬，本閘是**收斂**方向。

    ⚠️ 正常 UI 走不到這裡（下拉只有自己的課）——這是防繞過，不是流程的一部分。
    """

    def test_管理者不受限(self) -> None:
        ensure_course_filter_allowed(owner_id="t_other", actor_id="admin01", is_admin=True)

    def test_管理者選一門查無的課程也不擋(self) -> None:
        """管理者的可見範圍是 `true()`，查無課程只會得到空結果，不需要在此攔。"""
        ensure_course_filter_allowed(owner_id=None, actor_id="admin01", is_admin=True)

    def test_教師選自己的課通過(self) -> None:
        ensure_course_filter_allowed(owner_id="t_own", actor_id="t_own", is_admin=False)

    def test_教師選他人的課回_403(self) -> None:
        with pytest.raises(AppError) as exc:
            ensure_course_filter_allowed(owner_id="t_other", actor_id="t_own", is_admin=False)
        assert exc.value.status_code == 403
        assert exc.value.error_code == "ET_APPROVAL_007"

    def test_查無課程時對教師_fail_closed(self) -> None:
        """⚠️ 查無 → 擋下，不是放行。

        放行的話，`course_id` 隨便給一個不存在的值就會退化成「沒有課程條件」的查詢
        ——而那條路徑在關鍵字也沒給時本該是 422。
        """
        with pytest.raises(AppError) as exc:
            ensure_course_filter_allowed(owner_id=None, actor_id="t_own", is_admin=False)
        assert exc.value.error_code == "ET_APPROVAL_007"
