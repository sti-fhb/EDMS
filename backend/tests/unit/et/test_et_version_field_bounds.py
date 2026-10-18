"""ET 全模組：**請求本體**的 `version` 一律要有 INT4 上界（2026-10-18 security review L-3）。

## 這條在擋什麼

`VERSION` 在 DB 是 `Integer`（int4）。樂觀鎖的版本由**請求帶入**，所以
`{"version": 9999999999}` 會一路走到 asyncpg 綁定參數那一刻才拋出，落到通用例外
handler 變成 **500**——而它其實是一個「版本不符」的請求，應該回 409。

## 為什麼用 OpenAPI 列舉，而不是掃 schemas 模組

單一個 `le=MAX_INT4` 誰都寫得出來；問題是**下一個新增樂觀鎖欄位的人不會想到**。
`course/schemas.py` 六處有、material / quiz / survey / approval 八處沒有，就是這樣來的。

⚠️ 但「掃 `app.et.*.schemas` 裡所有帶 version 的 model」會連**回應** model 一起掃到
（`CourseDetail`、`QuizDetail`…共 12 個），而回應的 `version` 來自 DB、不是使用者輸入，
加上界毫無意義。改以「名字結尾是 `Req`」區分則是另一種猜：一個叫 `UpdatePayload`
的請求模型會靜默漏掉。

OpenAPI 的 `requestBody` 是 FastAPI **自己算出來的**「哪些 model 會接使用者輸入」，
不需要猜。⛔ 不要為了讓這條變綠而加豁免清單——沒有豁免清單是刻意的。
"""

from typing import Any

import pytest

import main
from app.et.course.schemas import MAX_INT4

_SPEC: dict[str, Any] = main.app.openapi()


def _schema_names_in_et_request_bodies() -> list[str]:
    """`/api/et` 底下所有端點的請求本體所參照的 component schema 名稱。"""
    names: list[str] = []
    for path, ops in _SPEC["paths"].items():
        if not path.startswith("/api/et"):
            continue
        for op in ops.values():
            content = (op.get("requestBody") or {}).get("content") or {}
            for media in content.values():
                ref = (media.get("schema") or {}).get("$ref")
                if ref:
                    names.append(ref.rsplit("/", 1)[-1])
    return sorted(set(names))


def _with_version() -> list[str]:
    """上述之中，請求本體真的帶 `version` 欄位的那些。"""
    components = _SPEC["components"]["schemas"]
    return [n for n in _schema_names_in_et_request_bodies() if "version" in (components[n].get("properties") or {})]


def test_掃得到東西() -> None:
    """🔴 正向錨點：掃不到任何 schema 時，下面那條會**空集合通過**。

    參數化出 0 條的 `parametrize` 不會紅，只會安靜地什麼都不驗——與「對錯誤回應做
    否定斷言」是同一個形狀的假證據。
    """
    found = _with_version()

    assert len(found) >= 12, f"掃描器壞了（改了路由前綴？），下面的守門已失效；目前只掃到 {found}"


@pytest.mark.parametrize("schema_name", _with_version())
def test_請求本體的_version_有_int4_上界(schema_name: str) -> None:
    prop = _SPEC["components"]["schemas"][schema_name]["properties"]["version"]

    assert "maximum" in prop, f"{schema_name}.version 沒有上界 ⇒ 超界的版本號會變成 500 而非 409"
    assert prop["maximum"] <= MAX_INT4, f"{schema_name}.version 的上界 {prop['maximum']} 超過 int4"
