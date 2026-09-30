"""核可查詢之可見範圍判定（US17 / #385，SA Q1 裁示 C）。

## 為何這組是 unit 而非 integration

`visible_clause` 是純函式——吃身分、回一段 SQLAlchemy 條件，不碰 DB。把它抽出來的
理由不只是好測：**範圍判定必須進 `WHERE`，不能是取出資料後的 Python 後篩**。後篩會讓
`paginate()` 的 `meta.total` 算的是過濾**前**的筆數、每頁也少於 `limit`——教師看到
「共 40 筆」卻只翻得出 12 筆，而且不會有任何錯誤訊息。條件是一個獨立的值，這件事才
守得住。

本檔比對編譯後的 SQL 字串。⚠️ **那只證明條件被組進去了，不證明它在真的資料上篩對**
——後者由 `tests/integration/et/test_et_approval_query.py` 以實際資料驗證。兩層都要。
"""

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.core.exceptions import AppError
from app.et.approval.models import EtApproval
from app.et.approval.query_rules import (
    ensure_course_filter_allowed,
    normalize_search_criteria,
    visible_clause,
)
from app.et.course.models import EtCourse

pytestmark = pytest.mark.unit


def _sql(clause) -> str:
    """把條件組進一個 SELECT 並編譯成含字面值的 SQL，供斷言比對。"""
    stmt = select(EtApproval.approval_id).join(EtCourse, EtCourse.course_id == EtApproval.course_id).where(clause)
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class TestAdminScope:
    def test_管理者不受任何範圍限制(self) -> None:
        """`FR-ET-US17-02` 與場景 3：管理者可查全部課程之全部學員核可紀錄。"""
        sql = _sql(visible_clause(actor_id="admin01", is_admin=True))
        assert "OWNER_ID" not in sql, "管理者的條件不得出現課程擁有者比對"
        assert "IS_REVOKED" not in sql, "管理者的條件不得出現撤銷狀態比對"


class TestTeacherScope:
    """SA Q1 裁示 C：通過看全部、不通過與已撤銷僅限自己 owner 的課程。"""

    def test_條件同時包含結果與擁有者兩側(self) -> None:
        sql = _sql(visible_clause(actor_id="t01", is_admin=False))
        assert "RESULT" in sql and "IS_REVOKED" in sql, "缺少『通過且未撤銷』那一側"
        assert "OWNER_ID" in sql, "缺少『自己 owner』那一側"
        assert " OR " in sql, "兩側必須是 OR——教師看得到的是兩個集合的聯集"

    def test_通過那一側必須同時要求未撤銷且與擁有者側以_or_分開(self) -> None:
        """🔴 這條是裁示裡最容易漏的一句，而且它的正確性靠**運算子結合順序**。

        被撤銷的「通過」其 `RESULT` 仍是 `PASS`。若只依 `RESULT` 分流而不看
        `IS_REVOKED`，一筆被撤銷的 PASS 會對全體教師可見**並顯示撤銷原因**——而撤銷原因
        承載的正是負面判斷（誤植、考核有問題），那是本裁示要擋的東西從側門漏出去。

        ⚠️ SQLAlchemy 不會為 `or_(and_(A, B), C)` 補括號，編譯結果是 `A AND B OR C`。
        它之所以正確，是因為 SQL 的 `AND` 優先級高於 `OR`。本測試斷言的正是那個**順序**
        ——若日後有人把條件改寫成 `or_(A, and_(B, C))`，字串裡照樣有 AND / OR / 三個欄位，
        只比對「有沒有出現」的測試會照樣綠。
        """
        # 去掉識別字引號後比對，避免斷言綁死在 SQLAlchemy 的引號風格上
        sql = _sql(visible_clause(actor_id="t01", is_admin=False)).replace('"', "")
        where = sql.split("WHERE", 1)[1].strip()
        assert where.startswith("ET_APPROVAL.RESULT = 'PASS' AND ET_APPROVAL.IS_REVOKED IS false OR "), (
            f"『PASS AND 未撤銷』必須是 OR 的左側且兩者以 AND 相接，實得：{where}"
        )
        assert where.endswith("ET_COURSE.OWNER_ID = 't01'")

    def test_擁有者比對用的是傳入的身分(self) -> None:
        sql = _sql(visible_clause(actor_id="teacher_x", is_admin=False))
        assert "teacher_x" in sql


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


class TestClauseIsReusable:
    def test_同一組參數兩次呼叫產生相同條件(self) -> None:
        """條件會被 service 用在 count 與 data 兩支查詢上，兩者必須一致。

        `paginate()` 以 `select(func.count()).select_from(stmt.subquery())` 產生 count，
        與資料查詢共用同一個 `stmt`——若條件含隨機成分或可變狀態，總筆數與實際內容會對不上。
        """
        a = _sql(visible_clause(actor_id="t01", is_admin=False))
        b = _sql(visible_clause(actor_id="t01", is_admin=False))
        assert a == b
