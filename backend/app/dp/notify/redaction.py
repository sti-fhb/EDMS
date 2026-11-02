"""含一次性連結之系統信的 outbox 遮罩政策（#50）。

`DP_EMAIL_LOG.BODY` 為渲染後快照，含一次性明文連結時會抵銷 `DP_PWD_RESET` 只存 token 雜湊的
縱深防禦。本模組集中定義三件事，供三個執行點共用、不各寫一份：

| 定義 | 使用處 |
|---|---|
| `ONE_TIME_LINK_TEMPLATES`（範本 → 時效參數）| worker 轉 SENT 時遮罩；SCHDP001 遮罩逾時效 FAILED 列 |
| `ONE_TIME_LINK_VARIABLES`（連結類變數）| DP04 存檔時禁止放進主旨（`service.ensure_subject_without_link`）|
| `REDACTED_BODY`（遮罩字串）| 上述兩個遮罩點 + alembic 回溯 migration（後者寫死、不 import）|

## SA 裁示（2026-10-29 / 2026-11-02）

1. 寄出（SENT）後遮罩 BODY；與 SENT 同交易。PENDING 保留原文（重試需要）。
2. FAILED 為終態、無重試路徑：連結過了時效即失效，保留原文已無用途，**超過時效後遮罩**；
   併入 SCHDP001 平台每日作業，不另開排程。
3. 主旨不遮罩（會出現在寄送紀錄列表與 log，事後遮罩擋不完）→ DP04 存檔時禁止連結類變數。

⚠️ 前端 `frontend/src/dp/notify/schemas.ts` 的 `ONE_TIME_LINK_VARIABLES` 是本處變數清單的
鏡像（Zod 即時提示用），新增連結類變數時兩處一起改；權限邊界在後端（`DP_MAIL_013`）。
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import utcnow
from app.dp.notify.repository import NotifyRepository
from app.dp.params.service import ParamService

logger = logging.getLogger(__name__)

#: 遮罩後的 BODY 固定標記（非空字串，以免與渲染失敗列的空 BODY 混淆）。
#:
#: ⚠️ 此字串已凍結於 alembic 回溯 migration 04fc1cf07681 與 b27739aa4ac6（寫死、不 import）：
#: 日後若改這裡，既有已遮罩列不會跟著改，兩種標記會並存——要改請另寫 migration 一併更新。
REDACTED_BODY = "[已遮罩：本信含一次性連結，寄出後清除原文]"

#: 含一次性連結的系統信 → 該連結的時效參數 `(DP_PARAM.PARAM_ID, PARAM_KEY)`。
#:
#: 以 (MODULE, TEMPLATE_CODE) 為鍵——ET / DM 同名代碼不受影響。四支皆為 IS_SYSTEM 種子範本，
#: 代碼固定、不可新增 / 刪除，故不必每輪查範本表。
#:
#: 時效參數取自各寄信端實際讀的那一個（改動寄信端讀的參數時，這裡要一起改）：
#:
#: | 範本 | 寄信端 | 參數 |
#: |---|---|---|
#: | PWD_RESET | `dp/user/forgot_service.py` | `LOGIN.RESET_TOKEN_TTL_MIN` |
#: | EMAIL_CHANGE_VERIFY | `dp/user/email_change_service.py` | `LOGIN.EMAIL_CHANGE_TTL_MIN` |
#: | ACCOUNT_VERIFY | `dp/user/register_service.py`、`dp/user/verify_service.py`（補寄）| `LOGIN.RESET_TOKEN_TTL_MIN` |
#: | ACCOUNT_INVITE | `dp/users/service.py`（`_invite_ttl_min`，邀請與重寄）| `LOGIN.RESET_TOKEN_TTL_MIN` |
ONE_TIME_LINK_TEMPLATES: dict[tuple[str, str], tuple[str, str]] = {
    ("DP", "PWD_RESET"): ("LOGIN", "RESET_TOKEN_TTL_MIN"),
    ("DP", "EMAIL_CHANGE_VERIFY"): ("LOGIN", "EMAIL_CHANGE_TTL_MIN"),
    ("DP", "ACCOUNT_VERIFY"): ("LOGIN", "RESET_TOKEN_TTL_MIN"),
    ("DP", "ACCOUNT_INVITE"): ("LOGIN", "RESET_TOKEN_TTL_MIN"),
}

#: 時效參數讀取失敗時的保底值——與各寄信端的 `_DEFAULT_TTL_MIN` 相同（寄信端讀不到參數時
#: 也是用 30 分鐘簽 token，兩邊一致才不會在連結仍有效時就判定逾時）。
_DEFAULT_TTL_MIN = 30

#: 一次性連結類變數（寄信端以 token 組出的連結）。DP04 存檔時禁止出現在主旨。
#:
#: 只收**一次性 token 連結**：ET `COURSE_URL`、DM `dashboard_link` 是一般頁面連結，持有它
#: 不能做任何事（仍需登入），放進主旨不構成 #50 的風險，故不列入。
ONE_TIME_LINK_VARIABLES = frozenset({"reset_link", "verify_link", "activate_link"})


def redact_after_sent(module: str, template_code: str) -> bool:
    """此信寄出成功（轉 SENT）時是否須遮罩 BODY。"""
    return (module, template_code) in ONE_TIME_LINK_TEMPLATES


async def redact_expired_failed(
    db: AsyncSession,
    *,
    now: datetime,
    repository: NotifyRepository | None = None,
    params: ParamService | None = None,
) -> int:
    """遮罩**建立後已超過連結時效**的 FAILED 列 BODY，回傳遮罩筆數（SCHDP001，#50 裁示 2）。

    逾時判定以 outbox 列的 `CREATED_DATE` 起算：token 與 outbox 列在同一交易內產生，
    `CREATED_DATE + TTL` 即連結失效時點。TTL 讀**目前**參數值——
    - 參數調大過：比實際失效晚遮，只是晚一點，不會在連結有效時遮；
    - 參數調小過：比實際失效早遮，但列已是 FAILED 終態（不會再寄），提早遮罩無副作用。

    不 commit（交易由呼叫方負責，見 `redact_expired_failed_mails`）。

    Args:
        db: AsyncSession。
        now: 目前時間（測試可注入）。
        repository: 測試注入用。
        params: 測試注入用。
    """
    repo = repository or NotifyRepository()
    param_service = params or ParamService()
    ttl_cache: dict[tuple[str, str], int] = {}
    redacted = 0
    for (module, template_code), ttl_param in ONE_TIME_LINK_TEMPLATES.items():
        if ttl_param not in ttl_cache:
            ttl_cache[ttl_param] = await param_service.get_int_param(db, *ttl_param, _DEFAULT_TTL_MIN)
        redacted += await repo.redact_failed_created_before(
            db,
            module=module,
            template_code=template_code,
            cutoff=now - timedelta(minutes=ttl_cache[ttl_param]),
            redacted_body=REDACTED_BODY,
            now=now,
        )
    return redacted


async def redact_expired_failed_mails(db: AsyncSession) -> int:
    """SCHDP001 第④批：遮罩逾連結時效的 FAILED 信件並 commit；失敗 rollback、記 log、回 0。

    **不往外拋**——與 SCHDP001 其餘批次同一容錯姿態（`UsersService.purge_expired_pending`）：
    否則單批失敗會讓 handler 的彙總 log 整條不寫，且 scheduler 的 job 級 catch-all 會把
    「其餘批次成功、本批失敗」記成整個 SCHDP001 失敗。

    部署後第一次執行即涵蓋既有 FAILED 列，故不另寫回溯 migration。
    """
    try:
        redacted = await redact_expired_failed(db, now=utcnow())
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("SCHDP001 遮罩逾時效寄送失敗信件失敗")
        return 0
    return redacted
