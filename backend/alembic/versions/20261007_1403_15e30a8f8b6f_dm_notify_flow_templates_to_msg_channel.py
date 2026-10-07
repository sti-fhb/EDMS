"""dm notify flow templates to msg channel (#554)

Revision ID: 15e30a8f8b6f
Revises: 1e57d1db82b2
Create Date: 2026-10-07 14:03:00.000000

DM 簽核流程通知改為站內呈現，不再寄 Email（使用者裁示，#554）。

異動說明：
- 影響 Table：DP_NOTIFY_TEMPLATE（更新 5 列之 CHANNEL，不新增 / 不刪除列）
- 5 支：DOC_SUBMIT / DOC_REJECT / OBS_SUBMIT / OBS_APPROVE / OBS_REJECT，由 BOTH → MSG
- 皆為既有列之 UPDATE，idempotent；downgrade 還原為 BOTH

⚠️ **改成 MSG 不是「換一個管道送」，是「不送了」。** 平台沒有站內訊息佇列
（`dm/notify/service.py`：「站內訊息之呈現於 US9 個人專區以事件動態實作」）。使用者看得到
是因為「我的文件動態」與「簽核中心」本來就畫得出來，中文標籤由前端 `dm/personal/schemas.ts`
自己映射（核准發布 / 已退回 / 已撤回 / 廢止待簽核），**不讀本表的主旨與內文**。

👉 因此這 5 支（連同既有的 AUTO_REMIND / SUBMIT_WITHDRAWN）的 SUBJECT / BODY 自本次起
**沒有任何讀取端**，留著是給未來的站內訊息佇列。DP04 亦自本次起只列 CHANNEL='EMAIL' 的範本。

**不在本次改動之列**：
- DOC_PUBLISH 維持 EMAIL——其收件人含「可見對象相符閱覽者」，而閱覽者沒有 DM_REVIEW 列，
  「我的文件動態」對他們是空的，DM01 文件庫也無未讀 / 新發布標示。整支改 MSG 會讓閱覽者
  那一半整則消失。改為於 repository 層不再寄給撰寫者（撰寫者由動態「核准發布」承接）。
- KPI_WEEKLY / UNREAD_REMIND 本就是 EMAIL，與簽核流程無關。
"""

from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "15e30a8f8b6f"
down_revision: Union[str, None] = "1e57d1db82b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 簽核流程通知：收件人皆為送審當事人（審核者 / 撰寫者），站內於「我的文件動態」與
# 「簽核中心」看得到，故不再寄 Email。
_FLOW_TEMPLATES = ("DOC_SUBMIT", "DOC_REJECT", "OBS_SUBMIT", "OBS_APPROVE", "OBS_REJECT")

_NEW_CHANNEL = "MSG"
_OLD_CHANNEL = "BOTH"  # 回滾用：b7fa4b6e4fe7 之種子值


def _set_channel(channel: str) -> None:
    """將 5 支流程通知範本之 CHANNEL 一併設為指定值（MODULE 限 DM，避免誤觸同名他模組範本）。"""
    op.execute(
        text(
            'UPDATE "DP_NOTIFY_TEMPLATE" SET "CHANNEL" = :channel '
            'WHERE "MODULE" = \'DM\' AND "TEMPLATE_CODE" IN '
            "(:t0, :t1, :t2, :t3, :t4)"
        ).bindparams(
            channel=channel,
            t0=_FLOW_TEMPLATES[0],
            t1=_FLOW_TEMPLATES[1],
            t2=_FLOW_TEMPLATES[2],
            t3=_FLOW_TEMPLATES[3],
            t4=_FLOW_TEMPLATES[4],
        )
    )


#: `CHANNEL` 的合法值域（平台詞彙）。比照既有的 `CK_DP_PARAM_D_EDIT_SCOPE`。
_CK_CHANNEL = "CK_DP_NOTIFY_TEMPLATE_CHANNEL"
_CHANNELS = ("EMAIL", "MSG", "BOTH")


def upgrade() -> None:
    _set_channel(_NEW_CHANNEL)

    # 補值域約束（#554 Security Review MEDIUM-4）。
    #
    # 建表時 `CHANNEL` 只有 String(10)、**沒有 CHECK**；值域唯一的把關是 schemas.py 的
    # `Literal["EMAIL","MSG","BOTH"]`，而那只在 API 寫入路徑上。#307 讓 CHANNEL 唯讀、
    # #554 進一步讓站內範本整列不可寫，於是這些列的 CHANNEL **只剩 IT 直接下 SQL 一條路**
    # ——那條路沒有值域驗證、不寫稽核、不 bump VERSION。
    #
    # 具體風險：打成 `EMAIL_ONLY`（正是本次於 data-model.md 更正掉的舊寫法）會通過 DB，
    # 而 `_channel_allows_email` 回 False → 該範本**靜默永不寄信**。這是 spec 註記自己
    # 警告過的失敗模式，卻沒有東西擋它。加上 CHECK 把靜默失效換成當場報錯。
    op.create_check_constraint(
        _CK_CHANNEL, "DP_NOTIFY_TEMPLATE", f"\"CHANNEL\" IN ('{_CHANNELS[0]}', '{_CHANNELS[1]}', '{_CHANNELS[2]}')"
    )


def downgrade() -> None:
    op.drop_constraint(_CK_CHANNEL, "DP_NOTIFY_TEMPLATE", type_="check")
    _set_channel(_OLD_CHANNEL)
