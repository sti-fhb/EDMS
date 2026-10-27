"""送檔端點都先釋放 DB 連線，且都在 nginx「不寫暫存」的下載 location 內（#810 第 3 項）。

兩件事必須一起成立，少一件都會出事：
- nginx 對下載不寫暫存（`proxy_max_temp_file_size 0`），慢速讀取的客戶端就無法寫滿 nginx 的磁碟；
  但 nginx 因此依客戶端速度向後端取資料，後端在整段送檔期間都在送
- FastAPI 的 `get_db` 要等 response 送完才收尾——送檔前不先 `release_db_before_streaming`，
  每個看影片的學員就全程佔住 1 條 DB 連線（連線池只有 15 條）

反過來，下載 location 若命中**沒有**先釋放連線的端點（例如一般 JSON 查詢），那支端點就會被慢客戶端
拖住連線。故三邊對照：回傳 `FileResponse` 的函式 ↔ 先釋放連線 ↔ nginx 下載 location。
"""

import ast
import re
from pathlib import Path

import pytest

from main import app

pytestmark = pytest.mark.unit

_BACKEND = Path(__file__).resolve().parents[2]
_APP = _BACKEND / "app"
_NGINX_CONF = _BACKEND.parent / "nginx" / "nginx.conf"
_RELEASE = "release_db_before_streaming"
_NO_TEMP = "proxy_max_temp_file_size 0;"


def _router_prefixes(tree: ast.Module) -> dict[str, str]:
    """模組內 `xxx = APIRouter(prefix=...)` 的變數名 → prefix。"""
    prefixes: dict[str, str] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and getattr(node.value.func, "id", "") == "APIRouter"
        ):
            prefix = next((ast.literal_eval(k.value) for k in node.value.keywords if k.arg == "prefix"), "")
            prefixes.update({t.id: prefix for t in node.targets if isinstance(t, ast.Name)})
    return prefixes


def _returns_file_response(fn: ast.AsyncFunctionDef) -> list[ast.Return]:
    return [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Return)
        and isinstance(n.value, ast.Call)
        and getattr(n.value.func, "id", "") == "FileResponse"
    ]


def _file_endpoints() -> list[tuple[str, str, ast.AsyncFunctionDef]]:
    """回傳 `FileResponse` 的 async 路由函式：(位置, 完整 GET 路徑, 函式)。"""
    found = []
    for path in sorted(_APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        prefixes = _router_prefixes(tree)
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.AsyncFunctionDef) or not _returns_file_response(fn):
                continue
            route = next(
                (
                    prefixes[d.func.value.id] + ast.literal_eval(d.args[0])
                    for d in fn.decorator_list
                    if isinstance(d, ast.Call)
                    and isinstance(d.func, ast.Attribute)
                    and isinstance(d.func.value, ast.Name)
                    and d.func.value.id in prefixes
                    and d.func.attr == "get"
                ),
                None,
            )
            found.append((f"{path.relative_to(_BACKEND).as_posix()}:{fn.lineno} {fn.name}", route, fn))
    return found


def _sample(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "X1", path)


def _nginx_download_patterns() -> list[re.Pattern[str]]:
    """設了 `proxy_max_temp_file_size 0` 的 regex location（取每次出現之前最近的 location）。"""
    conf = _NGINX_CONF.read_text(encoding="utf-8")
    patterns = []
    for m in re.finditer(re.escape(_NO_TEMP), conf):
        patterns.append(re.compile(re.findall(r"location ~ (\S+) \{", conf[: m.start()])[-1]))
    return patterns


def test_守門_掃得到送檔端點():
    """正向錨點：掃描若壞掉（0 支），下面幾條會空洞地通過。"""
    assert len(_file_endpoints()) >= 5


def test_送檔端點都是_GET_路由():
    """掃描依賴 `@router.get(...)` 才能算出路徑；不是的話守門會漏掉它。"""
    assert [where for where, route, _ in _file_endpoints() if route is None] == []


_PRESENCE_CHECKS = {"_ensure_file_present", "is_file"}


def _calls(node: ast.AST) -> set[str]:
    """節點內所有呼叫的名稱（`f(...)` 取 `f`、`x.f(...)` 取 `f`）。"""
    names = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            func = n.func
            names.add(func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", ""))
    return names


def _session_param(fn: ast.AsyncFunctionDef) -> str | None:
    return next(
        (a.arg for a in fn.args.args + fn.args.kwonlyargs if getattr(a.annotation, "id", "") == "AsyncSession"),
        None,
    )


def _release_problem(fn: ast.AsyncFunctionDef) -> str | None:
    """回傳違規說明；合規回 None。

    規則：`return FileResponse(...)` 必須在函式最外層，**緊接在它前面**的一句必須是
    `await release_db_before_streaming(<AsyncSession 參數>)`，且更前面要有實體檔存在檢查。
    「緊接在前」同時保證了兩件事：在存在檢查之後（檔案遺失時要拋 404 讓閱讀紀錄回滾），
    且與 return 在同一層（不會只在某個分支裡呼叫）。
    """
    body = fn.body
    returns = [
        i
        for i, st in enumerate(body)
        if isinstance(st, ast.Return)
        and isinstance(st.value, ast.Call)
        and getattr(st.value.func, "id", "") == "FileResponse"
    ]
    if len(returns) != len(_returns_file_response(fn)):
        return "return FileResponse 不在函式最外層"
    for i in returns:
        prev = body[i - 1] if i > 0 else None
        call = prev.value.value if isinstance(prev, ast.Expr) and isinstance(prev.value, ast.Await) else None
        if not (isinstance(call, ast.Call) and getattr(call.func, "id", "") == _RELEASE):
            return f"return FileResponse 的前一句不是 await {_RELEASE}(...)"
        arg = call.args[0].id if call.args and isinstance(call.args[0], ast.Name) else None
        if arg != _session_param(fn):
            return f"{_RELEASE} 的參數不是本函式的 AsyncSession 參數"
        if not any(_calls(st) & _PRESENCE_CHECKS for st in body[: i - 1]):
            return f"{_RELEASE} 之前沒有實體檔存在檢查"
    return None


def test_送檔前都先釋放_DB_連線():
    problems = [f"{where}：{msg}" for where, _, fn in _file_endpoints() if (msg := _release_problem(fn))]
    assert problems == [], problems


def test_守門_回傳型別為_FileResponse_的函式都被掃到():
    """掃描只認得 `return FileResponse(...)`；別名 import、先賦值再回傳等寫法會漏掉——以回傳註解交叉比對。"""
    scanned = {where for where, _, _ in _file_endpoints()}
    annotated = []
    for path in sorted(_APP.rglob("*.py")):
        for fn in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef))
                and getattr(fn.returns, "id", "") == "FileResponse"
            ):
                annotated.append(f"{path.relative_to(_BACKEND).as_posix()}:{fn.lineno} {fn.name}")
    assert annotated, "正向錨點：至少要找到一個回傳註解為 FileResponse 的函式"
    assert sorted(set(annotated) - scanned) == []


def test_送檔端點都在_nginx_的下載_location():
    patterns = _nginx_download_patterns()
    assert patterns, f"nginx.conf 找不到設 `{_NO_TEMP}` 的 location"
    missing = [
        f"{where} {route}"
        for where, route, _ in _file_endpoints()
        if route and not any(rx.match(_sample(route)) for rx in patterns)
    ]
    assert missing == [], f"送檔端點要加進 nginx/nginx.conf 的下載 location：{missing}"


def test_nginx_的下載_location_只命中送檔端點():
    """反向：命中一般 JSON 端點的話，那支端點會被慢客戶端拖住 DB 連線（它沒有先釋放）。"""
    patterns = _nginx_download_patterns()
    file_routes = {_sample(route) for _, route, _ in _file_endpoints() if route}
    extra = sorted(
        f"{method.upper()} {path}"
        for path, methods in app.openapi()["paths"].items()
        for method in methods
        if any(rx.match(_sample(path)) for rx in patterns) and _sample(path) not in file_routes
    )
    assert extra == [], f"nginx 下載 location 命中非送檔端點：{extra}"
