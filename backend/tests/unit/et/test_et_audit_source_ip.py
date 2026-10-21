"""ET 模組的稽核一律帶來源 IP（#790）。

2026-10-21 盤點：ET 排程以外寫稽核的 19 處呼叫中，有 11 處沒帶 `source_ip`，DP05 的來源 IP
因此顯示「—」。漏掉的除了 issue 回報的個資匯出，還有另外 10 處：移除學員、重設重測次數、角色指派、
課程內容維護等，重要性都不在個資匯出之下。

逐處補整合測試的成本高，而漏帶的形狀很單純（呼叫少一個關鍵字參數），故以結構檢查守住：
掃描 `app/et` 每一個 `log_action(...)` 呼叫，**排程以外**都必須帶 `source_ip=`。日後新增稽核時
漏帶，這條會紅並指出位置。

⚠️ 排程（`app/et/schedules/`）沒有發起請求的使用者，`get_client_ip()` 恆為 `None`，刻意不帶。
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ET_ROOT = Path(__file__).resolve().parents[3] / "app" / "et"
#: 沒有 request 的路徑：排程由 APScheduler 觸發，來源 IP 不存在。
_NO_REQUEST_DIRS = {"schedules"}


def _log_action_calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "log_action"
    ]


def _request_path_calls() -> list[tuple[str, ast.Call]]:
    calls: list[tuple[str, ast.Call]] = []
    for path in sorted(_ET_ROOT.rglob("*.py")):
        rel = path.relative_to(_ET_ROOT)
        if rel.parts[0] in _NO_REQUEST_DIRS:
            continue
        calls.extend((f"app/et/{rel.as_posix()}:{call.lineno}", call) for call in _log_action_calls(path))
    return calls


def test_掃描範圍確實涵蓋_ET_的稽核呼叫() -> None:
    """正向錨點：路徑寫錯或掃描邏輯壞掉時，下一條會因為「沒有呼叫」而空洞地通過。"""
    assert len(_request_path_calls()) >= 15


def test_使用者操作觸發的稽核都帶來源_IP() -> None:
    missing = [where for where, call in _request_path_calls() if not any(kw.arg == "source_ip" for kw in call.keywords)]
    assert missing == [], f"以下稽核漏帶 source_ip=get_client_ip()：{missing}"
