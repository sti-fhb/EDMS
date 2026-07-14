"""DP_NOTIFY_TEMPLATE schema smoke test（T006）。

驗證通知範本 model 可用：MODULE+TEMPLATE_CODE 複合 PK、BODY（TEXT）、
Boolean 旗標（IS_ENABLED / IS_SYSTEM）、VERSION 可寫入讀回。
屬 schema plumbing 健康檢查。
"""

import pytest
from sqlalchemy import select

from app.core.utils import utcnow
from app.dp.notify.models import DpNotifyTemplate

pytestmark = pytest.mark.integration


async def test_notify_template_insert_and_query(db):
    """插入一支 DP 系統信範本（複合 PK + TEXT body），讀回驗證。"""
    now = utcnow()
    db.add(
        DpNotifyTemplate(
            module="DP",
            template_code="PWD_RESET",
            template_name="密碼重設信",
            subject="【EDMS】密碼重設通知",
            body="您好 {user_name}，請點擊連結重設密碼：{reset_link}",
            variables="user_name, reset_link",
            channel="EMAIL",
            is_enabled=True,
            is_system=True,
            version=1,
            created_user="SYSTEM",
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()

    fetched = (
        await db.execute(
            select(DpNotifyTemplate).where(
                DpNotifyTemplate.module == "DP",
                DpNotifyTemplate.template_code == "PWD_RESET",
            )
        )
    ).scalar_one()
    assert fetched.is_system is True
    assert "{reset_link}" in fetched.body
