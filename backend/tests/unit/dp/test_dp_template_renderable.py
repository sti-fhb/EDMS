"""儲存時的範本佔位檢核（#534）。

## 為何這支測試存在

DP04 讓管理者編輯範本的**主旨與內文**，而內文裡的 `{變數}` 是一份**與呼叫端的契約**。
問題是：DP04 可以改契約的一端，但在 #534 之前**沒有任何一端在守它**。

管理者把 `{user_name}` 打成 `{user_nam}`，該範本從此每次寄送都失敗——`_SafeFormatter`
拋 `KeyError` → `send_email` 整批寫 `FAILED` → 回 `queued_count=0` 且**不外拋**。而
`DP_EMAIL_LOG` 沒有任何畫面在顯示（前端全掃零命中），所以沒有人會知道。

## 檢核與 `_render` 共用同一份解析邏輯（AC 2）

**不是抽一份共用正則，而是直接跑 `_render` 本身**：以該範本宣告的 `VARIABLES` 組一個空值
探針 dict 餵進去。這樣在定義上不可能與渲染時分歧——它就是渲染。

本檔逐條釘住「`_SafeFormatter` 擋得住的，儲存時也擋得住」這個等價關係。
"""

import pytest

from app.core.exceptions import AppError
from app.dp.notify.service import ensure_renderable

pytestmark = pytest.mark.unit

#: 多數案例共用的宣告（對齊 `DM/DOC_REJECT` 的真實 VARIABLES）
_VARS = "author_name,doc_name,reason"


def _err(subject: str = "主旨", body: str = "內文", variables: str | None = _VARS) -> AppError:
    with pytest.raises(AppError) as exc:
        ensure_renderable(subject=subject, body=body, variables=variables)
    return exc.value


class Test合法範本放行:
    async def test_佔位全部已宣告(self) -> None:
        ensure_renderable(
            subject="{doc_name} 已被退回",
            body="{author_name} 您好：\n\n退回原因：{reason}。請修改後重新送審。",
            variables=_VARS,
        )

    async def test_完全沒有佔位(self) -> None:
        ensure_renderable(subject="系統通知", body="請洽管理員。", variables=_VARS)

    async def test_宣告為空且內文無佔位(self) -> None:
        """`VARIABLES` 可為 NULL（欄位 nullable）。"""
        ensure_renderable(subject="主旨", body="內文", variables=None)

    async def test_只用了宣告的一部分(self) -> None:
        """宣告是**上界**不是清單——少用不算錯，多用才是。"""
        ensure_renderable(subject="{doc_name}", body="{doc_name}", variables=_VARS)


class Test未宣告的佔位:
    """`KeyError` 這一類：打錯字、用了沒宣告的變數。"""

    async def test_內文打錯一個字母(self) -> None:
        e = _err(body="{author_nam} 您好")  # 少一個 e
        assert e.status_code == 422
        assert e.error_code == "DP_MAIL_011"

    async def test_主旨也要檢核(self) -> None:
        """主旨與內文走不同的 formatter（主旨連 LF 一併剝），兩邊都得驗。"""
        assert _err(subject="{doc_nmae} 已退回").error_code == "DP_MAIL_011"

    async def test_宣告為空卻用了佔位(self) -> None:
        assert _err(body="{anything}", variables=None).error_code == "DP_MAIL_011"

    async def test_錯誤訊息不得嵌入佔位名稱(self) -> None:
        """`sti-error-codes` 明定 error_message 不得嵌入動態值；佔位名屬 schema 細節。

        （比照 `render_preview` 的 `DP_MAIL_007`：詳情只進伺服器日誌。）
        """
        e = _err(body="{SECRET_PLACEHOLDER_NAME}")
        assert "SECRET_PLACEHOLDER_NAME" not in e.detail


class Test非具名佔位與格式規格:
    """`ValueError` / `IndexError` 這一類——issue 特別點名「只修一半」的風險。"""

    @pytest.mark.parametrize(
        ("bad", "說明"),
        [
            ("{doc_name.__class__}", "屬性存取（原生 format 可讀到 JWT_SECRET_KEY）"),
            ("{doc_name[0]}", "索引存取"),
            ("{0}", "位置佔位"),
            ("{}", "自動編號佔位"),
            ("{doc_name:>200000000}", "格式規格（可 OOM 常駐 worker）"),
            ("未閉合的 {doc_name", "未閉合大括號"),
            ('<div style="{color:red}">x</div>', "HTML inline CSS——大括號是閉合的，`:` 才是問題"),
        ],
    )
    async def test_內文(self, bad: str, 說明: str) -> None:
        assert _err(body=bad).error_code == "DP_MAIL_011", 說明

    @pytest.mark.parametrize("bad", ["{doc_name.__class__}", "{0}", "{doc_name:>9}", "未閉合 {x"])
    async def test_主旨(self, bad: str) -> None:
        assert _err(subject=bad).error_code == "DP_MAIL_011"


class Test與_render_的等價關係:
    """AC 2 的可執行版本：檢核放行的，`_render` 就渲染得出來。

    ⚠️ 這條是本檔唯一能證明「共用解析邏輯」的斷言。只測「壞的被擋」不足以證明兩者同源——
    一份獨立寫的正則也可能擋得住上面所有案例，卻在某個邊角與 `_render` 分歧，而分歧的
    方向正好是「檢核放行、渲染失敗」。
    """

    @pytest.mark.parametrize(
        "body",
        [
            "{doc_name}",
            "純文字",
            "跳脫的大括號 {{ 不是佔位 }}",  # str.format 的跳脫寫法
            "{doc_name} 與 {reason} 同時出現",
            "換行\n後面還有 {author_name}",
        ],
    )
    async def test_放行者必定渲染得出來(self, body: str) -> None:
        from app.dp.notify.service import _render

        ensure_renderable(subject="x", body=body, variables=_VARS)
        # 不拋例外即通過；此處用真實參數再跑一次，確認不是「檢核寬鬆、渲染嚴格」
        _render(body, {"author_name": "甲", "doc_name": "乙", "reason": "丙"})


class Test主旨不得多行:
    """主旨的**範本文字本身**含換行 → 422 `DP_MAIL_012`（#534 Security MEDIUM-3）。

    ## 為何這條比「打錯變數名」更隱形

    `_SUBJECT_TRANS` 的剝除只作用於**代入值**，不作用於範本文字；`_SubjectStr` 的
    `strip_whitespace` 也只剝頭尾。於是多行主旨存得進去、渲染正常、`send_email` 回報
    `queued_count=N` **看起來完全成功**——失敗發生在 worker（stdlib 設 header 時拋
    「Header values may not contain linefeed or carriage return」），而 `worker.py` 的
    `except Exception` 吞掉後只把訊息寫進 `DP_EMAIL_LOG.ERROR_MSG`、**連一行 log 都沒有**。

    #534 新增的 `RENDER_FAILED` 訊號對這條路徑**不會觸發**，所以要在儲存時擋。
    """

    @pytest.mark.parametrize("bad", ["主旨\n第二行", "主旨\r", "主旨\r\nBcc: x@evil.com"])
    async def test_換行與_cr_被擋下(self, bad: str) -> None:
        e = _err(subject=bad)
        assert e.status_code == 422
        assert e.error_code == "DP_MAIL_012"

    @pytest.mark.parametrize("ok", ["主旨\x00", "主旨 ", "主旨\x1f"])
    async def test_其他控制字元仍放行(self, ok: str) -> None:
        """⚠️ **刻意**只擋 `\n` / `\r`。

        實測 `NUL` / `U+2028` / 其他控制字元在主旨裡照樣寄得出去
        （`EmailMessage.as_bytes()` 不拋錯），擋它們等於擋掉本來能用的內容——
        那會是「守門擋了它不該擋的」，與本 issue 要修的方向相反。

        這條在日後有人想「順手把 `_SUBJECT_TRANS` 整套搬過來」時會紅，並指向此處理由。
        """
        ensure_renderable(subject=ok, body="內文", variables=_VARS)

    async def test_內文含換行不受影響(self) -> None:
        """正向錨點：內文本來就該允許換行，別讓主旨那道守門誤傷它。"""
        ensure_renderable(subject="主旨", body="第一行\n第二行\n{reason}", variables=_VARS)


class Test巢狀格式規格:
    """`{a:{b}}` 在探針與實跑下必須得到**相同**答案（#534 Security MEDIUM-1）。

    stdlib 會先把巢狀的 `format_spec` 遞迴渲染完才交給 `format_field`。修正前：探針代入空字串
    → spec 變成 `""` → 放行；真實值非空 → `format_field` 擋下。於是**儲存時放行、寄送時
    `RENDER_FAILED`**，正是本 issue 要消滅的那種靜默失敗——而我原本在 docstring 與
    FR-DP-US9-10 都宣稱「定義上不可能不一致」。

    修法是在 `_SafeFormatter.parse`（遞迴**之前**、看得到原始 spec）擋下，於是與值無關。
    """

    @pytest.mark.parametrize("bad", ["{doc_name:{reason}}", "{doc_name!r:{reason}}", "{doc_name:{doc_name}}"])
    async def test_巢狀規格在儲存時就被擋(self, bad: str) -> None:
        assert _err(body=bad).error_code == "DP_MAIL_011"

    @pytest.mark.parametrize("bad", ["{doc_name:{reason}}", "{doc_name:>10}"])
    async def test_實跑也一樣擋(self, bad: str) -> None:
        """與上一條成對：只驗「儲存擋下」證明不了兩邊一致——也可能是檢核過嚴。"""
        from app.dp.notify.service import _render

        with pytest.raises(ValueError):
            _render(bad, {"author_name": "甲", "doc_name": "乙", "reason": "丙"})
