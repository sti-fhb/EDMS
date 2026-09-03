#!/bin/sh
set -e

# Migration 由 CD pipeline 獨立執行（docker compose run --rm），
# 不在 entrypoint 跑，避免多副本同時啟動時的 race condition。

# --no-access-log：uvicorn 的 access log 之 request line 含 query string，
# 存取記錄改由 nginx 負責（已設為不記 query string，見 nginx/log-format.conf）。
exec uv run uvicorn main:app --host 0.0.0.0 --port 8000 --no-access-log
