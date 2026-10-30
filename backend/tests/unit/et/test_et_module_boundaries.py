"""ET 模組邊界之架構護欄（#188 A3；純靜態掃描，不需 DB）。

把 `sti-backend-boundaries.md` 與 `et/spec.md` §外模組 table 引用清單的兩條規範變成
機器可驗證的約束，而非靠 review 人工把關：

1. **ET 不得 import `app.dp` 內部**——跨模組一律經 `app.services`。白名單僅
   `_DP_IMPORT_ALLOWLIST` 所列（唯讀 JOIN 之 model、DP 刻意開放之帳號狀態判定）。
2. **ET 不得對 `DP_USER` 寫入**——帳號由平台建立 / 維護；ET 只可唯讀 JOIN。

「ET 不得 import `app.dm`」已由 `tests/integration/et/test_et_dm_integration.py`
（#185）守住，本檔不重複。

一律以 **AST** 判定，不做整檔字串比對：在 docstring / 註解寫下規則本身不應觸發護欄
（理由見上述 DM 版之 docstring）。每條護欄另以合成樣本驗證偵測函式本身——
偵測函式若寫壞成永遠回空清單，掃描真實程式碼的那支測試會永遠綠燈。
"""

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_BACKEND = Path(__file__).resolve().parents[3]
_ET_ROOT = _BACKEND / "app" / "et"
_VERSIONS = _BACKEND / "alembic" / "versions"

# ET 可直接 import 之 DP 模組（其餘一律經 `app.services`）：
# - `app.dp.users.models`：`DpUser` 唯讀 JOIN（報表 / 查詢例外，已列於 et/spec.md §外模組 table 引用清單 A 類）
# - `app.dp.users.account_status`：帳號狀態判定與其 SQL 條件——該模組 docstring 明訂
#   「`STATUS` 值域屬 DP 語意，其他模組不得自行解讀，需要 SQL 條件者請取用」，即為開放給他模組之出口
_DP_IMPORT_ALLOWLIST = frozenset({"app.dp.users.models", "app.dp.users.account_status"})

# 原生 SQL 寫入 DP_USER。`\b` 使 `DP_USER_xxx` 等他表不誤中；容許 schema 前綴（`public."DP_USER"`）
# 與 `ONLY`。`UPDATE "ET_X" ... FROM "DP_USER"` 為讀取，不符「動詞後直接接 DP_USER」故不中。
_DP_USER_WRITE_SQL = re.compile(
    r"\b(?:INSERT\s+INTO|UPDATE(?:\s+ONLY)?|DELETE\s+FROM(?:\s+ONLY)?|MERGE\s+INTO|TRUNCATE(?:\s+TABLE)?)"
    r'\s+(?:"?\w+"?\.)?"?DP_USER\b"?',
    re.IGNORECASE,
)
# 以**字尾**比對寫入函式：涵蓋 `pg_insert`（ET 之 upsert 慣用寫法）、`sa.insert` 等
_WRITE_SUFFIXES = ("insert", "update", "delete")
_TABLE_FACTORIES = frozenset({"table", "Table"})


def _imported_modules(node: ast.Import | ast.ImportFrom) -> list[str]:
    """一個 import 語句實際引入之完整模組路徑。

    `from app.dp.users import models` 的 `node.module` 只是套件 `app.dp.users`，
    須接上名稱才知道引入的是 `app.dp.users.models`。
    """
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    module = node.module or ""
    return [f"{module}.{alias.name}" for alias in node.names]


def find_disallowed_dp_imports(source: str) -> list[str]:
    """回傳原始碼中不在白名單內之 `app.dp` import（模組路徑）。

    **相對 import 一律視為違規**（回報 `.` 開頭之原樣）：`app/` 全為絕對 import，
    而 `from ...dp.users import service` 不以 `app.dp` 開頭，不擋就是繞過護欄的捷徑。
    ruff 未開 `TID252`，lint 擋不到。

    ⚠️ 已知盲區：`importlib.import_module("app.dp...")` 等動態 import——須刻意繞過才寫得出來，由 review 把關。
    """
    hits: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.ImportFrom):
            if node.level > 0:
                hits.append("." * node.level + (node.module or ""))
                continue
            if node.module in _DP_IMPORT_ALLOWLIST:
                continue
        for name in _imported_modules(node):
            if (name == "app.dp" or name.startswith("app.dp.")) and name not in _DP_IMPORT_ALLOWLIST:
                hits.append(name)
    return hits


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _docstring_ids(tree: ast.Module) -> set[int]:
    """各 module / class / function 之 docstring 節點——在說明裡寫下規則本身不應觸發護欄。"""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def _dp_user_aliases(tree: ast.Module) -> set[str]:
    """`DpUser` 及其別名（`import ... DpUser as U`、單層賦值 `U = DpUser`）。"""
    names = {"DpUser"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(a.asname for a in node.names if a.name == "DpUser" and a.asname)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name) and node.value.id in names:
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def _refers_to_dp_user(expr: ast.expr, aliases: set[str]) -> bool:
    """`DpUser`、其別名、`models.DpUser`、`aliased(DpUser)`。"""
    if isinstance(expr, ast.Name):
        return expr.id in aliases
    if isinstance(expr, ast.Attribute):
        return expr.attr == "DpUser"
    if isinstance(expr, ast.Call) and _call_name(expr.func) == "aliased" and expr.args:
        return _refers_to_dp_user(expr.args[0], aliases)
    return False


def find_dp_user_writes(source: str) -> list[str]:
    """回傳原始碼中對 `DP_USER` 之寫入。

    涵蓋：ORM 建構（`DpUser(...)`）、`*insert` / `*update` / `*delete(DpUser)`（含 `pg_insert`、
    別名、`aliased`）、任何 `DpUser.__table__` 引用（Core 寫法之入口，唯讀 JOIN 用不到）、
    `table("DP_USER")`（migration 常見之 lightweight table），以及原生 SQL 字串（docstring 除外）。

    ⚠️ 已知盲區（須刻意繞過才寫得出來，由 review 把關）：對既有 `DpUser` 實例直接改屬性
    （`user.status = ...`；ET 之 `DpUser` 引用皆為 `select` 欄位之唯讀 JOIN，取不到可寫實例）、
    動態拼接之 SQL（`"UPDATE " + tbl`）。
    """
    tree = ast.parse(source)
    docstrings = _docstring_ids(tree)
    aliases = _dp_user_aliases(tree)
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node.func) or ""
            if name in aliases or name == "DpUser":
                hits.append("DpUser(...)")
            elif name.endswith(_WRITE_SUFFIXES) and node.args and _refers_to_dp_user(node.args[0], aliases):
                hits.append(f"{name}(DpUser)")
            elif (
                name in _TABLE_FACTORIES
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "DP_USER"
            ):
                hits.append(f'{name}("DP_USER")')
        elif isinstance(node, ast.Attribute) and node.attr == "__table__" and _refers_to_dp_user(node.value, aliases):
            hits.append("DpUser.__table__")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            match = _DP_USER_WRITE_SQL.search(node.value)
            if match:
                hits.append(match.group(0))
    return hits


def _et_sources() -> list[Path]:
    """ET 全模組程式碼 + ET 之 alembic migration（檔名含 `_et_`）。

    不掃全部 migration：`common_seed_demo_accounts` 等**跨模組 seed** 本來就合法寫入 `DP_USER`
    （由平台側建立示範帳號），以「內容提到 ET 表」判定會把它們誤列為 ET。ET 自己的 migration
    依命名慣例一律帶 `_et_`；檔名不含 `_et_` 卻寫 `DP_USER` 的 ET migration 會脫離本護欄，由 review 把關。
    """
    return sorted(_ET_ROOT.rglob("*.py")) + sorted(_VERSIONS.glob("*_et_*.py"))


# ── 護欄 1：ET 不得 import app.dp 內部 ──────────────────────────────────────


def test_et_不得_import_dp_內部_白名單除外():
    """違規時回報**相對路徑**——ET 有多個子模組都有 `service.py`，只給檔名找不到。"""
    offenders = {
        str(py.relative_to(_BACKEND)): hits
        for py in sorted(_ET_ROOT.rglob("*.py"))
        if (hits := find_disallowed_dp_imports(py.read_text(encoding="utf-8")))
    }
    assert offenders == {}, f"ET 不得直接 import DP 內部（請改經 app.services）：{offenders}"


def test_dp_import_偵測_抓得到_service_與_repository():
    src = (
        "from app.dp.params.service import ParamService\n"
        "import app.dp.users.repository as repo\n"
        "from app.dp.users import service\n"
        "from ...dp.users import repository\n"
    )
    assert sorted(find_disallowed_dp_imports(src)) == sorted(
        [
            "app.dp.params.service.ParamService",
            "app.dp.users.repository",
            "app.dp.users.service",
            "...dp.users",
        ]
    )


def test_dp_import_偵測_放行白名單與_app_services():
    src = (
        "from app.dp.users.models import DpUser\n"
        "from app.dp.users.account_status import is_account_disabled\n"
        "from app.dp.users import models\n"
        "from app.services import ParamService\n"
        '"""註解寫 from app.dp.params.service import X 不算"""\n'
    )
    assert find_disallowed_dp_imports(src) == []


# ── 護欄 2：ET 不得寫入 DP_USER ─────────────────────────────────────────────


def test_et_不得寫入_dp_user():
    """涵蓋 migration：#185 bootstrap seed 對 `DP_USER` 只有 `INSERT ... SELECT` 讀取，此前僅靠人工確認。"""
    offenders = {
        str(py.relative_to(_BACKEND)): hits
        for py in _et_sources()
        if (hits := find_dp_user_writes(py.read_text(encoding="utf-8")))
    }
    assert offenders == {}, f"ET 不得寫入 DP_USER（帳號寫入一律經 DP Service）：{offenders}"


def test_et_掃描範圍含_bootstrap_migration():
    """正向錨點：glob 寫錯會讓 migration 靜默脫離掃描範圍。"""
    assert any("et_seed_roles_bootstrap" in p.name for p in _et_sources())


def test_dp_user_寫入偵測_抓得到_orm_與原生_sql():
    src = (
        "from app.dp.users import models\n"
        "from app.dp.users.models import DpUser as U\n"
        "Alias = DpUser\n"
        "db.add(DpUser(user_id='x'))\n"
        "db.add(models.DpUser(user_id='y'))\n"
        "await db.execute(update(DpUser).values(status='DISABLED'))\n"
        "stmt = sa.delete(DpUser)\n"
        "stmt = pg_insert(DpUser).on_conflict_do_nothing()\n"  # ET 之 upsert 慣用寫法
        "stmt = update(models.DpUser)\n"
        "stmt = update(U)\n"
        "stmt = insert(Alias)\n"
        "stmt = update(aliased(DpUser))\n"
        "stmt = DpUser.__table__.insert()\n"
        "op.bulk_insert(sa.table('DP_USER', sa.column('USER_ID')), [])\n"
        'text(\'INSERT INTO "DP_USER" ("USER_ID") VALUES (:u)\')\n'
        "text('update dp_user set status = 1')\n"
        'text(\'UPDATE public."DP_USER" SET "X" = 1\')\n'
        'text(\'UPDATE ONLY "DP_USER" SET "X" = 1\')\n'
        "text('MERGE INTO DP_USER u USING x ON true')\n"
        "text('TRUNCATE TABLE DP_USER')\n"
    )
    # `ast.walk` 為廣度優先、不保證原始碼順序，故以排序比對
    assert sorted(find_dp_user_writes(src)) == sorted(
        [
            "DpUser(...)",
            "DpUser(...)",
            "update(DpUser)",
            "delete(DpUser)",
            "pg_insert(DpUser)",
            "update(DpUser)",
            "update(DpUser)",
            "insert(DpUser)",
            "update(DpUser)",
            "DpUser.__table__",
            'table("DP_USER")',
            'INSERT INTO "DP_USER"',
            "update dp_user",
            'UPDATE public."DP_USER"',
            'UPDATE ONLY "DP_USER"',
            "MERGE INTO DP_USER",
            "TRUNCATE TABLE DP_USER",
        ]
    )


def test_dp_user_寫入偵測_放行唯讀與他表寫入():
    src = (
        '"""模組說明：不得 UPDATE DP_USER，也不得 INSERT INTO "DP_USER"。"""\n'
        "def f():\n"
        '    """函式說明同樣不算：DELETE FROM DP_USER"""\n'
        "select(DpUser.user_id).join(DpUser, DpUser.user_id == X.user_id)\n"
        "pg_insert(EtUserRole).on_conflict_do_update(index_elements=['USER_ID'], set_={})\n"
        'text(\'INSERT INTO "ET_USER_ROLE" SELECT u."USER_ID" FROM "DP_USER" u\')\n'
        'text(\'UPDATE "ET_COURSE" c SET "X" = 1 FROM "DP_USER" u\')\n'
        'text(\'UPDATE "DP_USER_ROLE" SET "X" = 1\')\n'
        "update(EtUserRole)\n"
    )
    assert find_dp_user_writes(src) == []
