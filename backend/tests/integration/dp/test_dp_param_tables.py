"""DP_PARAM_M / DP_PARAM_D schema smoke test（T005）。

驗證參數主檔/明細 model 可用：明細對主檔的 FK、複合 PK（PARAM_ID+PARAM_KEY）、
BaseModel 標準欄位可寫入讀回。屬 schema plumbing 健康檢查。
"""

import pytest
from sqlalchemy import select

from app.core.utils import utcnow
from app.dp.params.models import DpParamDetail, DpParamMaster

pytestmark = pytest.mark.integration


async def test_param_master_detail_insert_and_query(db):
    """建主檔（LIST 型）→ 明細兩列（複合 PK + FK），讀回並依 SORT_ORDER 排序。"""
    now = utcnow()
    db.add(
        DpParamMaster(
            param_id="DM_DOC_CATEGORY",
            param_name="文件分類",
            param_type="LIST",
            detail_lock=True,
            description="文件分類清單",
            created_user="SYSTEM",
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()

    for key, name, order in (("MANUAL", "手冊", 1), ("FORM", "表單", 2)):
        db.add(
            DpParamDetail(
                param_id="DM_DOC_CATEGORY",
                param_key=key,
                param_name=name,
                sort_order=order,
                is_enabled=True,
                created_user="SYSTEM",
                created_date=now,
                deleted=0,
            )
        )
    await db.flush()

    rows = (
        (
            await db.execute(
                select(DpParamDetail)
                .where(DpParamDetail.param_id == "DM_DOC_CATEGORY")
                .order_by(DpParamDetail.sort_order)
            )
        )
        .scalars()
        .all()
    )
    assert [r.param_key for r in rows] == ["MANUAL", "FORM"]
    assert rows[0].param_name == "手冊"
