"""參數唯讀服務 SRVDP001 整合測試（讀種子 + 停用過濾 + 不存在回空，用真實 DB）。"""

import pytest
from sqlalchemy import update

from app.dp.params.models import DpParamDetail
from app.services import ParamService

pytestmark = pytest.mark.integration


async def test_get_param_value_reads_seed(db):
    """讀平台種子單值：JWT / ACCESS_TTL_MIN → '15'。"""
    value = await ParamService().get_param_value(db, "JWT", "ACCESS_TTL_MIN")
    assert value == "15"


async def test_get_param_value_missing_returns_none(db):
    """PARAM_ID 或 PARAM_KEY 不存在 → 回 None（非例外，利呼叫方 fallback）。"""
    svc = ParamService()
    assert await svc.get_param_value(db, "NO_SUCH_PARAM", "VALUE") is None
    assert await svc.get_param_value(db, "JWT", "NO_SUCH_KEY") is None


async def test_get_param_value_disabled_returns_none(db):
    """停用（IS_ENABLED=false）的明細 → 回 None。"""
    await db.execute(
        update(DpParamDetail)
        .where(DpParamDetail.param_id == "JWT", DpParamDetail.param_key == "ACCESS_TTL_MIN")
        .values(is_enabled=False)
    )
    assert await ParamService().get_param_value(db, "JWT", "ACCESS_TTL_MIN") is None


async def test_get_param_list_sorted(db):
    """清單型參數依 SORT_ORDER 排序回傳（ACTION_TYPE 6 筆）。

    本條**刻意**寫死完整種子內容：`ACTION_TYPE` 是程式碼寫死的 enum、不開放維護，
    內容變動必定伴隨程式碼變動（如 #477 補 `EXPORT` 時同步補了 router 的 `_Action` 值域）。
    種子改了而本條變紅，是提醒「確認兩邊都改了」，不是誤報。
    """
    items = await ParamService().get_param_list(db, "ACTION_TYPE")
    assert [i.key for i in items] == ["LOGIN", "LOGOUT", "CREATE", "UPDATE", "DELETE", "EXPORT"]
    assert [i.sort_order for i in items] == [1, 2, 3, 4, 5, 6]
    assert items[0].name == "登入"
    assert all(i.is_enabled for i in items)


async def test_get_param_list_filters_disabled(db):
    """enabled_only=True（預設）過濾停用清單項。"""
    await db.execute(
        update(DpParamDetail)
        .where(DpParamDetail.param_id == "ACTION_TYPE", DpParamDetail.param_key == "DELETE")
        .values(is_enabled=False)
    )
    keys = [i.key for i in await ParamService().get_param_list(db, "ACTION_TYPE")]
    all_keys = [i.key for i in await ParamService().get_param_list(db, "ACTION_TYPE", enabled_only=False)]
    # 釘住「被濾掉的**正是**那一列」而非只是「數量少一」——後者在過濾砍錯列時仍會通過。
    # 同樣不依賴母體大小，日後種子增減不會咬到這條。
    assert set(all_keys) - set(keys) == {"DELETE"}


async def test_get_param_list_include_disabled(db):
    """enabled_only=False 時停用項也回傳。"""
    await db.execute(
        update(DpParamDetail)
        .where(DpParamDetail.param_id == "ACTION_TYPE", DpParamDetail.param_key == "DELETE")
        .values(is_enabled=False)
    )
    items = await ParamService().get_param_list(db, "ACTION_TYPE", enabled_only=False)
    enabled_only = await ParamService().get_param_list(db, "ACTION_TYPE")
    # 同上：驗「含停用項時多了一筆」，不寫死母體大小
    assert len(items) == len(enabled_only) + 1
    disabled = next(i for i in items if i.key == "DELETE")
    assert disabled.is_enabled is False


async def test_get_param_list_missing_returns_empty(db):
    """不存在的 PARAM_ID → 空清單（非例外）。"""
    assert await ParamService().get_param_list(db, "NO_SUCH_PARAM") == []
