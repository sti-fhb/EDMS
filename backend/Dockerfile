# 建置用映像一律以 digest 鎖定：tag 可被上游改指，鎖 digest 才能確保建置可重現、不會在
# 不知情下吃進行為改變的映像。追版由 Dependabot（.github/dependabot.yml 的 docker
# ecosystem）每週檢查並開 PR 更新 digest；合併前須確認映像實際建得起來（ci.yml 不建本映像）。
#
# uv 寫成獨立階段而非 `COPY --from=ghcr.io/...`：Dependabot 只更新 FROM，寫在 COPY 裡會漏追版。
FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv

# 建置階段：以 uv 安裝依賴到 /app/.venv。
# uv 只在此階段使用，最終映像不放 uv／uvx：執行期本就不需要 uv，直接執行 .venv 內的指令即可。
# 兩個階段須用同一個基底（含 digest）：.venv 內的 python 指向基底映像的 /usr/local/bin/python3.12。
FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159 AS builder

COPY --from=uv /uv /bin/

WORKDIR /app

# 先複製依賴檔案（利用 Docker layer cache）
COPY pyproject.toml uv.lock ./

# 安裝 production 依賴（不含 dev）。
# --compile-bytecode：最終映像中 .venv 對執行身分唯讀，執行期寫不進 __pycache__，
# 不預先編譯就會每次啟動都重新編譯（不會報錯，只是變慢）。
# .venv/.lock 為 uv 的鎖檔（任何人可寫），執行期用不到，不帶進最終映像。
RUN uv sync --frozen --no-dev --no-cache --compile-bytecode \
    && rm -f /app/.venv/.lock

FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159

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
# 刻意不把 .venv/bin 加進 PATH：維持裸指令（python 等）解析到基底映像的系統路徑。

# 複製應用程式碼
COPY . .

# 設定 entrypoint 執行權限；預先編譯應用程式碼（理由同上方 --compile-bytecode）
RUN chmod +x entrypoint.sh \
    && /app/.venv/bin/python -m compileall -q /app/main.py /app/app /app/alembic

# 建立非 root 使用者執行應用，uid/gid 釘死為 10001：正式環境與院內把 host 目錄 bind mount
# 進下方兩個落盤根，host 端 owner 須與本使用者一致，屆時不要改動此 uid。
#
# 程式碼與 .venv 維持 root 持有、app 唯讀：應用程式即使被取得執行權，也無法改寫執行檔與
# 相依套件。app 只對兩個落盤根有寫入權——執行期寫入點僅有：
#   - /app/var/dm_files（DM_FILE_STORAGE_ROOT：DM 受控文件）
#   - /app/var/et_videos（ET_VIDEO_STORAGE_ROOT：ET 影片，暫存檔亦在其下以便 os.replace 原子搬移）
#   - /tmp（上傳 spool 等 tempfile）
# 部署時兩個落盤根以 bind mount 覆蓋；預先建好並 chown，未掛載（本機 named volume 首次
# 建立會沿用此 owner）時也寫得進去。
# ⚠️ 落盤根改到 /app/var 以外、或新增執行期寫檔位置時，須在此另建目錄並 chown，
#    否則會「啟動成功、health 通過，但上傳失敗」。
RUN addgroup --system --gid 10001 app && adduser --system --uid 10001 --ingroup app app \
    && mkdir -p /app/var/dm_files /app/var/et_videos \
    && chown app:app /app/var/dm_files /app/var/et_videos
USER app

# 院內為封閉網路，映像執行期不得依賴對外連線。直接執行 .venv 內的指令不會做任何依賴
# 同步，不再需要原本 `uv run` 搭配的 UV_NO_SYNC。
# 驗證方式：docker run --rm --network none <image> /app/.venv/bin/python -c "print('offline-ok')"
# （CD 與出版的「驗證映像可於封閉網路執行」步驟每次都會跑這件事）

EXPOSE 8000

CMD ["./entrypoint.sh"]
