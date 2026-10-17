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

⚠️ 上面那組 `doc_name` / `days` 是 **#627 當時**的 `AUTO_REMIND`，不是現況——#699 把它改成
逐位審核者彙整，佔位已是 `reviewer_name,pending_count,pending_list`。此處保留舊值是因為
那才是本測試要擋的那個真實案例；要看現況請查 DB 或 `7c4e19ab3f52`。

## 本測試的判準：`VARIABLES` ⊆ 程式實傳 key

方向是單向包含，不是相等——多傳無害（`_SafeFormatter` 只對**缺** key 報錯），
少傳才會炸。例如 `OBS_APPROVE` 的呼叫端多傳了 `reason`，那是刻意共用同一個
`_notify_obsolete`，不該被判為錯。

## ⚠️ 為何宣告端讀 DB 而不是讀 seed migration

本測試初版是 unit，直接正則解析 seed migration `b7fa4b6e4fe7` 取 `VARIABLES`。**那是錯的**：
migration 是 append-only，**現況是最後一次寫入、不是 seed**。`9eb4dd6e496b`（#332，週報改
內文摘要 + 儀表板連結）就改寫過 `KPI_WEEKLY` 的 `VARIABLES`，於是初版守門拿兩個月前的舊宣告
去比對，對該範本**靜默地少驗了一個變數**——正是本測試要消滅的那種失效，而且發生在守門自己身上。

要在不讀 DB 的前提下算出現況，等於在測試裡重寫一遍 alembic 的套用順序。宣告端的現況**本來就是
DB 狀態**，所以本測試是 integration；呼叫端（`app/dm` 的 AST）仍是純靜態解析。

母體由 DB 查詢本身保證窮盡：`WHERE MODULE='DM'` 回幾列就驗幾列，新增範本不會漏出守門之外。
"""

import ast
import pathlib

import pytest
from sqlalchemy import select

from app.dp.notify.models import DpNotifyTemplate

pytestmark = pytest.mark.integration

_DM_APP = pathlib.Path(__file__).resolve().parents[3] / "app" / "dm"


def _dict_keys(node: ast.AST | None) -> set[str] | None:
    """dict literal → key 集合；非 dict literal 回 None。"""
    if isinstance(node, ast.Dict):
        return {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    return None


def _module_string_consts(tree: ast.Module) -> dict[str, str]:
    """模組層字串常數（`_TPL_WEEKLY = "KPI_WEEKLY"`）。

    `template_code` 常以常數傳入；不解析的話該呼叫會被誤判成「包裝層」，整支範本就漏出守門之外。
    """
    return {
        t.id: n.value.value
        for n in tree.body
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
        for t in n.targets
        if isinstance(t, ast.Name)
    }


def _local_dict_vars(fn: ast.AST) -> dict[str, set[str]]:
    """函式內 `name = {...}` 的區域 dict 變數 → key 集合。"""
    out: dict[str, set[str]] = {}
    for stmt in ast.walk(fn):
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            tgt = stmt.targets[0]
            keys = _dict_keys(stmt.value)
            if isinstance(tgt, ast.Name) and keys is not None:
                out[tgt.id] = keys
    return out


def _scan_function(fn, consts, found, wrappers, wrapper_calls) -> None:
    """掃單一函式內的呼叫，把結果累加進三個收集器（就地修改）。"""
    local = _local_dict_vars(fn)
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
        consts = _module_string_consts(tree)
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            _scan_function(fn, consts, found, wrappers, wrapper_calls)

    for fname, code in wrapper_calls:
        if fname in wrappers:
            found.setdefault(code, set()).update(wrappers[fname])
    return found


async def _declared_variables(db) -> dict[str, set[str]]:
    """自 DB 取各 DM 範本**現行**宣告的 `VARIABLES`（空字串代表無變數）。"""
    rows = (await db.execute(select(DpNotifyTemplate).where(DpNotifyTemplate.module == "DM"))).scalars().all()
    return {r.template_code: {v for v in (r.variables or "").split(",") if v} for r in rows}


#: 刻意沒有呼叫端的範本——**不是漏接線，是已 seed 待用**。
#:
#: `SUBMIT_WITHDRAWN`（US9 撤回送審）於 `6a96fd1016fd` 種入，供未來站內訊息佇列使用；
#: 撤回的實際呈現走「我的文件動態」，不經通知服務（`app/dm/personal/service.py` 的 docstring
#: 載明此事）。平台至今沒有站內訊息佇列，故它沒有、也不該有呼叫端。
#:
#: ⛔ 請勿為了讓測試變綠而把其他範本加進這張清單：清單裡的每一支都代表「這支範本不受本守門
#: 保護」。下方 `test_豁免清單沒有多餘項目` 會在某支接上呼叫端時變紅，要求把它移出清單。
_INTENTIONALLY_UNWIRED = {"SUBMIT_WITHDRAWN"}


async def test_每支範本宣告的變數都有被程式傳入(db):
    declared = await _declared_variables(db)
    passed = _passed_params()
    assert declared, "DB 取不到任何 MODULE=DM 範本——查詢或 migration 壞了，不是沒有範本"

    missing = {
        code: sorted(vars_ - passed.get(code, set()))
        for code, vars_ in declared.items()
        if code not in _INTENTIONALLY_UNWIRED and vars_ - passed.get(code, set())
    }
    assert not missing, f"下列範本宣告了程式沒有傳入的變數，渲染時會 KeyError → 整批寫 FAILED 且不外拋：{missing}"


async def test_每支範本都有找到對應的呼叫端(db):
    """健康檢查：若 AST 解析器失效（如呼叫寫法改變），上面那條會因為「沒東西可比」而假性通過。

    ⚠️ 母體錨點是 DB 的範本列，不是解析結果——解析器整個壞掉時 `passed` 為空，本條會列出全部 9 支。
    """
    declared = await _declared_variables(db)
    passed = _passed_params()
    orphan = sorted(set(declared) - set(passed) - _INTENTIONALLY_UNWIRED)
    assert not orphan, f"下列範本找不到呼叫端，本守門對它們形同虛設：{orphan}"


async def test_豁免清單沒有多餘項目(db):
    """反向探針：豁免清單裡的範本若**接上了**呼叫端，要求把它移出清單、納入守門。

    沒有這條的話，`_INTENTIONALLY_UNWIRED` 會變成一張只進不出的名單——某支日後接線了卻
    仍被豁免，它的 params key 從此不受檢查，而兩條正向測試都還是綠的。
    """
    declared = await _declared_variables(db)
    passed = _passed_params()
    assert _INTENTIONALLY_UNWIRED <= set(declared), (
        f"豁免清單列了 DB 裡不存在的範本：{sorted(_INTENTIONALLY_UNWIRED - set(declared))}"
    )
    wired = sorted(_INTENTIONALLY_UNWIRED & set(passed))
    assert not wired, f"下列範本已接上呼叫端，請自 `_INTENTIONALLY_UNWIRED` 移除以納入守門：{wired}"


async def test_宣告端確實取到後續_migration_改寫過的值(db):
    """釘住「現況是最後一次寫入、不是 seed」這件事本身。

    `KPI_WEEKLY` 的 `VARIABLES` 於 `9eb4dd6e496b`（#332）被改寫過，seed `b7fa4b6e4fe7` 的舊值
    **不含** `lowest_list`。本測試初版正是讀 seed，因而對這支少驗一個變數卻全綠。

    這條在這裡的作用是：若日後有人為了「讓測試不依賴 DB」把宣告端改回解析 seed migration，
    它會立刻變紅，而不是靜默地退回舊的漏洞。
    """
    declared = await _declared_variables(db)
    assert "lowest_list" in declared["KPI_WEEKLY"], (
        "KPI_WEEKLY 的宣告未含 `lowest_list`——宣告端可能被改回讀 seed migration（見本檔 docstring）"
    )
