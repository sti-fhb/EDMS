"""ET 會進入通知信**內文**的使用者輸入欄位，必須拒控制字元（#423）。

## 威脅模型（`core/schema_types.py` 已寫得很完整，此處只記結論）

平台發信層對主旨剝換行、但對**內文刻意保留 LF**（DM 的退回理由是真的多行輸入），
故多行名稱會原樣渲染成信件內容——讓一封 **SPF/DKIM 全部合法的組織信件夾帶自選文字**。

⚠️ 這**不**消除信件內文注入，只降低保真度：攻擊者仍可放入同一行的完整句子。真正消除
需改範本設計或不回顯使用者自填內容，屬產品決策（`schema_types.py` 明載）。

## 為何是測試而不是一份清單

一次性的盤點清單**會過期，而且過期時沒有任何徵兆**——新增一個進信件內文的欄位時，
沒有任何東西會提醒作者去翻那份文件。本檔把清單做成 fail-closed 的斷言：新增範本佔位符
而未分類 → 紅。⭐ 漏做的後果因此從「錯的資訊」降級成「**必須做一個決定**」。

（做法借自 edms-fa 於 #424 的 `EtLearningService` 公開方法分類測試。）
"""

import re

import pytest
from pydantic import ValidationError

from app.core.schema_types import SAFE_SINGLE_LINE_PATTERN
from app.et.constants import ITEM_QUIZ
from app.et.course.schemas import (
    ChapterCreateReq,
    ChapterRenameReq,
    CourseCreateReq,
    CourseUpdateReq,
    ItemCreateReq,
)
from app.et.notify.approval_passed import APPROVAL_PASSED_PARAM_KEYS
from app.et.notify.course_invite import COURSE_INVITE_PARAM_KEYS, DIGEST_PARAM_KEYS
from app.et.notify.course_update import COURSE_UPDATE_PARAM_KEYS
from app.et.notify.quiz_retest_required import QUIZ_RETEST_REQUIRED_PARAM_KEYS
from app.et.notify.schedule_mail import (
    URGENT_REMIND_PARAM_KEYS,
    WEEKLY_REMIND_PARAM_KEYS,
    WEEKLY_REPORT_PARAM_KEYS,
)
from app.et.quiz.schemas import QuizUpdateReq

pytestmark = pytest.mark.unit

#: ET 全部通知範本的佔位符集合。
#:
#: ⚠️ **這份聯集必須涵蓋所有範本**——遺漏一組，本檔的 fail-closed 斷言就對那組完全失效，
#: 而且不會有任何徵兆。我自己第一版只寫了 4 組（漏掉 `schedule_mail` 的 4 組），正是本檔
#: 要防的那種疏漏。新增通知模組時，把它的 `*_PARAM_KEYS` 加進來。
_TEMPLATE_KEY_SETS = (
    COURSE_INVITE_PARAM_KEYS,
    COURSE_UPDATE_PARAM_KEYS,
    QUIZ_RETEST_REQUIRED_PARAM_KEYS,
    APPROVAL_PASSED_PARAM_KEYS,
    DIGEST_PARAM_KEYS,
    URGENT_REMIND_PARAM_KEYS,
    WEEKLY_REMIND_PARAM_KEYS,
    WEEKLY_REPORT_PARAM_KEYS,
)


def _all_template_keys() -> set[str]:
    return set().union(*_TEMPLATE_KEY_SETS)


#: 含 LF 的名稱——攻擊者藉此在信件內文插入自選的一整行。
_INJECTED = "正常課程\n【重要】帳號異常，請至 http://evil.tw 處理"


#: `QuizUpdateReq` 的其餘必填欄位——值本身與本檔無關，只為讓模型建得起來。
_QUIZ_REQUIRED = {"pass_score": 60, "max_retry": 3, "version": 0}


def _rejects_control_chars(model, field: str, **extra) -> bool:
    """該欄位是否**因為那個欄位**而拒收含 LF 的值。

    🔴 **不可只看「有沒有拋 ValidationError」。** 第一版就是那樣寫的，結果
    `QuizUpdateReq` 因為缺 `pass_score` / `max_retry` 而拋，測試照樣綠——它驗到的是
    「我漏餵必填欄位」，不是「控制字元被擋」。那是一個**為了錯的理由而通過**的測試。

    故此處比對 `err["loc"]`：錯誤必須指向目標欄位；順手斷言**沒有其他欄位的錯誤**，
    否則下一個人加了必填欄位又會把這裡變成假綠。
    """
    try:
        model(**{field: _INJECTED, **extra})
    except ValidationError as exc:
        locs = {err["loc"][0] for err in exc.errors() if err["loc"]}
        assert locs == {field}, f"錯誤應只來自 {field}，實際為 {sorted(locs)}——請補齊其他必填欄位"
        return True
    return False


class TestChapterName:
    """#423 主體：`ET_CHAPTER.CHAPTER_NAME` 原本只有長度限制。"""

    def test_建立章節拒收含控制字元的名稱(self):
        assert _rejects_control_chars(ChapterCreateReq, "chapter_name")

    def test_更名章節也拒收(self):
        """🔴 AC 2：**不可只擋建立**。

        `ChapterRenameReq` 目前是 `ChapterCreateReq` 的子類別，故約束由繼承而來——
        但**繼承是實作細節，不是契約**。有人把欄位在子類別重新宣告（例如為了改長度上限）
        就會安靜地失去防護，而建立那條測試照樣綠。本條獨立釘住更新路徑。

        ⚠️ #414 的教訓正是「守門不在所有到得了的路徑上」。
        """
        assert _rejects_control_chars(ChapterRenameReq, "chapter_name", version=0)

    def test_正常名稱照常通過(self):
        assert ChapterCreateReq(chapter_name="第一章 採血作業").chapter_name == "第一章 採血作業"

    def test_前後空白仍照常_strip(self):
        """⚠️ pydantic 先 strip 再驗 pattern，故前後換行**不**被拒、只被去掉。

        這是既有行為（`schema_types.py` 註解載明已實測），本次不改變它——只有**內部**
        控制字元會被拒。
        """
        assert ChapterCreateReq(chapter_name="  第一章  ").chapter_name == "第一章"


class TestQuizName:
    """AC 5 的盤點抓到的第二個同類缺口：`{QUIZ_NAME}` 也進重測通知內文。

    範本原文（`20260921_1500_a7c31f5e9d24`）：

        {USER_NAME} 您好：\\n\\n課程「{COURSE_NAME}」的測驗「{QUIZ_NAME}」內容已更新，

    issue 說「章節名稱適用完全相同的推理，只是當初沒套上去」——**同一句話對測驗名稱
    也成立**，故一併修而非留給下一張票。
    """

    def test_更新測驗名稱拒收含控制字元(self):
        assert _rejects_control_chars(QuizUpdateReq, "quiz_name", **_QUIZ_REQUIRED)

    def test_正常測驗名稱照常通過(self):
        assert QuizUpdateReq(quiz_name="第一章小考", **_QUIZ_REQUIRED).quiz_name == "第一章小考"


class TestCourseName:
    """回歸護欄：`course_name` 本來就有防護，本次不得弄壞。"""

    def test_課程名稱仍拒收(self):
        assert _rejects_control_chars(CourseCreateReq, "course_name")


class TestMailBodyFieldInventory:
    """🔴 fail-closed 盤點：每個範本佔位符都必須被分類，新增未分類即紅。

    ⛔ **不要為了讓測試綠而把新佔位符隨手丟進豁免**——豁免要寫得出理由，而理由會被
    下一個讀的人檢驗。真的是使用者自填的自由文字，就去輸入端套 pattern。
    """

    #: 佔位符 → **全部**會寫入它的輸入端欄位 `(model, field)`。
    #:
    #: 🔴 **鍵是佔位符、值是清單，這件事是重點**：一個佔位符可以有**多條**輸入路徑，
    #: 只要一條沒守住洞就在。本檔第一版的值只是一句文字描述，於是
    #: `QUIZ_NAME` 被標成「已守住」，而它的**建立**路徑（`ItemCreateReq.title` →
    #: `create_shell` → `quiz_name`）完全沒被看見——**分類表對它無感**。
    #:
    #: 改成可執行的：下方測試會真的去讀每個欄位的 `pattern` 約束。漏列一條路徑仍然
    #: 抓不到（沒有東西能自動找出所有寫入點），但至少**列出來的每一條都經過驗證**，
    #: 而不是靠一句「✅ 已守住」。
    GUARDED: dict[str, list[tuple[type, str, dict]]] = {
        "COURSE_NAME": [(CourseCreateReq, "course_name", {}), (CourseUpdateReq, "course_name", {"version": 0})],
        "NEW_CHAPTER_NAME": [
            (ChapterCreateReq, "chapter_name", {}),
            (ChapterRenameReq, "chapter_name", {"version": 0}),
        ],
        "QUIZ_NAME": [(QuizUpdateReq, "quiz_name", _QUIZ_REQUIRED), (ItemCreateReq, "title", {"item_type": ITEM_QUIZ})],
        # 姓名三者同源（`DP_USER.USER_NAME`），由 DP 的 `SafeNameStr` 守；不在 ET schema 上。
        "USER_NAME": [],
        "TEACHER_NAME": [],
        "RECIPIENT_NAME": [],
        "APPROVED_BY_NAME": [],
    }

    #: 非使用者自填 → 不適用輸入端 pattern，但仍須寫明理由。
    EXEMPT = {
        "COURSE_URL": "系統以 settings 組出，不含使用者輸入",
        "REPORT_CSV_URL": "同上",
        "INVITATION_CODE": "系統產生之隨機碼",
        "OPEN_START_AT": "datetime 格式化，非自由文字",
        "OPEN_END_AT": "同上",
        "APPROVED_AT": "同上",
        "COURSE_LIST": "由已受防護之 course_name 組成（見下方測試）",
        "REPORT_SUMMARY": "系統計算之統計數字",
    }

    def test_每個範本佔位符都已分類(self):
        """新增佔位符而未分類 → 紅。這條就是那份「清單」的執行版。"""
        actual = _all_template_keys()
        classified = set(self.GUARDED) | set(self.EXEMPT)
        unclassified = actual - classified
        assert not unclassified, (
            f"新增的範本佔位符必須分類為 GUARDED（輸入端套 pattern）或 EXEMPT（附理由）：{sorted(unclassified)}"
        )

    def test_每條輸入路徑都真的擋得住控制字元(self):
        """🔴 這條才是表的執行版——只寫「已守住」證明不了任何事。

        ⚠️ 驗**行為**不驗**機制**。第一版是去讀 `StringConstraints` 的 `pattern` metadata，
        結果 `ItemCreateReq.title` 明明擋得住卻被判為未守——它用的是 `field_validator`
        而非 `Field(pattern=)`，因為該欄位**允許空字串**（2026-08-27「名稱可留空」裁示），
        而 `SAFE_SINGLE_LINE_PATTERN` 是 `^[...]+$`、要求至少 1 字元。

        ⭐ 驗機制會把「用了別的正確手段」誤判成缺口，也會把「掛了 pattern 但被其他
        validator 繞過」誤判成安全。實際餵一個含 LF 的值進去才是真的。
        """
        unguarded = []
        for placeholder, paths in self.GUARDED.items():
            for model, field, extra in paths:
                if not _rejects_control_chars(model, field, **extra):
                    unguarded.append(f"{placeholder}: {model.__name__}.{field}")
        assert not unguarded, "下列輸入路徑會進信件內文但擋不住控制字元：" + str(unguarded)

    def test_分類表沒有已不存在的佔位符(self):
        """反向：範本移除佔位符後，分類表也該跟著清，否則它會慢慢變成考古資料。"""
        actual = _all_template_keys()
        stale = (set(self.GUARDED) | set(self.EXEMPT)) - actual
        assert not stale, f"分類表列了範本已不使用的佔位符：{sorted(stale)}"

    NEWLINE_LIKE = {
        0x00: "NUL",
        0x0A: "LF",
        0x0D: "CR",
        0x0B: "VT",
        0x0C: "FF",
        0x1C: "FS",
        0x1D: "GS",
        0x1E: "RS",
        0x1F: "US",
        0x7F: "DEL",
        0x85: "NEL",
        0x2028: "LS",
        0x2029: "PS",
    }

    #: 刻意**不**擋的：屬顯示欺騙（同形字），與信件結構無關。
    DISPLAY_SPOOF = {0x202E: "RLO-雙向覆寫", 0x200D: "ZWJ"}

    def test_pattern_擋下每一個換行類字元(self):
        """⛔ issue 明令不得為此放寬 `SAFE_SINGLE_LINE_PATTERN`。

        ⚠️ 以**碼點**列舉並用 `chr()` 組出字元——原始碼中不寫跳脫序列。本檔前兩版
        都在這裡被吃掉過（跳脫在寫入時被解成真字元，產生一個壞掉的字面）。碼點也
        比跳脫貼近規格：排除範圍本來就是照 `str.splitlines()` 的切點定義的。

        ⛔ 也不要改回「比對正規式字串本身」——字面相等證明不了它真的擋得住什麼。
        """
        for code, name in self.NEWLINE_LIKE.items():
            assert not re.match(SAFE_SINGLE_LINE_PATTERN, "甲" + chr(code) + "乙"), f"{name} 未被擋下"

    def test_pattern_刻意不擋顯示欺騙類字元(self):
        """⭐ 反向釘住**刻意不擋**的範圍，否則日後有人「順手補強」會誤傷真人姓名。

        部分書寫系統的正常姓名會用到格式字元（`schema_types.py` 明載此判斷）。
        """
        for code, name in self.DISPLAY_SPOOF.items():
            assert re.match(SAFE_SINGLE_LINE_PATTERN, "甲" + chr(code) + "乙"), f"{name} 不該被擋"
