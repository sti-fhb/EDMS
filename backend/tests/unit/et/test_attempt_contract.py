"""作答明細之前後端欄位名契約（#358 第 1 項）。

## 這個檔案存在的理由

`OptionResult` 的欄位名**同時是前端的契約**。前端那邊是 TypeScript `interface`，只存在於
編譯期——名字對不上時執行期讀到 `undefined`，**不會拋錯**：選項文字變空白、`selected`
為 falsy 故每一題都標成未選，連滿分的題目都顯示「（正確答案，未選）」。CI 全綠。

`sti-zod-conventions.md` 明訂 API 回應型別**保留手寫 interface**（zod 只用於表單），所以
前端沒有執行期驗證可以擋。防護因此分三道：

| 道 | 位置 | 擋什麼 |
|---|---|---|
| 1 | **本檔** | 後端改名時變紅，逼改動者一併處理前端 |
| 2 | `frontend/src/test/server.ts` 的 fixture 以**後端名字**撰寫 | 前端改名時渲染測試變紅 |
| 3 | `StudentsPage.test.tsx` 真的渲染選項並斷言勾選狀態 | 讓第 2 道有東西可以紅 |

⚠️ 第 2 道是本次才補上的——原本 fixture 用的是前端的錯名字，**假資料與 bug 互相印證**，
而唯一開啟該對話框的測試又把 `questions` 覆寫成 `[]`，那些選項從來沒被渲染過。
"""

import pytest

from app.et.attempt.schemas import OptionResult, QuestionResult

pytestmark = pytest.mark.unit


class TestOptionResultContract:
    """`OptionResult` 的欄位名是前後端契約，改名即為 breaking change。"""

    def test_欄位名一個不多一個不少(self) -> None:
        """🔴 改這組名字**必須**同步下列三處，否則教師端的作答明細會靜默變空白：

        - `frontend/src/et/students/schemas.ts::OptionResult`
        - `frontend/src/et/students/TeacherAttemptDialog.tsx`（`optionColor` 與渲染）
        - `frontend/src/test/server.ts` 的 attempt detail fixture

        ⚠️ 本 schema 由**學員端與教師端兩個端點共用**（`attempt/service.py::to_question_result`），
        改名同時是對已交付之學員端 API 的破壞性變更。#358 的裁示是**改前端對齊後端**，
        正是因為改動面在這一側大得多。
        """
        assert set(OptionResult.model_fields) == {"option_id", "text", "is_correct", "selected"}

    def test_不可改用前端風格的欄位名(self) -> None:
        """釘住那兩個**曾經被抄錯**的名字不會出現在後端。

        單純斷言正確名字存在擋不住「兩種都給」的折衷改法——那會讓契約有兩個事實來源。
        """
        assert "option_text" not in OptionResult.model_fields
        assert "is_selected" not in OptionResult.model_fields


class TestQuestionResultContract:
    """`QuestionResult` 同為兩端共用，順帶釘住。"""

    def test_欄位名一個不多一個不少(self) -> None:
        assert set(QuestionResult.model_fields) == {
            "question_id",
            "question_type",
            "stem",
            "points",
            "score",
            "outcome",
            "options",
        }
