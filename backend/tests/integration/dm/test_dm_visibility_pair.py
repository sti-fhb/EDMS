"""可見對象 (單位, 職位) 配對之可見性判定（#437，真實 DB）。

判定規則：

    可見 ⟺ ∃ 文件配對 (du, dp) 使得
            (du = 「全單位」 AND dp = 「全體」)                           -- 全系統，不需任何授權
            OR ∃ 使用者配對 (uu, up):
                 (du = 「全單位」 OR du = uu) AND (dp = 「全體」 OR up = dp)

第一項不可省：未授予任何配對之閱覽者（`DM_USER_TAG` 無列）其「∃ 使用者配對」恆假，少了這項
連全系統公開文件都看不到——那是對導入前行為的迴歸（原「文件掛『全體』即所有閱覽者可見」）。

兩項皆以**整組配對**比對，不可拆成「單位集 ∧ 職位集」：使用者持 [(松山, 護理師), (三總, 行政)]
時，拆開比對會讓文件 (松山, 行政) 誤判為可見。

本檔覆蓋 issue #437 驗收條件 1（6 組單筆配對）與 2（多筆配對不含交叉組合）。
另驗人側 `UNIT_TAG_ID IS NULL`（單位未指定）之過渡行為——此為既有授權於導入單位維度後
可見範圍不變的依據。
"""

import pytest
from sqlalchemy import select

from app.core.utils import utcnow
from app.dm.audience.models import DmUserTag
from app.dm.catalog.models import DmCategory, DmFunc, DmTag  # noqa: F401  # 註冊 FK 目標
from app.dm.document.models import DmDocTag, DmDocument
from app.dm.document.visibility import visible_docs_condition
from app.dm.roles.authz import DM_VIEWER

pytestmark = pytest.mark.integration

_ALL_UNITS = "全單位"
_ALL_ROLES = "全體"
_SONGSHAN_STATION = "國防醫學院三軍總醫院松山分院捐血站"
_SONGSHAN_BRANCH = "國防醫學院三軍總醫院松山分院"
_TSGH = "國防醫學院三軍總醫院"
_MAB = "國防部軍醫局"


async def _role_id(db, tag_name: str) -> int:
    return await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "AUDIENCE", DmTag.tag_name == tag_name))


async def _unit_id(db, tag_name: str) -> int:
    return await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "UNIT", DmTag.tag_name == tag_name))


async def _doc(db, doc_id: str, pairs: list[tuple[str, str]]) -> None:
    """建立已發布文件並掛上 (單位名, 職位名) 配對清單。"""
    now = utcnow()
    db.add(
        DmDocument(
            doc_id=doc_id, doc_name=doc_id, category_code="SOP", status="PUBLISHED", created_user="e", created_date=now
        )
    )
    await db.flush()
    for unit_name, role_name in pairs:
        db.add(
            DmDocTag(
                doc_id=doc_id,
                tag_id=await _role_id(db, role_name),
                unit_tag_id=await _unit_id(db, unit_name),
                created_user="e",
                created_date=now,
            )
        )
    await db.flush()


async def _grant(db, user_id: str, pairs: list[tuple[str | None, str]]) -> None:
    """授予使用者 (單位名 | None, 職位名) 配對；單位傳 None 代表「未指定」（過渡狀態）。"""
    now = utcnow()
    for unit_name, role_name in pairs:
        db.add(
            DmUserTag(
                user_id=user_id,
                tag_id=await _role_id(db, role_name),
                unit_tag_id=None if unit_name is None else await _unit_id(db, unit_name),
                created_user="admin",
                created_date=now,
            )
        )
    await db.flush()


async def _visible(db, user_id: str) -> set[str]:
    cond = visible_docs_condition(user_id, {DM_VIEWER})
    stmt = select(DmDocument.doc_id)
    if cond is not None:
        stmt = stmt.where(cond)
    return set((await db.execute(stmt)).scalars().all())


async def test_六組單筆配對之可見性(db):
    """AC1：松山捐血站的護理師，對 6 種文件配對的可見結果。"""
    await _doc(db, "DM-SOP-000001", [(_SONGSHAN_STATION, _ALL_ROLES)])  # 單位命中 + 全體
    await _doc(db, "DM-SOP-000002", [(_SONGSHAN_STATION, "護理師")])  # 兩維皆命中
    await _doc(db, "DM-SOP-000003", [(_ALL_UNITS, "護理師")])  # 全單位 + 職位命中
    await _doc(db, "DM-SOP-000004", [(_ALL_UNITS, _ALL_ROLES)])  # 全系統可見
    await _doc(db, "DM-SOP-000005", [(_SONGSHAN_STATION, "行政人員")])  # 職位不符
    await _doc(db, "DM-SOP-000006", [(_SONGSHAN_BRANCH, "護理師")])  # 單位不符（不展開階層）
    await _grant(db, "v_songshan_nurse", [(_SONGSHAN_STATION, "護理師")])

    visible = await _visible(db, "v_songshan_nurse")

    assert {"DM-SOP-000001", "DM-SOP-000002", "DM-SOP-000003", "DM-SOP-000004"} <= visible
    assert "DM-SOP-000005" not in visible
    assert "DM-SOP-000006" not in visible


async def test_不展開階層_上層單位不涵蓋下層(db):
    """AC1：掛「三軍總醫院」之文件，松山分院與院內捐血站的人皆不可見。"""
    await _doc(db, "DM-SOP-000010", [(_TSGH, "護理師")])
    await _grant(db, "v_branch_nurse", [(_SONGSHAN_BRANCH, "護理師")])
    await _grant(db, "v_station_nurse", [(_SONGSHAN_STATION, "護理師")])

    assert "DM-SOP-000010" not in await _visible(db, "v_branch_nurse")
    assert "DM-SOP-000010" not in await _visible(db, "v_station_nurse")


async def test_多筆配對不涵蓋交叉組合(db):
    """AC2：文件掛 [(軍醫局, 護理師), (三總, 行政人員)]——客戶原始需求。

    交叉式設計會讓「軍醫局的行政人員」與「三總的護理師」也看得到，配對清單不會。
    """
    await _doc(db, "DM-SOP-000020", [(_MAB, "護理師"), (_TSGH, "行政人員")])
    await _grant(db, "v_mab_nurse", [(_MAB, "護理師")])  # 要
    await _grant(db, "v_tsgh_admin", [(_TSGH, "行政人員")])  # 要
    await _grant(db, "v_mab_admin", [(_MAB, "行政人員")])  # 不要
    await _grant(db, "v_tsgh_nurse", [(_TSGH, "護理師")])  # 不要

    assert "DM-SOP-000020" in await _visible(db, "v_mab_nurse")
    assert "DM-SOP-000020" in await _visible(db, "v_tsgh_admin")
    assert "DM-SOP-000020" not in await _visible(db, "v_mab_admin")
    assert "DM-SOP-000020" not in await _visible(db, "v_tsgh_nurse")


async def test_一人多配對_各自獨立生效(db):
    """一人同時為松山捐血站的護理師與三總的行政人員，兩邊文件皆可見、不互相擴散。"""
    await _doc(db, "DM-SOP-000030", [(_SONGSHAN_STATION, "護理師")])
    await _doc(db, "DM-SOP-000031", [(_TSGH, "行政人員")])
    await _doc(db, "DM-SOP-000032", [(_SONGSHAN_STATION, "行政人員")])  # 交叉組合，不該可見
    await _grant(db, "v_dual", [(_SONGSHAN_STATION, "護理師"), (_TSGH, "行政人員")])

    visible = await _visible(db, "v_dual")

    assert {"DM-SOP-000030", "DM-SOP-000031"} <= visible
    assert "DM-SOP-000032" not in visible


async def test_人側單位未指定_僅匹配全單位(db):
    """向後相容：導入單位維度前之既有授權（UNIT_TAG_ID IS NULL）可見範圍不變。

    僅能匹配文件側掛「全單位」之配對——即回填後的既有文件，其可見範圍與導入前相同。
    """
    await _doc(db, "DM-SOP-000040", [(_ALL_UNITS, "護理師")])  # 回填後的既有文件
    await _doc(db, "DM-SOP-000041", [(_SONGSHAN_STATION, "護理師")])  # 導入後新掛單位者
    await _grant(db, "v_legacy", [(None, "護理師")])  # 既有授權，單位未指定

    visible = await _visible(db, "v_legacy")

    assert "DM-SOP-000040" in visible
    assert "DM-SOP-000041" not in visible


async def test_無任何授權者_僅見全單位加全體(db):
    """未授予任何配對之閱覽者：只看得到 (全單位, 全體)。"""
    await _doc(db, "DM-SOP-000050", [(_ALL_UNITS, _ALL_ROLES)])
    await _doc(db, "DM-SOP-000051", [(_ALL_UNITS, "護理師")])

    visible = await _visible(db, "v_nobody")

    assert "DM-SOP-000050" in visible
    assert "DM-SOP-000051" not in visible
