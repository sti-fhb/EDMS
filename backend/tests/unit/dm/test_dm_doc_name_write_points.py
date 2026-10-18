"""`DM_DOC.DOC_NAME` 的寫入點收斂守門（#697 AC 7）。

## 這條在證明什麼

#697 的 AC 寫得很精確：「有一條測試證明**換行無法進入 `DOC_PUBLISH` 通知的 params**
（而非只斷言 `doc_name` 被拒）」。

「輸入端擋下換行」只證明了**那一條路徑**安全。真正要的性質是**完整性**——通知讀的是
`DmDocument.doc_name` 這個欄位（`review/center_service.py` 的 `DOC_PUBLISH` / `DOC_REJECT` /
`OBS_*` 分支皆為 `doc.doc_name`），所以只要有**任何一條**寫入路徑沒經過驗證，換行就能落庫、
再從欄位流進信件內文。而 `_BODY_TRANS` 刻意保留 LF（多行退回理由是正當需求），擋不住它。

⇒ 本檔以 AST 掃出 `app/dm` 內所有寫 `doc_name` 的點，釘住「就是這兩處、都在已驗證的
編輯器路徑上」。新增第三處時這條會紅，提醒那條路徑也要套 `_DocNameForm` 的驗證。

## 為何不是整合測試

「送出含換行的名稱 → 422」已由 `test_dm_editor_input_limits.py` 的
`test_新增_身份欄含換行回_422` 涵蓋（unit，依 `sti-testing.md`「輸入驗證一律寫 unit」）。
本檔補的是那條測試**涵蓋不到**的那一半：有沒有別的門。
"""

import ast
from pathlib import Path

import pytest

from app.dm.document.models import DmDocument

pytestmark = pytest.mark.unit

_DM_ROOT = Path(__file__).resolve().parents[3] / "app" / "dm"

#: 已知且**經過輸入驗證**的寫入點（檔案相對 `app/dm` 的 posix 路徑）。
#:
#: - `editor/repository.py`：`DmDocument(doc_name=...)`，新增文件
#: - `editor/service.py`：`doc.doc_name = ...`，續編首版草稿改名（#222）
#:
#: 兩者的 `doc_name` 都來自 `editor/router.py` 的 `_DocNameForm` / `_OptDocNameForm`。
_ALLOWED_WRITE_POINTS = {"editor/repository.py", "editor/service.py"}


#: 真正擁有 `DOC_NAME` 欄位的 ORM model 名稱——由 model 本身推導，不手寫。
#:
#: ⚠️ 初版規則寫成「名稱以 `Dm` 開頭的建構子」，結果把 `integration/service.py` 的
#: `DmDocItem(doc_name=r.doc_name, ...)` 誤判為寫入點——那是跨模組門面在組**回應
#: dataclass**，右側是讀取。判準必須是「這個 class 真的對應到那張表」，不是命名慣例。
_ORM_MODELS_WITH_DOC_NAME = frozenset(cls.__name__ for cls in (DmDocument,) if "DOC_NAME" in cls.__table__.c)


def _write_points() -> set[str]:
    """掃出所有「寫入 `DM_DOC.DOC_NAME`」的檔案：ORM model 建構，或 ORM 實體的屬性賦值。

    ⚠️ 刻意不看「讀取」：`change_log` / `dashboard` / `detail` / `integration` 等把
    `doc_name` 放進回應 schema 的地方不是寫入點，納進來會讓這條守門噪音大到沒人維護。
    """
    found: set[str] = set()
    for path in _DM_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(_DM_ROOT).as_posix()
        for node in ast.walk(tree):
            # ① `DmDocument(doc_name=...)` —— 只認真正對應該表的 model
            if isinstance(node, ast.Call):
                callee = node.func
                name = callee.id if isinstance(callee, ast.Name) else getattr(callee, "attr", "")
                if name in _ORM_MODELS_WITH_DOC_NAME and any(kw.arg == "doc_name" for kw in node.keywords):
                    found.add(rel)
            # ② `<某個 ORM 實體>.doc_name = ...` —— 屬性賦值
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr == "doc_name":
                        found.add(rel)
    return found


def test_doc_name_的寫入點未擴散():
    """新增寫入路徑時本條會紅——請確認那條路徑的 `doc_name` 也經過輸入驗證。"""
    actual = _write_points()
    assert actual == _ALLOWED_WRITE_POINTS, (
        f"DOC_NAME 的寫入點有變動。\n"
        f"  預期：{sorted(_ALLOWED_WRITE_POINTS)}\n"
        f"  實際：{sorted(actual)}\n"
        f"新增的那一處若未套 `editor/router.py` 的 `_DocNameForm`（單行 + 長度），"
        f"含換行的文件名稱就能落庫，再從 `DmDocument.doc_name` 流進 `DOC_PUBLISH` 信件內文"
        f"——而 `_BODY_TRANS` 刻意保留 LF，擋不住它。"
    )


def test_掃描器本身有效():
    """正向錨點：掃描器若壞掉（例如 AST 走訪寫錯）會回空集合，而空集合會讓上面那條恆真。"""
    assert _write_points(), "掃描器回了空集合——它壞了，上面那條守門形同虛設"
