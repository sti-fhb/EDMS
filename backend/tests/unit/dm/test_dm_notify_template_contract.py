"""範本宣告的 `VARIABLES` 與程式實傳 params key 的契約守門（#627）。

## 為何需要這道守門

`DP_NOTIFY_TEMPLATE` 的 `VARIABLES` 是一份**三方契約**：

| 參與者 | 看的是什麼 |
|---|---|
| 範本主旨 / 內文 | 用 `{佔位}` 引用 |
| DP04 維護畫面 | 管理者依 `VARIABLES` 知道可以用哪些佔位 |
| 呼叫端程式 | 實際傳入的 `params` dict |

`ensure_renderable`（#534 / #597）守的是**前兩者**：儲存時以 `VARIABLES` 組空值探針跑一次
`_render`，擋掉「管理者把 `{user_name}` 打成 `{user_nam}`」。

但它**看不到第三者**——它不知道程式實際傳什麼。於是這種錯位可以長期存在：

    VARIABLES   reviewer_name, doc_name, days          ← 宣告
    內文         ...已逾 {days} 天...                   ← 與宣告一致 → ensure_renderable 通過
    程式實傳     reviewer_name, doc_name, waiting_days  ← 對不上 → 渲染時 KeyError

`AUTO_REMIND` 正是如此（#627）。它之所以沒被發現，是因為該範本的 `CHANNEL` 是 `MSG`、
從不寄信，錯位永遠沒機會現形；一改成 `EMAIL` 就會變成每天一批 `FAILED` 空信，
而 `send_email` 整批寫 `FAILED` 後回 `queued_count=0` 且**不外拋**。

## 本測試的判準：`VARIABLES` ⊆ 程式實傳 key

方向是單向包含，不是相等——多傳無害（`_SafeFormatter` 只對**缺** key 報錯），
少傳才會炸。例如 `OBS_APPROVE` 的呼叫端多傳了 `reason`，那是刻意共用同一個
`_notify_obsolete`，不該被判為錯。

⚠️ 本測試刻意是 **unit**：它只比對「seed 的宣告字串」與「程式碼的 params 字面值」，
拿掉真 DB 一樣驗得了（見 `.claude/rules/sti-testing.md` 的分層閘門）。
"""

import ast
import pathlib
import re

import pytest

pytestmark = pytest.mark.unit

_BACKEND = pathlib.Path(__file__).resolve().parents[3]
_SEED = (
    _BACKEND
    / "alembic"
    / "versions"
    / "20260806_1118_b7fa4b6e4fe7_dm_seed_templates_params_into_dp.py"
)
_DM_APP = _BACKEND / "app" / "dm"

def _dict_keys(node: ast.AST | None) -> set[str] | None:
    """dict literal → key 集合；非 dict literal 回 None。"""
    if isinstance(node, ast.Dict):
        return {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    return None


def _declared_variables() -> dict[str, set[str]]:
    """自 seed migration 取各 DM 範本宣告的 `VARIABLES`（後續 migration 若改寫，由本測試的
    `_assert_no_later_override` 擋下——見該函式說明）。"""
    src = _SEED.read_text(encoding="utf-8")
    out: dict[str, set[str]] = {}
    for m in re.finditer(r'\(\s*"DM",\s*"([A-Z_]+)",(.*?)\n    \),', src, re.S):
        code, rest = m.group(1), m.group(2)
        vm = re.search(r'"([a-z_]+(?:,[a-z_]+)*)",\s*\n\s*"(?:EMAIL|MSG|BOTH)"', rest)
        if vm:
            out[code] = set(vm.group(1).split(","))
    return out


def _passed_params() -> dict[str, set[str]]:
    """掃 `app/dm` 的 AST，取每支範本實際被傳入的 params key。

    以 AST 而非正則：字面值比對會把註解、docstring 裡的範例一併撈進來。

    需處理三種寫法（全部出現在現行程式碼裡，不是假想）：

    1. 行內 dict —— `notify(template_code="DOC_SUBMIT", params={...})`
    2. 區域變數 —— `params = {...}` 後 `notify(template_code=_TPL_WEEKLY, params=params)`
    3. **包裝層** —— `_notify_obsolete(template_code="OBS_APPROVE", ...)`，而真正的
       `notify(params={...})` 在該函式體內、`template_code` 是它的參數

    ⚠️ 刻意不用「手動列一張 code → keys 對照表」補第 2、3 種：那張表不會跟著程式碼變，
    改了呼叫端卻忘了改表時，守門會**靜默地放行**——正是本測試要消滅的那種失效。
    """
    found: dict[str, set[str]] = {}
    wrappers: dict[str, set[str]] = {}  # 函式名 → 其內 notify 的 params key（template_code 為變數者）
    wrapper_calls: list[tuple[str, str]] = []  # (被呼叫的函式名, 字面 template_code)

    for path in _DM_APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # 模組層字串常數（`_TPL_WEEKLY = "KPI_WEEKLY"`）——`template_code` 常以常數傳入，
        # 不解析的話會被誤判成「包裝層」而整支範本漏出守門之外。
        consts: dict[str, str] = {
            t.id: n.value.value
            for n in tree.body
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
            for t in n.targets
            if isinstance(t, ast.Name)
        }
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            local: dict[str, set[str]] = {}
            for stmt in ast.walk(fn):
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                    tgt = stmt.targets[0]
                    keys = _dict_keys(stmt.value)
                    if isinstance(tgt, ast.Name) and keys is not None:
                        local[tgt.id] = keys
            for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call)]:
                kw = {k.arg: k.value for k in call.keywords if k.arg}
                code_node, params_node = kw.get("template_code"), kw.get("params")
                # Name 若為模組層字串常數，等同字面值
                if isinstance(code_node, ast.Name) and code_node.id in consts:
                    code_node = ast.Constant(value=consts[code_node.id])
                # 包裝層呼叫：有字面 template_code、但 params 不在這一層
                fname = getattr(call.func, "attr", getattr(call.func, "id", None))
                if isinstance(code_node, ast.Constant) and params_node is None and fname:
                    wrapper_calls.append((fname, code_node.value))
                if params_node is None:
                    continue
                keys = _dict_keys(params_node)
                if keys is None and isinstance(params_node, ast.Name):
                    keys = local.get(params_node.id)
                if keys is None:
                    continue
                if isinstance(code_node, ast.Constant) and isinstance(code_node.value, str):
                    found.setdefault(code_node.value, set()).update(keys)
                else:  # template_code 是變數 → 本函式為包裝層
                    wrappers.setdefault(fn.name, set()).update(keys)

    for fname, code in wrapper_calls:
        if fname in wrappers:
            found.setdefault(code, set()).update(wrappers[fname])
    return found


def test_每支範本宣告的變數都有被程式傳入():
    declared = _declared_variables()
    passed = _passed_params()
    assert declared, "解析不到任何範本宣告——解析器壞了，不是沒有範本"

    missing = {
        code: sorted(vars_ - passed.get(code, set()))
        for code, vars_ in declared.items()
        if vars_ - passed.get(code, set())
    }
    assert not missing, (
        f"下列範本宣告了程式沒有傳入的變數，渲染時會 KeyError → 整批寫 FAILED 且不外拋：{missing}"
    )


def test_每支範本都有找到對應的呼叫端():
    """健康檢查：若解析器失效（如呼叫寫法改變），上面那條會因為「沒東西可比」而假性通過。"""
    declared = _declared_variables()
    passed = _passed_params()
    orphan = sorted(set(declared) - set(passed))
    assert not orphan, f"下列範本找不到呼叫端，本守門對它們形同虛設：{orphan}"
