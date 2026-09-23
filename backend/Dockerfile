FROM python:3.12-slim

# ffmpeg：本專案**唯一的系統層依賴**（其餘 11 個皆為純 Python 套件）。
# ET 教材影片上傳時以其中的 `ffprobe` 解析長度，而 `ET_MATERIAL_VIDEO.DURATION_SEC`
# 是 ET05 觀看覆蓋率的分母、data-model 訂為 NOT NULL，故**取不到不得存檔**。
#
# 🔴 少了它，**所有影片一律上傳失敗**（422 `ET_MATERIAL_004`「無法解析影片長度」），
#    與檔案大小無關。#360 就是這樣壞的：README 第 80、214 行都寫明「映像檔須加裝
#    ffmpeg」，但本 Dockerfile 從 #254 起就沒裝，而**沒有任何東西會因此變紅**——
#    CI runner 自己裝了（`ci.yml` 的「確保 ffmpeg 可用」），所以測試全綠；本機開發
#    照 README 裝了，所以開發時正常。只有部署環境壞，且症狀是一則看似在講格式的
#    錯誤訊息（「請改用其他格式」），會把人導向去換影片檔而不是查環境。
#
# 放在最前面是為了 layer cache：它幾乎不變，擺在 COPY 程式碼之後會讓每次改碼都重裝。
# `--no-install-recommends` 省掉一批用不到的編解碼週邊；`rm -rf` 不留 apt 索引。
# 本行需要 build 時有網路——院內封閉網路的約束管的是**執行期**（見下方 UV_NO_SYNC），
# build 一律在 CI 進行，不受該約束。
#
# ⚠️ 移除或改動本行前，先確認 `cd.yml` 的「驗證映像內含 ffprobe」仍會擋下。
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

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
