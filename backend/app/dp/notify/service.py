"""通知發送服務（SRVDP002）。

全 EDMS 唯一發信入口（research §8）：各模組傳 template_code + 收件人，服務渲染範本、
逐收件人寫入 outbox（DP_EMAIL_LOG，PENDING）即返回，不同步寄送、不阻塞呼叫方交易；
實際寄送由常駐 worker（見 worker.py）非同步執行。模組不自持範本、不自建佇列、不直連 SMTP。
"""

import logging
import string

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.utils import utcnow
from app.dp.notify.repository import NotifyRepository
from app.dp.notify.schemas import RenderedMail, SendResult

logger = logging.getLogger(__name__)

# 系統作業建立者（DP_EMAIL_LOG 標準欄位 CREATED_USER）；實際觸發模組記於 CALLER_MODULE。
_SYSTEM_USER = "SYSTEM"

#: `ensure_renderable` 的對外訊息（不得嵌入佔位名稱，見該函式註解）。
_UNRENDERABLE_MSG = "範本內容含無法代入的變數，請確認僅使用「可用變數」所列的名稱"

#: `ensure_renderable` 的主旨單行檢核訊息（#534）。
_SUBJECT_MULTILINE_MSG = "主旨不得含換行，請改為單行"

#: 單次 `send_email` 的收件人上限（對齊 TBMS 慣例）。**公開常數**：傳多人清單的呼叫方
#: 需據此分批，故由 `app.services` 一併匯出（#563）。
#:
#: ⚠️ 原註解寫它「防濫用一次寫入海量 outbox 拖垮 worker」——**那個目的從來沒有達成**：
#:
#:   - 它沒有任何時間或累積維度，只看單次呼叫的 `len(recipients)`。呼叫方自己寫個迴圈
#:     就能寫到同樣的量，而呼叫方全是第一方程式碼——「自己繞得過」的限制不是信任邊界。
#:   - 超過上限時的結果不是「少寫一些」，而是**整個呼叫方交易 rollback**。也就是說它
#:     從來不會把大量通知變小，只會把它變成硬失敗（#563 正是這個失敗：可見對象超過
#:     50 人的文件因此發布不了）。
#:   - 真正的流量控制在**寄送端**：`worker.py` 依 `DP_PARAM` 的 `MAIL/RATE_PER_MIN`
#:     （保底 60）限制每輪取件量，輪距再搭配控制速率。那一道與本上限彼此獨立，outbox
#:     多幾列不會讓 worker 多寄，只會讓佇列變長。
#:
#: 所以本上限的實際效用只剩：擋住呼叫方**誤把整張表當收件人清單**這類 bug，讓它當場 422
#: 而不是安靜地寫出十萬列。保留它是刻意的——ET 與 DP 自身的呼叫都在其下運作（皆為單人），
#: 移除屬跨模組語意變更。
#:
#: ⚠️ 連帶要知道：DM 自 #563 起會分批，於是**單一請求可達的 outbox 寫入量從 0（硬失敗）
#: 變成 N**（N＝可見對象相符的閱覽者數）。那不是本上限放寬的結果，是它原本就擋不住、
#: 只是以 rollback 掩蓋了。真正的上界是機構內 `DM_VIEWER` 人數。
#:
#: ⚠️ 本值必須 ≥ 1：呼叫方以它當 `range()` 步長分批，設為 0 會在分批處拋 `ValueError`
#: （未處理例外、不是 `AppError`）。目前硬編碼故不可能發生；若日後改為 `DP_PARAM` 可設定，
#: 需在讀取處補一道下界守門。
MAX_RECIPIENTS = 50


# 代入值中須剝除的字元（#225）。**主旨與內文用不同嚴格度**，因為兩者對「換行」的容忍度不同。
#
# 共同剝除：C0（除 TAB / LF）、DEL、C1 全段、U+2028、U+2029。C1 與 U+2028 / U+2029 是 review
# 抓到的缺口——`str.splitlines()` 與 Python 的 email 模組都把 U+0085 / U+2028 / U+2029 當斷行
# 邊界（UAX #14 class BK），只剝 C0 等於防線只做一半。
#
# **內文保留 LF / TAB**：DM 的退回 / 廢止理由是真的多行使用者輸入（`dm/review/center_service.py`
# 與 `dm/obsolete/service.py` 把它當範本參數傳入，前端輸入框為 multiline）。在此剝換行會把理由
# 壓平——那是弄壞別的模組的功能。CRLF 因此被正規化為 LF：丟 CR、留 LF，多行結構保留。
#
# **主旨連 LF 一起剝**（`_SUBJECT_TRANS`）：主旨本質單行，剝掉不會弄壞任何模組，而保留會壞事——
# stdlib 的 `EmailMessage.__setitem__` 對含斷行的 header 直接拋 `ValueError`（實測連 U+2028 /
# U+0085 都擋），該例外被 worker 的 except 吞掉、`retry_count` 累加到上限後標 FAILED。也就是說
# 一個含換行的主旨參數會讓**該批通知信永久寄不出去**，而錯誤只留在 `DP_EMAIL_LOG.ERROR_MSG`。
#
# ⚠️ 這條路徑**現在就可觸發**：DM 的 9 支內建範本主旨含 `{doc_name}` 佔位（見
# `alembic/versions/..._dm_seed_templates_params_into_dp.py`），而 `doc_name` 只做 strip、無 pattern，
# 任何已認證的 DM 編輯者把文件命名為含換行即可。本層剝除是止血；`doc_name` 的輸入驗證屬 DM 範圍。
#
# 「內文被插入假訊息」則由**輸入端**擋（姓名見 `core/schema_types.py` 的 `SafeNameStr`）：姓名本質
# 單行、理由本質多行，只有輸入端分得清這個差別；本層只做與信件結構有關的防護。
_SHARED_STRIP = [*range(0x00, 0x09), *range(0x0B, 0x20), *range(0x7F, 0xA0), 0x2028, 0x2029]
_BODY_TRANS = str.maketrans({c: None for c in _SHARED_STRIP})
_SUBJECT_TRANS = str.maketrans({c: None for c in [*_SHARED_STRIP, 0x0A]})


def _safe_log(exc: Exception) -> str:
    """把例外訊息整理成可安全寫進 log 的單行字串（#534）。

    `_SafeFormatter.get_field` 的錯誤訊息把 `field_name` **原樣**嵌入，而 `field_name` 是
    `{` 與第一個 `:` / `!` / `}` 之間的任意字元——**含換行**。`_BodyStr` 允許換行、長度上限
    10000，於是一次被拒的儲存可以：

    - **偽造 log 行**：在內文貼入一個以換行開頭的佔位名，輸出就會多出一行看起來像系統紀錄
      的文字（例如偽造一筆 `CRITICAL ... 稽核已清除`），污染 log 聚合與事後鑑識。
    - **灌量**：`{` 之後接上萬個換行再 `}`，單一請求即可產生近萬行 log。

    ⚠️ 這是**被拒絕、從未落地**的內容——DB 裡查不到，只有 log 留下。`send_email` 對同一份
    例外訊息本來就有 `[:500]` 截斷（寫進 `DP_EMAIL_LOG.ERROR_MSG`），log 路徑原本漏了這一刀。

    Returns:
        換行與歸位字元轉為可見跳脫、截斷至 200 字元的單行字串。
    """
    flattened = str(exc).replace("\r", "\\r").replace("\n", "\\n")
    return flattened[:200]


class _SafeFormatter(string.Formatter):
    """安全範本格式器：僅允許具名佔位 `{var}`，封鎖範本注入攻擊面。

    範本（SUBJECT/BODY）由 US9 後台可編輯，等同不受信任的 format string；原生 str.format
    允許屬性 / 索引存取（`{x.__class__.__globals__...}` 可讀 JWT_SECRET_KEY）與格式規格
    （`{v:>200000000}` 可 OOM 常駐 worker）。本格式器：
    - 佔位僅接受合法識別字（拒 `{0}` / `{}` / `{a.b}` / `{a[0]}`）
    - 禁格式規格（拒 `{v:...}`）
    - 值一律 str() 後代入（即便呼叫方誤傳非 str 物件，亦無屬性存取路徑）
    - 值中的控制 / 斷行字元剝除，主旨比內文嚴格（`single_line`），見上方常數（#225）

    Args:
        single_line: True 用於主旨（連 LF 一併剝）；False 用於內文（保留 LF / TAB）。
    """

    def __init__(self, *, single_line: bool) -> None:
        super().__init__()
        self._trans = _SUBJECT_TRANS if single_line else _BODY_TRANS

    def parse(self, format_string):
        """在**遞迴展開之前**擋下任何格式規格（#534）。

        `format_field` 本來就會拒絕非空的 `format_spec`，但它拿到的是**已經遞迴渲染完**的
        字串——於是巢狀寫法 `{a:{b}}` 的結果取決於值：`b` 代入空字串時 spec 變成 `""`、
        放行；代入非空值時才被擋。

        這讓「以空值探針實跑一次渲染」的檢核（`ensure_renderable`）與真正寄送時的渲染**對
        同一份範本給出不同答案**：儲存時放行、寄送時 `RENDER_FAILED`——正是 #534 要消滅的
        那種靜默失敗。

        `Formatter.parse` 看得到**原始**的 `format_spec`（`{a:{b}}` 給的是 `"{b}"`），在此
        擋下即與值無關，兩邊恆一致。

        ⚠️ 安全面向不受影響：`{a:{b}}` 在舊行為下也到不了 padding / OOM（內層渲染完仍是
        非空 spec，照樣被 `format_field` 擋）。本改動關的是**可用性**破口。
        """
        for literal_text, field_name, format_spec, conversion in super().parse(format_string):
            if format_spec:
                raise ValueError("範本佔位不得含格式規格")
            yield literal_text, field_name, format_spec, conversion

    def get_field(self, field_name: str, args, kwargs):
        if not field_name.isidentifier():
            raise ValueError(f"範本佔位僅允許具名變數，禁屬性 / 索引 / 位置: {{{field_name}}}")
        return kwargs[field_name], field_name

    def format_field(self, value, format_spec: str) -> str:
        # 保留此道（縱深防禦）：`parse` 已在上游擋掉所有非空 spec，正常情況下這裡恆為 `""`。
        # 若日後有人改動 `parse`，這一道仍會攔住。
        if format_spec:
            raise ValueError("範本佔位不得含格式規格")
        return str(value).translate(self._trans)


_formatter = _SafeFormatter(single_line=False)
_subject_formatter = _SafeFormatter(single_line=True)


def _render(text: str, params: dict[str, str], *, single_line: bool = False) -> str:
    """以 params 代入範本具名佔位（`{var}`）。

    範本需要而 params 未提供 → KeyError；範本含屬性 / 索引 / 格式規格 / 未閉合大括號 → ValueError。
    兩者由呼叫端捕捉標該批 FAILED（不外拋阻斷呼叫方）。

    Args:
        single_line: 渲染**主旨**時傳 True——代入值連 LF 一併剝除，避免含換行的參數讓 stdlib
            設定 header 時拋錯、使該批信永久 FAILED（見上方常數說明）。
    """
    formatter = _subject_formatter if single_line else _formatter
    return formatter.vformat(text, (), params)


def declared_variable_names(variables: str | None) -> set[str]:
    """從 `VARIABLES` 欄取出變數名集合。

    ## ⚠️ 本欄有**三種格式並存**（2026-10-12 對全部 23 支範本實測）

    | 模組 | 格式 | 實例 |
    |---|---|---|
    | DM | 裸小寫識別字 | `reviewer_name,pending_count,pending_list` |
    | **DP** | 識別字 + **全形括號說明**，逗號後另有空格 | `user_name（使用者姓名）, activate_link（啟用連結）` |
    | ET | 裸**大寫**識別字 | `USER_NAME,COURSE_NAME` |

    所以**不能**直接把整段 token 當變數名——那會讓 DP 的 5 支範本算出
    `user_name（使用者姓名）` 這種 key，與內文的 `{user_name}` 永遠對不上，於是管理者連只改
    主旨都會被 422 擋死。這不是假設：#534 的檢核第一版正是這樣寫的，`ensure_renderable`
    對 DP 全部 5 支可維護範本回 422，而**沒有任何既有測試會紅**。

    DP 那種格式是刻意的——前端 `TemplateForm.tsx` 把本欄**原樣顯示**為「可用變數：…」，
    中文說明對管理者有用。該改的是解析，不是資料。

    取「第一個 `（` 或 `(` 之前的部分」即可涵蓋三種。說明文字中目前沒有全形逗號（已實測），
    故以 `,` 切是安全的；日後若有人寫出帶逗號的說明，本函式會把它切碎成無效名稱 →
    `ensure_renderable` 會把合法範本誤判為不合法。下方的全庫守門測試會在那時變紅。

    Args:
        variables: `DP_NOTIFY_TEMPLATE.VARIABLES` 原始值；可為 None。

    Returns:
        變數名集合；無宣告時回空集合。
    """
    names: set[str] = set()
    for token in (variables or "").split(","):
        name = token.split("（", 1)[0].split("(", 1)[0].strip()
        if name:
            names.add(name)
    return names


def ensure_renderable(*, subject: str, body: str, variables: str | None) -> None:
    """儲存前驗證範本的佔位皆可渲染；不符拋 `AppError(422, DP_MAIL_011)`（#534）。

    ## 為何是「跑一次 `_render`」而不是另寫一份檢核

    DP04 可編輯的主旨 / 內文裡，`{變數}` 是一份**與呼叫端的契約**，而在 #534 之前沒有任何
    一端在守它：管理者把 `{user_name}` 打成 `{user_nam}`，該範本從此每次寄送都失敗——
    `send_email` 整批寫 `FAILED` 後回 `queued_count=0` 且**不外拋**，而 `DP_EMAIL_LOG`
    沒有任何畫面在顯示。發生時沒人知道、發生後沒地方看。

    ⚠️ **刻意不另寫正則**。兩份規則遲早分歧，而分歧的方向正好是最糟的那個：「檢核放行、
    渲染失敗」——那等於把檢核做成了裝飾品。此處以該範本宣告的 `VARIABLES` 組一個空值探針
    dict，**直接呼叫 `_render`**，於是檢核與渲染共用同一份解析。

    ⚠️ 「共用」不自動等於「結果相同」：探針值是空字串、真實值不是，而 stdlib 會先把巢狀的
    `format_spec` 遞迴渲染完才交給 `format_field`。`{a:{b}}` 因此一度是「儲存放行、寄送
    `RENDER_FAILED`」（#534 Security MEDIUM-1 實測）。已於 `_SafeFormatter.parse` 根治——
    在遞迴**之前**擋下所有非空 spec，兩邊才真的與值無關。

    一次呼叫即涵蓋 `_SafeFormatter` 的全部拒絕路徑：

    | 壞寫法 | 由哪一道攔下 |
    |---|---|
    | `{user_nam}`（未宣告）| `get_field` 的 `kwargs[field_name]` → `KeyError` |
    | `{a.b}` / `{a[0]}` / `{0}` / `{}` | `get_field` 的 `isidentifier()` → `ValueError` |
    | `{v:>200000000}` | `format_field` 的 `format_spec` → `ValueError` |
    | 未閉合的 `{` | stdlib `Formatter.parse` → `ValueError` |

    ⚠️ **HTML inline CSS 的 `{color:red}` 走哪一條取決於 `color` 有沒有被宣告**（實測）：
    未宣告 → stdlib 先把它拆成 `field_name="color"` / `format_spec="red"`，`color` 是合法
    識別字，於是卡在 `kwargs["color"]` → **`KeyError`**；已宣告 → 過了 `get_field`，才卡在
    `format_field` 的 `format_spec` → `ValueError`。兩條都擋得住，但**別把它記成「未閉合
    大括號」那一類**——它的大括號是閉合的，`:` 才是問題。

    主旨與內文分別驗——兩者走不同的 formatter（主旨連 LF 一併剝），只驗一邊會漏。

    ⚠️ **`VARIABLES` 是上界、不是必用清單**：少用宣告的變數不算錯（探針有值即可渲染），
    多用沒宣告的才是錯。

    ⚠️ **本檢核上線後，新增變數的流程被強制排序**：先改程式傳新 params、再改 migration 更新
    `VARIABLES`，管理者才改得動內文。第三步會被第二步擋住——那是對的，但要寫進維運文件，
    否則會變成「管理者改不了內文」的客訴。

    Args:
        subject: 待存的主旨。
        body: 待存的內文。
        variables: 該範本的 `VARIABLES` 欄原始值；解析見 `declared_variable_names`（**三種格式並存**）。

    Raises:
        AppError: 任一處無法渲染（422 `DP_MAIL_011`）。
    """
    # 主旨的**範本文字本身**不得含換行 / CR（#534）。
    #
    # ⚠️ `_SUBJECT_TRANS` 的剝除只作用於**代入值**（`format_field` 內），不作用於範本文字；
    # `_SubjectStr` 的 `strip_whitespace` 也只剝頭尾。於是管理者可以把多行主旨存進去，
    # 渲染正常、`send_email` 回報 `queued_count=N` 看起來完全成功，**失敗發生在 worker**：
    # stdlib 設 header 時拋「Header values may not contain linefeed or carriage return」，
    # 而 `worker.py` 的 `except Exception` 吞掉後只把訊息寫進 `DP_EMAIL_LOG.ERROR_MSG`、
    # **連一行 log 都沒有**。那比本 issue 要修的缺陷更隱形。
    #
    # ⚠️ **刻意只擋 `\n` / `\r`，不套用 `_SUBJECT_TRANS` 的完整字元集**：實測 `NUL` 與
    # `U+2028` 在主旨裡照樣寄得出去（`EmailMessage.as_bytes()` 不拋錯），擋它們等於擋掉
    # 本來能用的內容。守門只擋驗證過會死的那些。
    if "\n" in subject or "\r" in subject:
        raise AppError(status_code=422, detail=_SUBJECT_MULTILINE_MSG, error_code="DP_MAIL_012")

    probe = {name: "" for name in declared_variable_names(variables)}
    try:
        _render(subject, probe, single_line=True)
        _render(body, probe)
    except (KeyError, ValueError, IndexError) as exc:
        # 例外訊息**不外流**：它含範本內部的佔位名稱，屬 schema 細節（sti-error-codes 明定
        # error_message 不得嵌入動態值）。詳情留在伺服器日誌——比照 `render_preview`。
        logger.warning("通知範本佔位檢核失敗: %s", _safe_log(exc))
        raise AppError(status_code=422, detail=_UNRENDERABLE_MSG, error_code="DP_MAIL_011") from exc


def _channel_allows_email(channel: str) -> bool:
    """僅 EMAIL / BOTH 寄 Email；MSG（純站內訊息、模組自理）不寄。"""
    return channel in ("EMAIL", "BOTH")


class NotifyService:
    """SRVDP002 發信服務（跨模組經 app.services 呼叫）。"""

    def __init__(self, repository: NotifyRepository | None = None) -> None:
        self._repo = repository or NotifyRepository()

    async def render_preview(
        self,
        db: AsyncSession,
        *,
        template_code: str,
        module: str,
        params: dict[str, str],
    ) -> RenderedMail:
        """渲染範本並回傳主旨 / 內文，**不寫入 outbox、不寄送**（#273）。

        給「寄出前先讓使用者看一眼」的情境用。ET 之 Email 邀請要求於下一步顯示依統一
        範本渲染之預覽（FR-ET-US8-07），而範本與 `_SafeFormatter` 皆為本模組內部——
        呼叫方自行讀 `DP_NOTIFY_TEMPLATE` 會違反 `sti-backend-boundaries`，故由此提供。

        與 `send_email` 的差異只有「不落 outbox」；渲染規則（主旨剝換行、內文保留 LF、
        佔位僅允許具名變數）與**可否寄出之前置條件**（範本存在、已啟用、CHANNEL 允許
        Email）完全共用，故預覽所見即寄出所得。

        `CHANNEL` 這道檢查不可省：非系統範本之 `CHANNEL` 可由管理者於後台改為 `MSG`，
        此時 `send_email` 會回 `skipped_reason='CHANNEL_NOT_EMAIL'`、`queued_count=0`。
        若預覽不檢查，使用者會看到一封完整的信、按下寄出後卻全部落入失敗清單。

        **渲染失敗於此拋錯而非靜默記 FAILED**：`send_email` 吞掉渲染錯誤是為了不阻斷
        呼叫方的業務交易（信寄不出去不該讓文件送審失敗）；預覽沒有業務交易可保護，
        它的**唯一產出**就是那段文字，靜默回空字串只會讓使用者看到一封空白的信卻以為
        正常。

        Args:
            template_code: DP_NOTIFY_TEMPLATE.TEMPLATE_CODE。
            module: 範本歸屬 MODULE（DP / ET / DM）。
            params: 範本變數；key 須逐字對齊範本佔位。

        Returns:
            RenderedMail：渲染後之 subject / body。

        Raises:
            AppError: 範本不存在（404 / DP_MAIL_001）、已停用（409 / DP_MAIL_006）、
                渲染失敗（422 / DP_MAIL_007，多為 params 缺 key）、
                CHANNEL 非 Email（409 / DP_MAIL_008）。
        """
        template = await self._repo.get_template(db, module, template_code)
        if template is None:
            raise AppError(status_code=404, detail="通知範本不存在", error_code="DP_MAIL_001")
        if not template.is_enabled:
            # 停用的範本寄不出去，預覽卻給出內容會讓使用者按下寄出後一無所獲。
            raise AppError(status_code=409, detail="通知範本已停用", error_code="DP_MAIL_006")
        if not _channel_allows_email(template.channel):
            raise AppError(status_code=409, detail="通知範本未設定為 Email 發送", error_code="DP_MAIL_008")
        try:
            subject = _render(template.subject, params, single_line=True)
            body = _render(template.body, params)
        except (KeyError, ValueError, IndexError) as exc:
            # 例外訊息**不外流**：它含範本內部的佔位名稱，屬 schema 細節（sti-error-codes
            # 明定 error_message 不得嵌入動態值）。詳情留在伺服器日誌。
            logger.warning("通知範本預覽渲染失敗 module=%s template_code=%s: %s", module, template_code, _safe_log(exc))
            raise AppError(status_code=422, detail="通知範本內容無法產生預覽", error_code="DP_MAIL_007") from exc
        return RenderedMail(subject=subject, body=body)

    async def send_email(
        self,
        db: AsyncSession,
        *,
        recipients: list[str],
        template_code: str,
        module: str,
        params: dict[str, str],
        caller_module: str,
    ) -> SendResult:
        """渲染範本並逐收件人寫入 outbox（PENDING），即返回；不同步寄送。

        於呼叫方交易內執行（同一 db session、只 flush）；呼叫方 MUST 於業務 commit 後呼叫。

        Args:
            db: 呼叫方 AsyncSession。
            recipients: 收件人 Email 清單（逐人一列 outbox）。
            template_code: DP_NOTIFY_TEMPLATE.TEMPLATE_CODE。
            module: 範本歸屬 MODULE（DP / ET / DM）。
            params: 範本變數。
            caller_module: 呼叫方模組（記入 CALLER_MODULE）。

        Returns:
            SendResult：queued_count（排入 PENDING 的收件人數）、skipped_reason。
            後者四種值：`TEMPLATE_DISABLED` / `CHANNEL_NOT_EMAIL`（管理者**有意**的設定，
            不寫 outbox）、`RENDER_FAILED`（**缺陷**，整批寫 FAILED，#534）、`None`
            （成功，或收件人清單本來就是空的）。

        Raises:
            AppError: template_code 不存在（404 / DP_MAIL_001）。
        """
        if len(recipients) > MAX_RECIPIENTS:
            raise AppError(status_code=422, detail="收件人數超過單次上限", error_code="DP_MAIL_002")
        template = await self._repo.get_template(db, module, template_code)
        if template is None:
            raise AppError(status_code=404, detail="通知範本不存在", error_code="DP_MAIL_001")
        if not template.is_enabled:
            return SendResult(queued_count=0, skipped_reason="TEMPLATE_DISABLED")
        if not _channel_allows_email(template.channel):
            return SendResult(queued_count=0, skipped_reason="CHANNEL_NOT_EMAIL")

        # 渲染一次（同批 params 相同）；渲染失敗 → 整批寫 FAILED 記錄、不拋錯不阻斷呼叫方（FR-06）。
        # KeyError：範本需要的變數缺漏；ValueError/IndexError：範本含未跳脫大括號（如 HTML inline CSS）
        # 或位置佔位——一律視為渲染失敗，不得外拋讓呼叫方交易 500。
        try:
            subject = _render(template.subject, params, single_line=True)
            body = _render(template.body, params)
        except (KeyError, ValueError, IndexError) as exc:
            error_msg = f"範本渲染失敗: {exc}"[:500]
            await self._write_logs(db, recipients, module, template_code, caller_module, "", "", "FAILED", error_msg)
            # #534：原本回 `None`，而 `None` 同時也是「成功」與「收件人為空」的值——三種情況
            # 回傳一模一樣，呼叫端即使想檢查也分不出哪個是故障。具名之後：兩個「刻意跳過」
            # （TEMPLATE_DISABLED / CHANNEL_NOT_EMAIL）、一個「缺陷」（RENDER_FAILED）、
            # 一個「無事發生」（None）彼此可區分。
            return SendResult(queued_count=0, skipped_reason="RENDER_FAILED")

        await self._write_logs(db, recipients, module, template_code, caller_module, subject, body, "PENDING", None)
        return SendResult(queued_count=len(recipients), skipped_reason=None)

    async def _write_logs(
        self,
        db: AsyncSession,
        recipients: list[str],
        module: str,
        template_code: str,
        caller_module: str,
        subject: str,
        body: str,
        status: str,
        error_msg: str | None,
    ) -> None:
        """逐收件人寫一列 DP_EMAIL_LOG（渲染快照 + 狀態），整批一次 flush（#563）。"""
        now = utcnow()
        await self._repo.add_logs(
            db,
            [
                {
                    "module": module,
                    "template_code": template_code,
                    "caller_module": caller_module,
                    "recipient": recipient,
                    "subject": subject,
                    "body": body,
                    "status": status,
                    "error_msg": error_msg,
                    "created_user": _SYSTEM_USER,
                    "created_date": now,
                }
                for recipient in recipients
            ],
        )
