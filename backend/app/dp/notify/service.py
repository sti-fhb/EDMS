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

# 收件人單次上限（防呼叫方 bug / 濫用一次寫入海量 outbox 拖垮 worker，對齊 TBMS 慣例）
_MAX_RECIPIENTS = 50


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

    def get_field(self, field_name: str, args, kwargs):
        if not field_name.isidentifier():
            raise ValueError(f"範本佔位僅允許具名變數，禁屬性 / 索引 / 位置: {{{field_name}}}")
        return kwargs[field_name], field_name

    def format_field(self, value, format_spec: str) -> str:
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
            logger.warning("通知範本預覽渲染失敗 module=%s template_code=%s: %s", module, template_code, exc)
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
            SendResult：queued_count（排入 PENDING 的收件人數）、skipped_reason（略過原因或 None）。

        Raises:
            AppError: template_code 不存在（404 / DP_MAIL_001）。
        """
        if len(recipients) > _MAX_RECIPIENTS:
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
            return SendResult(queued_count=0, skipped_reason=None)

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
        """逐收件人寫一列 DP_EMAIL_LOG（渲染快照 + 狀態）。"""
        now = utcnow()
        for recipient in recipients:
            await self._repo.add_log(
                db,
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
                },
            )
