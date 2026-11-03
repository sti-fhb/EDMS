"""正式環境 compose 的健康檢查與行程數上限（#833 B5、B6）。

CI 不跑 docker，這裡以設定內容釘住數值，並把健康檢查指令**實際執行**在一個假的 `/health` 上，
確認 200 / 503 / 連不上三種情況的結束碼——指令寫錯時 docker 只會默默顯示 unhealthy（或永遠 healthy）。
"""

import http.server
import shlex
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.prod.yml"


def _services() -> dict:
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))["services"]


# ── B5：後端健康檢查 ──────────────────────────────────────────────────


def test_後端有健康檢查():
    hc = _services()["edms-backend"]["healthcheck"]

    assert hc["test"][0] == "CMD"
    assert (hc["interval"], hc["timeout"], hc["retries"]) == ("30s", "10s", 3)
    assert "start_period" in hc, "啟動時跑 migration、暖機 bcrypt，給一段寬限期才開始算失敗"


def _serve(status: int) -> tuple[http.server.HTTPServer, int]:
    class _H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status if self.path == "/health" else 404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def _run_healthcheck(port: int) -> int:
    """以本機 python 執行 compose 裡的健康檢查指令（只把 port 換成假伺服器的）。"""
    cmd = _services()["edms-backend"]["healthcheck"]["test"][1:]
    assert cmd[0] == "python", "容器內是 python:3.12-slim，沒有 curl / wget"
    argv = [sys.executable, *[a.replace("127.0.0.1:8000", f"127.0.0.1:{port}") for a in cmd[1:]]]
    return subprocess.run(argv, capture_output=True, timeout=30).returncode  # noqa: S603 —— 固定指令，來自 repo 內設定


@pytest.mark.parametrize(("status", "healthy"), [(200, True), (503, False)], ids=["200-健康", "503-DB連不上"])
def test_健康檢查指令依_health_的狀態碼回結束碼(status, healthy):
    """`/health` 在 DB 連不上（含連線池滿、等不到連線）時回 503，那也要算不健康。"""
    server, port = _serve(status)
    try:
        code = _run_healthcheck(port)
    finally:
        server.shutdown()

    assert (code == 0) is healthy


def test_健康檢查指令在後端沒有回應時失敗():
    """event loop 卡住、行程掛掉：連不上也要回非 0，不能被當成健康。"""
    server, port = _serve(200)
    server.shutdown()
    server.server_close()

    assert _run_healthcheck(port) != 0


def test_健康檢查打的是容器內的後端():
    """`localhost` 可能先解析成 ::1 而連不上（uvicorn 只聽 0.0.0.0）；一律用 127.0.0.1。"""
    joined = shlex.join(_services()["edms-backend"]["healthcheck"]["test"])

    assert "http://127.0.0.1:8000/health" in joined


# ── B6：行程數與共享記憶體 ─────────────────────────────────────────────


def test_每個容器都有行程數上限():
    """擋 fork bomb 與行程失控（例如 ffprobe 子行程沒收掉）。用 `pids_limit` 而非較新的
    `deploy.resources.limits.pids`：VM 上的 compose 版本未知，舊版不認後者會讓部署整個失敗。"""
    services = _services()

    assert {name: s.get("pids_limit") for name, s in services.items()} == {
        "edms-backend": 256,
        "edms-nginx": 64,
        "edms-db": 200,
    }


def test_DB_的共享記憶體():
    """PostgreSQL 的平行查詢用 /dev/shm（預設只有 64 MB，不夠時查詢直接失敗）；算進 2 GB 記憶體上限。"""
    assert _services()["edms-db"]["shm_size"] == "256m"


def test_DB_未調整_max_connections():
    """DB 的 `pids_limit` 200 依 `max_connections` 預設 100 估算（每條連線一個行程）。日後調大連線數而
    沒重估，連線數還沒到上限就先 fork 失敗——這條在那時提醒（security review）。"""
    command = " ".join(_services()["edms-db"].get("command", []))

    assert "max_connections" not in command


def test_外部的_health_有限流():
    """`/health` 未登入可打、每次都查 DB：沒有限流時可被灌來搶連線池（security review）。"""
    conf = (Path(__file__).resolve().parents[3] / "nginx" / "nginx.conf").read_text(encoding="utf-8")
    block = conf[conf.index("location = /health {") :]
    block = block[: block.index("}")]

    assert "limit_conn api_conn 20;" in block
    assert "limit_req zone=api_limit" in block
