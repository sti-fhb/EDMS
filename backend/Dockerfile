FROM python:3.12-slim

# 安裝 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# 先複製依賴檔案（利用 Docker layer cache）
COPY pyproject.toml uv.lock ./

# 安裝 production 依賴（不含 dev）
RUN uv sync --frozen --no-dev --no-cache

# 複製應用程式碼
COPY . .

RUN chmod +x entrypoint.sh

# 建立非 root 使用者執行應用，uid/gid 釘死為 10001。
# 目前 EDMS 後端不寫檔案 log，故未如 TBMS 掛載 host 的 logs 目錄；日後若加入
# 檔案 log 而需 bind mount，owner 必須與本使用者一致，屆時不要改動此 uid。
RUN addgroup --system --gid 10001 app && adduser --system --uid 10001 --ingroup app app \
    && chown -R app:app /app
USER app

# uv 預設快取路徑對 non-root 使用者無寫入權限，改指向 /tmp
ENV UV_CACHE_DIR=/tmp/.uv-cache

# 執行期一律不做依賴同步，直接沿用上面 `uv sync --no-dev` 裝好的 .venv。
# 不設此項時，`uv run`（entrypoint 的 uvicorn、CD 的 alembic）每次啟動都會先把環境
# 同步到與 uv.lock 一致 —— 本映像刻意不裝 dev 依賴，uv 便判定缺漏而連線 PyPI 下載
# pytest 等套件。後果分兩種環境：
#   - 院內封閉網路（交付標的）：無對外連線，直接失敗，容器起不來、migration 也跑不了
#   - GCP CD：有網路故不會失敗，但每次啟動多裝一次 dev 依賴，且正式容器內混入測試套件
# 驗證方式：docker run --rm --network none <image> uv run alembic heads
# （CD 的「驗證映像可於封閉網路執行」步驟每次部署都會跑這件事）
ENV UV_NO_SYNC=1

EXPOSE 8000

CMD ["./entrypoint.sh"]
