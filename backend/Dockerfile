# 建置階段：以 uv 安裝依賴到 /app/.venv。
# uv 只在此階段使用，最終映像不放 uv／uvx：執行期本就不需要 uv，直接執行 .venv 內的指令即可。
# 兩個階段須用同一個基底：.venv 內的 python 指向基底映像的 /usr/local/bin/python3.12。
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/

WORKDIR /app

# 先複製依賴檔案（利用 Docker layer cache）
COPY pyproject.toml uv.lock ./

# 安裝 production 依賴（不含 dev）
RUN uv sync --frozen --no-dev --no-cache

FROM python:3.12-slim

# ffmpeg：本專案**唯一的系統層依賴**，其餘相依皆為純 Python 套件。
# （此處原本寫「其餘 11 個」，但那個數字隨 pyproject 增刪而漂移、沒人會記得改——
#   2026-10-06 實際已是 13 個。改成不帶數字，以免下一個讀的人被誤導。）
# ET 教材影片上傳時以其中的 `ffprobe` 解析長度，而 `ET_MATERIAL_VIDEO.DURATION_SEC`
# 是 ET06 觀看覆蓋率的分母、data-model 訂為 NOT NULL，故**取不到不得存檔**。
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
# 本行需要 build 時有網路——院內封閉網路的約束管的是**執行期**（見檔尾說明），
# build 一律在 CI 進行，不受該約束。
#
# ⚠️ 移除或改動本行前，先確認 `cd.yml` 的「驗證映像內含 ffprobe」仍會擋下。
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 移除基底映像內建的 pip：依賴一律由 uv 安裝進 /app/.venv，執行期不使用系統 pip。
RUN python -m pip uninstall -y pip

COPY --from=builder /app/.venv /app/.venv

# 執行期一律直接用 .venv 內的指令（uvicorn、alembic、python），不經 uv run。
# 呼叫端（entrypoint、CD、vm-deploy.sh、TBMS 院內交付包）寫絕對路徑 /app/.venv/bin/<指令>。
# ⚠️ 刻意不把 .venv/bin 加進 PATH：/app 整個歸 app 使用者所有（見下方 chown），
#    加進 PATH 後以 root 進容器打裸指令（python、alembic）就會執行 app 可改寫的檔案。

# 複製應用程式碼
COPY . .

RUN chmod +x entrypoint.sh

# 建立非 root 使用者執行應用，uid/gid 釘死為 10001。
# 目前 EDMS 後端不寫檔案 log，故未如 TBMS 掛載 host 的 logs 目錄；日後若加入
# 檔案 log 而需 bind mount，owner 必須與本使用者一致，屆時不要改動此 uid。
RUN addgroup --system --gid 10001 app && adduser --system --uid 10001 --ingroup app app \
    && chown -R app:app /app
USER app

# 院內為封閉網路，映像執行期不得依賴對外連線。直接執行 .venv 內的指令不會做任何依賴
# 同步，不再需要原本 `uv run` 搭配的 UV_NO_SYNC。
# 驗證方式：docker run --rm --network none <image> /app/.venv/bin/python -c "print('offline-ok')"
# （CD 與出版的「驗證映像可於封閉網路執行」步驟每次都會跑這件事）

EXPOSE 8000

CMD ["./entrypoint.sh"]
