"""ET 受控主檔類別列舉（SRVET004 / module-callbacks §3.1 之 `list_controlled_kinds`）。

ET 僅一類受控主檔（受訓單位標籤），且無子分組——清單為靜態宣告、不讀 DB，故寫 unit
而非 integration（`sti-testing` 之 integration vs unit 取捨）。DM 側需讀 `DM_TAG_GROUP`
取組名，該側寫 integration。
"""

import pytest

from app.et.catalog.adapter import EtCatalogAdapter

pytestmark = pytest.mark.unit


async def test_et_僅宣告一類受控主檔() -> None:
    """DP 後台據此決定要對 ET 呼叫哪些 kind——DP 不得硬編碼模組的 kind 清單。"""
    # db 傳 None：ET 之列舉不查 DB，此處刻意驗證該性質（會查 DB 就會在此炸）
    kinds = await EtCatalogAdapter().list_controlled_kinds(None)

    assert len(kinds) == 1
    kind = kinds[0]
    assert kind.kind == "TAG"
    assert kind.name, "顯示名不可為空——DP 端據此渲染區塊標題，不硬編碼模組語彙"
    assert kind.requires_code is False, "TAG_ID 由 Identity 配號，新增時不需使用者輸入代碼"
    assert kind.groups == (), "ET 受訓單位標籤為單層，無子分組"
