"""nginx 連線格位與慢速傳輸的設定契約（#833 B3）。

CI 不跑 nginx，這裡以設定檔內容釘住數值與它們之間的關係，並以官方原檔的副本實際執行建置腳本；
執行期行為（下載上限滿時回 503、API 照常、send_timeout 生效）於開發機以官方 nginx 實測，見 PR 說明。

## 問題

nginx 映像預設每個 worker 只有 1024 個連線格位，每條下載佔 2 格（客戶端一格、後端一格）。下載不寫
nginx 暫存之後（#810），慢速下載全程佔著格位；影片播放票不綁 IP，可分給多台機器用，每 IP 20 個的
`api_conn` 擋不住。格位用完時新連線一律進不來——**整站打不開**，不只下載。
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3]
_NGINX = _ROOT / "nginx"
_OFFICIAL = _ROOT / "backend" / "tests" / "fixtures" / "nginx_official_main.conf"
_TUNE = _NGINX / "tune-main-conf.sh"


def _read(name: str) -> str:
    return (_NGINX / name).read_text(encoding="utf-8")


def _directive(text: str, name: str) -> str:
    """取設定中某指令唯一一次出現的值（忽略註解行）。"""
    values = re.findall(rf"^\s*{re.escape(name)}\s+([^;]+);", text, re.M)
    assert len(values) == 1, f"{name} 應恰好出現一次，實得 {values}"
    return values[0].strip()


def _download_location() -> str:
    """送檔端點的 location 區塊（以 `proxy_max_temp_file_size 0` 辨識，#810 起只有它設）。"""
    blocks = re.findall(r"location ~ [^\n]*\{\n(.*?)\n    \}", _read("nginx.conf"), re.S)
    found = [b for b in blocks if "proxy_max_temp_file_size 0;" in b]
    assert len(found) == 1, "應恰有一個送檔 location"
    return found[0]


def _run_tune(conf: Path) -> subprocess.CompletedProcess:
    """以 POSIX sh 執行建置腳本（映像內是 busybox sh；CI 與開發機的 sh 皆可）。"""
    return subprocess.run(  # noqa: S603 —— 固定指令，參數為 repo 內的腳本與測試暫存檔
        ["sh", str(_TUNE), str(conf)],  # noqa: S607
        capture_output=True,
    )


@pytest.fixture
def tuned(tmp_path) -> str:
    """以官方原檔的副本執行建置腳本，回傳調整後的主設定。"""
    conf = tmp_path / "nginx.conf"
    shutil.copy(_OFFICIAL, conf)
    result = _run_tune(conf)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return conf.read_text(encoding="utf-8")


# ── 主設定（建置時就地調整）───────────────────────────────────────────


def test_映像建置時執行調整腳本():
    """`worker_connections` 只能寫在主設定的 events 區塊，conf.d/ 是 http 層、改不到。

    要在 `USER nginx` 之前執行：非 root 改不動 /etc/nginx/nginx.conf。
    """
    dockerfile = _read("Dockerfile")
    run = "RUN sh /tmp/tune-main-conf.sh /etc/nginx/nginx.conf"

    assert run in dockerfile
    assert dockerfile.index(run) < dockerfile.index("USER nginx")


def test_調整後的格位與_worker_數(tuned):
    assert _directive(tuned, "worker_processes") == "2"
    assert _directive(tuned, "worker_connections") == "4096"
    # 每條連線一個描述子，加上 log 等；不夠的話連線數還沒到上限就先 "Too many open files"
    assert int(_directive(tuned, "worker_rlimit_nofile")) >= 2 * 4096


def test_其餘內容與官方原檔相同(tuned):
    """只動三處：其餘（pid、log、include conf.d）若被改到，conf.d 的設定或 log 會失效。"""
    expected = (
        _OFFICIAL.read_text(encoding="utf-8")
        .replace("worker_processes  auto;", "worker_processes  2;")
        .replace("    worker_connections  1024;", "    worker_connections  4096;")
        .replace("\nevents {", "\nworker_rlimit_nofile 10240;\n\nevents {")
    )

    assert tuned == expected


def test_keepalive_仍為_65_秒(tuned):
    """跨 repo 約定：front-proxy（TBMS repo 的 edge/conf）的上游 keepalive 依賴「下游大於 60 秒」，
    否則 POST 會撞上被本層關掉的連線而回 502。本層不設，沿用官方預設，腳本把它當建置前提。"""
    assert _directive(tuned, "keepalive_timeout") == "65"


@pytest.mark.parametrize(
    ("original", "changed"),
    [
        ("    worker_connections  1024;", "    worker_connections  2048;"),
        ("worker_processes  auto;", "worker_processes  4;"),
        ("    keepalive_timeout  65;", "    keepalive_timeout  30;"),
    ],
    ids=["格位預設改了", "worker-數預設改了", "keepalive-預設改了"],
)
def test_官方預設檔改版時建置失敗而不是靜默套用(tmp_path, original, changed):
    """浮動版號的映像：官方預設改了就讓 CD 紅燈，由人對照後更新腳本。"""
    conf = tmp_path / "nginx.conf"
    conf.write_text(_OFFICIAL.read_text(encoding="utf-8").replace(original, changed), encoding="utf-8")

    assert _run_tune(conf).returncode != 0


# ── 全站下載上限 ──────────────────────────────────────────────────────


def _cap(zone: str) -> int:
    return int(re.search(rf"limit_conn {zone} (\d+);", _download_location()).group(1))


def test_下載上限以常數為鍵_DM_與_ET_分桶():
    """鍵是常數才是「全站」；鍵若帶 IP 就退化成每 IP 上限，擋不住多台機器分用播放票。"""
    rate = _read("rate-limit.conf")

    assert re.findall(r"^limit_conn_zone \$download_(\w+)_key zone=download_\1:", rate, re.M) == ["dm", "et"]
    assert re.search(r"map \$uri \$download_dm_key \{\s+~\^/api/dm/\s+\$server_name;\s+default\s+\"\";", rate)
    assert re.search(r"map \$uri \$download_et_key \{\s+~\^/api/et/\s+\$server_name;\s+default\s+\"\";", rate)
    assert len(re.findall(r"^\s*server_name\s", _read("nginx.conf"), re.M)) == 1, "只有一個 server，鍵才固定"


def test_送檔端點掛下載上限與送出逾時():
    block = _download_location()

    assert (_cap("download_dm"), _cap("download_et")) == (300, 700)
    assert "send_timeout 30s;" in block
    assert "limit_conn_log_level warn;" in block


def test_下載上限只掛在送檔端點():
    """誤掛到 `/api/` 就變成全站 API 同時只能 1000 個。"""
    conf = _read("nginx.conf")

    assert conf.count("limit_conn download_dm") == conf.count("limit_conn download_et") == 1


def test_送檔端點仍有每_IP_上限():
    """location 內的 limit_conn 會取代上層繼承的；`api_conn` 若被移到 server 層，送檔端點就悄悄失去它。"""
    assert "include /etc/nginx/api-proxy.conf;" in _download_location()
    assert "limit_conn api_conn 20;" in _read("api-proxy.conf")


def test_下載佔滿時仍留一半格位給頁面與_API(tuned):
    """本條是 B3 的目的：下載再多，頁面與 API 都還進得來。

    limit_conn 的 zone 由所有 worker 共用：1000 條最壞全落在同一個 worker，每條 2 格，仍不超過該 worker
    的一半。所以這個關係對每個 worker 都成立，與 worker 數無關——⛔ 不要以「worker 變多」為由放寬上限。
    """
    connections = int(_directive(tuned, "worker_connections"))

    assert 2 * (_cap("download_dm") + _cap("download_et")) <= connections // 2


# ── 慢速上傳 ─────────────────────────────────────────────────────────


def test_上傳端點縮短_body_讀取逾時():
    """上傳串流不緩衝（`proxy_request_buffering off`）：慢速送 body 的請求佔著後端的上傳名額（#833 A3），
    預設 60 秒的讀取間隔縮短為 30 秒。"""
    assert _directive(_read("api-upload.conf"), "client_body_timeout") == "30s"
