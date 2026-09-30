"""可見對象 (單位, 職位) 配對之輸入驗證（#437）。

配對經 multipart form 以**兩個平行陣列**傳入（`audience_unit_ids` / `audience_role_ids`，
同索引成對）——form 無法表達物件陣列。故驗證須含「兩陣列等長」這條，否則錯位的配對會靜默
寫入成另一組人的可見範圍。

TRAINING 分類靜默丟棄整份配對（延續 #377 之 FR-009 例外）。
"""

import pytest

from app.core.exceptions import AppError
from app.dm.editor.service import EditorService

pytestmark = pytest.mark.unit

_ROLE_NURSE = 1
_ROLE_ADMIN = 2
_UNIT_MAB = 10
_UNIT_TSGH = 11
_RETRIEVAL_BLOOD = 20

_GROUPS = {
    _ROLE_NURSE: "AUDIENCE",
    _ROLE_ADMIN: "AUDIENCE",
    _UNIT_MAB: "UNIT",
    _UNIT_TSGH: "UNIT",
    _RETRIEVAL_BLOOD: "RETRIEVAL",
}


class _StubRepo:
    """`classify_tags` 回標籤組型；未列於 `_GROUPS` 者視同停用（不回傳）。"""

    async def classify_tags(self, db, tag_ids) -> dict[int, str]:
        return {t: _GROUPS[t] for t in tag_ids if t in _GROUPS}


def _svc() -> EditorService:
    return EditorService(repository=_StubRepo())


async def test_配對與檢索標籤一併回傳():
    """正常輸入 → 配對帶單位、檢索標籤之單位為 None。"""
    got = await _svc()._validate_tags(
        None,
        audience_unit_ids=[_UNIT_MAB, _UNIT_TSGH],
        audience_role_ids=[_ROLE_NURSE, _ROLE_ADMIN],
        retrieval_ids=[_RETRIEVAL_BLOOD],
        category_code="SOP",
    )

    assert set(got) == {
        (_ROLE_NURSE, _UNIT_MAB),
        (_ROLE_ADMIN, _UNIT_TSGH),
        (_RETRIEVAL_BLOOD, None),
    }


async def test_兩陣列長度不等則擋下():
    """錯位的配對會把可見範圍指給另一組人，必須擋在寫入前。"""
    with pytest.raises(AppError) as exc:
        await _svc()._validate_tags(
            None,
            audience_unit_ids=[_UNIT_MAB],
            audience_role_ids=[_ROLE_NURSE, _ROLE_ADMIN],
            retrieval_ids=[],
            category_code="SOP",
        )

    assert exc.value.error_code == "DM_DOC_010"


async def test_training_靜默丟棄整份配對():
    """TRAINING 免填可見對象且 MUST NOT 寫入（#377 FR-009）——單位一併丟棄。"""
    got = await _svc()._validate_tags(
        None,
        audience_unit_ids=[_UNIT_MAB],
        audience_role_ids=[_ROLE_NURSE],
        retrieval_ids=[_RETRIEVAL_BLOOD],
        category_code="TRAINING",
    )

    assert got == [(_RETRIEVAL_BLOOD, None)]


async def test_單位欄放了職位標籤則擋下():
    """`UNIT_TAG_ID` 之 FK 只能保證指向 DM_TAG，組別須由應用層把關。"""
    with pytest.raises(AppError) as exc:
        await _svc()._validate_tags(
            None,
            audience_unit_ids=[_ROLE_NURSE],  # 職位標籤放進單位欄
            audience_role_ids=[_ROLE_ADMIN],
            retrieval_ids=[],
            category_code="SOP",
        )

    assert exc.value.error_code == "DM_DOC_010"


async def test_職位欄放了單位標籤則擋下():
    with pytest.raises(AppError) as exc:
        await _svc()._validate_tags(
            None,
            audience_unit_ids=[_UNIT_MAB],
            audience_role_ids=[_UNIT_TSGH],  # 單位標籤放進職位欄
            retrieval_ids=[],
            category_code="SOP",
        )

    assert exc.value.error_code == "DM_DOC_010"


async def test_停用之標籤擋下():
    """`classify_tags` 僅回啟用中者；停用之單位不得再被掛上。"""
    with pytest.raises(AppError) as exc:
        await _svc()._validate_tags(
            None,
            audience_unit_ids=[999],  # 不存在 / 已停用
            audience_role_ids=[_ROLE_NURSE],
            retrieval_ids=[],
            category_code="SOP",
        )

    assert exc.value.error_code == "DM_DOC_010"
