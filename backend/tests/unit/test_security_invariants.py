"""上線前安全不變量（ET-14 / #341 T123 / AC 9）。

AC 9 列了四項上線門檻。前三項在程式碼裡**已經成立**，但**沒有任何測試守著**——它們靠的是
函式庫預設值或設定檔預設值，而那兩者都會在升級或改設定時無聲改變。本檔把它們釘住。

| AC 9 項目 | 現況 | 本檔 |
|---|---|---|
| 密碼雜湊 ≥ bcrypt cost 12 | ✅ 實測 `$2b$12$`，但**未明訂**——來自 passlib 預設 | 釘住 |
| SMTP 採 TLS | ⚠️ #585 撤銷強制：改為預設 STARTTLS、部署端可設明文 | 釘住預設與明文可啟動 |
| token ≥ 32 bytes CSPRNG | ✅ `secrets.token_urlsafe(32)` | 釘住長度與熵來源 |
| 防帳號列舉 | ⚠️ 見 `tests/integration/dp/test_dp_login_no_enumeration.py`（#208）與殘留 #345 / #346 | 不在本檔 |

## 為什麼「已經成立」還需要測試

三項的共同形狀是**沒有人寫下過門檻**：

- bcrypt 的 12 round 是 passlib 當前版本的預設。passlib 升級改預設值不會有任何警告，
  而 `pyproject.toml` 沒有釘 passlib 的次版本
- `MAIL_STARTTLS: bool = True` 是欄位預設。#585 起 `MAIL_STARTTLS=false` 在任何環境都合法
  （不再有 production 檢查），所以**預設值是唯一剩下的保護**——沒寫 MAIL 加密設定的環境
  仍會走 STARTTLS
- token 長度寫在呼叫端（`secrets.token_urlsafe(32)`），不是常數

**這些不是「可能會壞」，是「壞了不會有人知道」**——沒有錯誤訊息、沒有紅燈，只有強度下降。
"""

import os
import re
import secrets
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.password_policy import hash_password
from app.dp.user.token import generate_reset_token

pytestmark = pytest.mark.unit

#: production 落盤根需絕對路徑；Windows 另需磁碟機，故不能寫死 "/srv/"。
_ABS_ROOT = os.path.join(os.path.abspath(os.sep), "srv", "edms_")

#: AC 9 明訂的下限。bcrypt 的 cost 是 2 的指數，每 +1 運算量加倍。
_MIN_BCRYPT_COST = 12

#: AC 9 明訂的下限（bytes of entropy）。
_MIN_TOKEN_ENTROPY_BYTES = 32


class TestPasswordHashing:
    """AC 9-1：密碼雜湊強度 ≥ bcrypt cost 12。"""

    def test_雜湊使用_bcrypt_且_cost_不低於十二(self) -> None:
        """從實際產出的雜湊字串解析 cost，而非讀設定——設定可能根本沒設（現況就是）。

        modular crypt format：`$2b$12$<22 字元 salt><31 字元 hash>`。
        """
        digest = hash_password("Abcd1234")

        match = re.match(r"^\$2[aby]\$(\d{2})\$", digest)
        assert match is not None, f"不是 bcrypt 的 modular crypt format：{digest[:10]}"
        cost = int(match.group(1))
        assert cost >= _MIN_BCRYPT_COST, (
            f"bcrypt cost {cost} 低於 AC 9 門檻 {_MIN_BCRYPT_COST}。"
            "此值目前來自 passlib 預設、未於 CryptContext 明訂——若因套件升級而下降，"
            "除了本測試沒有任何地方會發現。"
        )

    def test_每次雜湊帶不同_salt(self) -> None:
        """同一個密碼雜湊兩次必須不同，否則彩虹表可直接比對。"""
        assert hash_password("Abcd1234") != hash_password("Abcd1234")

    def test_超長密碼被擋而非靜默截斷(self) -> None:
        """bcrypt 只雜湊前 72 bytes。不擋的話，共用前 72 bytes 的兩個密碼會互相通過驗證。"""
        with pytest.raises(Exception) as exc:  # 型別由 AppError 保證，此處只驗「有擋」
            hash_password("a" * 73)
        assert exc.value is not None


class TestTokenEntropy:
    """AC 9-3：所有 token 使用 CSPRNG 且 ≥ 32 bytes。"""

    def test_重設_token_長度符合三十二_bytes_之_urlsafe_編碼(self) -> None:
        """`secrets.token_urlsafe(32)` 產出 43 字元（32 bytes → base64url 無 padding）。

        以**長度**驗熵：43 字元是 32 bytes 的必然結果，少一個字元就代表有人改小了參數。
        """
        token = generate_reset_token()

        expected_len = len(secrets.token_urlsafe(_MIN_TOKEN_ENTROPY_BYTES))
        assert len(token) == expected_len, (
            f"token 長度 {len(token)} ≠ {_MIN_TOKEN_ENTROPY_BYTES} bytes 的編碼長度 {expected_len}"
        )
        assert re.fullmatch(r"[A-Za-z0-9_-]+", token), "應為 urlsafe base64 字元集"

    def test_連續產生不重複(self) -> None:
        """不是統計檢定，只擋「忘了每次重新產生」這類低級錯誤（例如被快取成常數）。"""
        assert len({generate_reset_token() for _ in range(64)}) == 64


class TestMailTransportSecurity:
    """AC 9-2：SMTP 採 TLS——#585 撤銷「production 強制 TLS」，只保留預設值與互斥檢查。

    撤銷理由：院內郵件主機只提供埠 25、不加密、以 IP 授權（與 TBMS 同組設定），強制 TLS 會讓
    EDMS 在該環境起不來，現場只能以 `DEBUG=true` 繞過——而那會連帶關掉
    FRONTEND_BASE_URL、TRUSTED_PROXY_COUNT、儲存路徑等 production 護欄，代價比明文寄信更大。
    加密方式改由部署端依郵件主機決定。
    """

    def _settings(self, **over) -> Settings:
        """建一份**除了待測項目外全部合法**的 production 設定。

        ⚠️ `Settings` 有多道 production 檢核（JWT 金鑰長度、`FRONTEND_BASE_URL` 不得為空或
        指向 localhost…）。基準設定若漏掉任何一項，下面「應拋 ValidationError」的測試會
        **因為錯的理由而通過**——撰寫初版時就是如此（漏了 `FRONTEND_BASE_URL`，
        當時的 TLS 測試綠得毫無意義）。故互斥那條另以 `_tls_error` 確認錯的是 TLS 那一項；
        反過來「應可啟動」的測試也靠這份基準全部合法才有意義。
        """
        base = {
            "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/x",
            "JWT_SECRET_KEY": "x" * 64,
            "FRONTEND_BASE_URL": "https://edms.example.gov.tw",
            "TRUSTED_PROXY_COUNT": 0,
            "SEED_DEMO_ACCOUNTS": False,
            "DM_FILE_STORAGE_ROOT": _ABS_ROOT + "dm",
            "ET_VIDEO_STORAGE_ROOT": _ABS_ROOT + "et",
            "MAIL_SERVER": "smtp.example.gov.tw",
            "DEBUG": False,
            "MAIL_SUPPRESS_SEND": False,
        }
        base.update(over)
        # `_env_file=None`：`Settings` 預設會讀 `backend/.env`，而本機開發用的 .env 為了
        # 不連真 SMTP 會把 TLS 關掉（合法，因為它同時設了 DEBUG / MAIL_SUPPRESS_SEND）。
        # 不隔離的話本檔驗到的是**這台機器的設定**而非程式碼的預設值與檢核——
        # 「預設啟用 STARTTLS」那條會直接被本機 .env 弄紅。
        return Settings(_env_file=None, **base)

    def _tls_error(self, **over) -> str:
        """取得因 TLS 設定而起的錯誤訊息；若是別的檢核先擋下就讓測試紅。"""
        with pytest.raises(ValidationError) as exc:
            self._settings(**over)
        message = str(exc.value)
        assert "MAIL" in message or "TLS" in message or "SMTP" in message, (
            f"擋下請求的不是 TLS 檢核，本測試沒有驗到目標：{message}"
        )
        return message

    def test_預設啟用_starttls(self) -> None:
        """讀**欄位定義**而非實例——實例會被這台機器的 `.env` / 環境變數覆蓋。

        本機開發用的 `.env` 就把 `MAIL_STARTTLS` 設成 false（合法：它同時設了 `DEBUG=true`），
        所以拿實例來驗「預設值」只會驗到當下這台機器的設定。
        """
        assert Settings.model_fields["MAIL_STARTTLS"].default is True
        assert Settings.model_fields["MAIL_SSL_TLS"].default is False, "兩者互斥，預設只能開一個"

    def test_production_明文_smtp_可啟動(self) -> None:
        """埠 25 不加密在 `DEBUG=false` 下可正常啟動（#585）——不必再靠 `DEBUG=true` 繞過。

        `MAIL_SUPPRESS_SEND=False`、`MAIL_SERVER` 已設由 `_settings` 基準保證：兩者任一不成立，
        舊檢查本來就會放行，這條就驗不到「檢查已移除」。
        """
        s = self._settings(MAIL_STARTTLS=False, MAIL_SSL_TLS=False, MAIL_PORT=25)
        assert (s.DEBUG, s.MAIL_SUPPRESS_SEND, bool(s.MAIL_SERVER)) == (False, False, True)

    def test_implicit_tls_亦為合法(self) -> None:
        """埠 465 走 implicit TLS，不該被下面的互斥檢查誤擋。"""
        assert self._settings(MAIL_STARTTLS=False, MAIL_SSL_TLS=True, MAIL_PORT=465).MAIL_SSL_TLS is True

    def test_兩種_tls_不可同時啟用(self) -> None:
        """STARTTLS 是明文連線後升級、SSL_TLS 是一開始就加密；同時開會連不上。

        它擋的不是弱設定，是**無效設定**，症狀是寄不出信而非不安全——所以 #585 撤銷強制 TLS 時保留。
        """
        assert "不可同時" in self._tls_error(MAIL_STARTTLS=True, MAIL_SSL_TLS=True)


class TestProductionStartupGuards:
    """`DEBUG=false` 時**啟動即擋**的設定護欄總表。

    這組不對應 AC 9 的任一項，而是 T124（部署文件）的依據：部署時每一項設錯都會讓
    服務**起不來**，所以它們就是最短的上線檢查清單。逐項釘住是為了兩件事：

    1. 護欄被移除時會紅——它們都是「設錯了不會有錯誤訊息、只有靜默劣化」那一類，
       所以護欄本身就是唯一的偵測手段
    2. 部署文件與程式碼不會分岔——文件若漏列一項，這裡的清單仍然是完整的

    ⚠️ 撰寫本檔時逐一撞出了其中四項（原本只知道 MAIL TLS 那一道，該道已由 #585 撤銷）。這說明**光讀 `config.py`
    的欄位定義看不出有幾道護欄**，它們散在五個 `model_validator` 裡。
    """

    def _base(self) -> dict:
        return {
            "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/x",
            "JWT_SECRET_KEY": "x" * 64,
            "FRONTEND_BASE_URL": "https://edms.example.gov.tw",
            "TRUSTED_PROXY_COUNT": 0,
            "SEED_DEMO_ACCOUNTS": False,
            "DM_FILE_STORAGE_ROOT": _ABS_ROOT + "dm",
            "ET_VIDEO_STORAGE_ROOT": _ABS_ROOT + "et",
            "MAIL_SERVER": "smtp.example.gov.tw",
            "MAIL_STARTTLS": True,
            "MAIL_SSL_TLS": False,
            "DEBUG": False,
            "MAIL_SUPPRESS_SEND": False,
        }

    def test_全部設妥時可正常建立(self) -> None:
        """基準必須成立，否則下面每一條都會因為錯的理由而通過。"""
        assert Settings(_env_file=None, **self._base()).DEBUG is False

    @pytest.mark.parametrize(
        ("field", "bad_value", "why"),
        [
            ("JWT_SECRET_KEY", "short", "金鑰太短，簽章可被離線暴力破解"),
            ("FRONTEND_BASE_URL", "", "信件連結會組成空網域，使用者點不到"),
            ("FRONTEND_BASE_URL", "http://localhost:5173", "信件連結指向開發機"),
            ("TRUSTED_PROXY_COUNT", None, "未明示則限流與稽核的來源 IP 可被偽造"),
            ("SEED_DEMO_ACCOUNTS", None, "未明示則沿用預設 true，正式環境種入示範帳號"),
            ("DM_FILE_STORAGE_ROOT", "./var/dm_files", "相對路徑依工作目錄解析，換啟動位置全部檔案讀不到"),
            ("ET_VIDEO_STORAGE_ROOT", "./var/et_videos", "同上"),
            # MAIL_STARTTLS=false 已非護欄（#585 撤銷強制 TLS），見 TestMailTransportSecurity
        ],
    )
    def test_單項設錯即拒絕啟動(self, field: str, bad_value, why: str) -> None:
        """其餘欄位全部合法，只壞一項——證明擋下來的確實是這一項。"""
        settings = self._base()
        if bad_value is None:
            settings.pop(field)
        else:
            settings[field] = bad_value

        with pytest.raises(ValidationError) as exc:
            Settings(_env_file=None, **settings)
        assert field in str(exc.value), f"錯誤訊息未指出是哪一項（{field}：{why}）"

    def test_dev_不受這些護欄約束(self) -> None:
        """`DEBUG=true` 時全部放行——本機開發不必準備絕對路徑與真網域。

        這條同時說明了護欄的**限制**：它們只在 `DEBUG=false` 生效，所以「正式環境誤設
        `DEBUG=true`」是唯一能繞過全部護欄的一步，部署文件須單獨列出。
        """
        dev = {
            "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/x",
            "JWT_SECRET_KEY": "x" * 64,
            "DEBUG": True,
            "MAIL_SERVER": "smtp.example.gov.tw",
            "MAIL_STARTTLS": False,
            "MAIL_SSL_TLS": False,
            "DM_FILE_STORAGE_ROOT": "./var/dm_files",
        }
        assert Settings(_env_file=None, **dev).DEBUG is True


class TestCSP設定契約:
    """`nginx/security-headers.conf` 的 CSP 指令清單（#366）。

    這份設定不經任何測試——它是 nginx 設定檔，本機 dev 走 vite **完全不經 nginx**，
    所以 CSP 的缺漏只在部署環境出現。而 CSP 違規**只進瀏覽器 console**，不會變成前端
    錯誤：#366 的症狀是學員端 PDF 預覽「一個空框」——blob 取得成功、`error` 為 null、
    `loading` 已結束，三個條件分支全走完卻沒東西可顯示。

    ⚠️ **本檔的其他測試釘的是「函式庫預設值會無聲改變」，這一組釘的是另一種東西：
    CSP 的 fallback 機制會讓「少寫一條」看起來像「沒設限制」。** 未宣告的 fetch
    directive 回落到 `default-src`，而 `default-src 'self'` 不含 `blob:`——所以漏寫
    `frame-src` 不是「沒限制」，是「限制成 'self'」，方向與直覺相反。
    """

    _CONF = Path(__file__).resolve().parents[2].parent / "nginx" / "security-headers.conf"

    def _csp(self) -> str:
        text = self._CONF.read_text(encoding="utf-8")
        match = re.search(r'add_header\s+Content-Security-Policy\s+"([^"]+)"', text)
        assert match is not None, f"找不到 CSP 設定行：{self._CONF}"
        return match.group(1)

    def _directive(self, name: str) -> str | None:
        for part in self._csp().split(";"):
            tokens = part.split()
            if tokens and tokens[0] == name:
                return " ".join(tokens[1:])
        return None

    def test_設定檔存在(self) -> None:
        assert self._CONF.is_file(), f"路徑推導錯誤：{self._CONF}"

    @pytest.mark.parametrize(
        ("directive", "用途"),
        [
            ("img-src", "favicon/svg 與檔案下載預覽"),
            ("media-src", "ET 影音教材播放"),
            ("frame-src", "學員端 PDF 教材預覽（iframe 載入 blob URL）"),
        ],
    )
    def test_需要_blob_的指令都明確放行(self, directive: str, 用途: str) -> None:
        """每個要用 blob URL 的指令都**必須自己宣告**，不能靠 `default-src` 兜。

        這條若紅了，代表對應的功能在部署環境會安靜失效——沒有錯誤訊息、CI 全綠。
        """
        value = self._directive(directive)
        assert value is not None, f"{directive} 未宣告 → 回落到 default-src 'self'，{用途} 會被擋"
        assert "blob:" in value, f"{directive} 未放行 blob: → {用途} 會被擋（現值：{value}）"

    def test_default_src_不含_blob_故不能靠它兜(self) -> None:
        """釘住「為什麼每條都要自己寫」的前提。

        若日後有人為了省事把 `blob:` 加進 `default-src`，上面那組測試會**假綠**——
        因為回落機制讓所有未宣告的指令都拿到 blob:。那是放寬全站而非修好個別功能。
        """
        default_src = self._directive("default-src")
        assert default_src is not None
        assert "blob:" not in default_src, "default-src 放行 blob: 等於全站放寬，應逐條宣告"

    def test_反向的三道限制未被放寬(self) -> None:
        """⛔ `frame-ancestors` / `object-src` 管的是**反方向**，不該為了 #366 動它們。

        - `frame-ancestors 'none'`：別人不能 iframe 本站（防點擊劫持）
        - `object-src 'none'`：`<object>` / `<embed>` 全禁

        `frame-src` 管的是「本站能 iframe 什麼」。三者容易混淆，而放寬前兩者是安全性
        退步**且修不好** PDF 預覽——這是 #366 最容易被亂試出來的錯誤修法，故釘住。
        """
        assert self._directive("frame-ancestors") == "'none'"
        assert self._directive("object-src") == "'none'"

    def test_nginx_是全站安全標頭的來源(self) -> None:
        """釘住「這份設定就是全站來源」這件事本身，不擴及 app 端。

        本來想順手釘「app 端不得再設 nosniff」（設定檔第 19-20 行明文警告會疊出兩個同名
        header），但寫完一跑就被推翻：`app/et/learning/router.py:183` **刻意**在影片串流
        回應上加 `nosniff`，且附完整理由——該端點以 `inline` 回使用者上傳的位元組，關掉
        MIME 嗅探是縱深防禦。

        所以設定檔那句警告針對的是「全站再設一次」（middleware），不是個別端點的防禦。
        兩者的差別沒有寫在設定檔裡，已回報到 #263 一併釐清。
        """
        conf = self._CONF.read_text(encoding="utf-8")
        for header in ("X-Content-Type-Options", "Referrer-Policy", "Content-Security-Policy"):
            assert header in conf, f"{header} 不在 nginx 設定內——全站來源的前提不成立"

    def test_style_src_以_nonce_放行而非_unsafe_inline(self) -> None:
        """行內樣式以每次請求的 nonce 放行，不開 `'unsafe-inline'`。

        MUI／Emotion 與 tiptap 都在執行期注入 `<style>`。nonce 由 nginx 的 `$request_id`
        產生，同一個值以 sub_filter 寫進 index.html 的 `<meta name="csp-nonce">`
        （見 `Test前端快取設定契約`），前端讀出後交給 Emotion cache 與 tiptap 的 `injectNonce`。
        """
        style_src = self._directive("style-src")
        assert style_src is not None
        assert "'unsafe-inline'" not in style_src, f"style-src 仍放行 'unsafe-inline'（現值：{style_src}）"
        assert "'nonce-$request_id'" in style_src, f"style-src 未以請求 nonce 放行（現值：{style_src}）"


class Test前端快取設定契約:
    """`nginx/nginx.conf` 的快取指令（#441）。

    SPA 的正確設定是**一組不對稱的規則**：入口 HTML 每次回源驗證、雜湊資產永久快取。
    少了前半就是 #441 —— `index.html` 沒有任何 `Cache-Control`，瀏覽器改用啟發式快取
    自行決定存多久，而它指向的舊 bundle 是 `immutable, max-age=31536000`，會從本機
    快取秒載、整年不重抓。使用者跑的是一個完全舊版的前端，且**沒有任何跡象**。

    ⚠️ 2026-09-29 手測 #428 時實際被咬：程式已合併、CD 已 build、VM 已部署、線上
    bundle 抓下來 grep 得到新字串，但測試者瀏覽器跑的是舊版。**而舊版底下 6 個測試
    項目有 4 項看起來照樣通過**，回報長成「大部分都對，只有兩項怪怪的」，把人推向去
    查那兩項的程式邏輯。

    這份設定和 `TestCSP設定契約` 一樣不經任何執行期測試（本機 dev 走 vite 完全不經
    nginx），故同樣以解析設定檔的方式釘住。
    """

    _CONF = Path(__file__).resolve().parents[2].parent / "nginx" / "nginx.conf"

    def _location(self, pattern: str) -> str:
        """取出指定 location 區塊的內容（單層大括號，本檔無巢狀 location）。"""
        text = self._CONF.read_text(encoding="utf-8")
        start = text.find(f"location {pattern} {{")
        assert start != -1, f"找不到 location {pattern}：{self._CONF}"
        depth = 0
        for i in range(text.index("{", start), len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        raise AssertionError(f"location {pattern} 的大括號未閉合")

    def test_設定檔存在(self) -> None:
        assert self._CONF.is_file(), f"路徑推導錯誤：{self._CONF}"

    def test_index_html_每次回源驗證(self) -> None:
        """SPA 入口不得被瀏覽器自行決定快取多久。

        這條若紅了，部署新版之後使用者可能繼續跑舊版前端，且看起來像是程式沒生效。
        """
        block = self._location("/")
        match = re.search(r'add_header\s+Cache-Control\s+"([^"]+)"', block)
        assert match is not None, "location / 未設 Cache-Control → 瀏覽器啟發式快取決定存多久（#441）"
        value = match.group(1)
        assert "no-cache" in value or "no-store" in value, (
            f"location / 的 Cache-Control 必須要求回源驗證，現值：{value}"
        )

    def test_location_根目錄有重新_include_安全標頭(self) -> None:
        """🔴 加了 `add_header` 就必須重新 include —— 否則 HTML 回應**靜默失去全部安全標頭**。

        nginx 的繼承規則：location 內只要出現任何一個 `add_header`，server 層的
        `add_header` 就**全部失效**。`security-headers.conf` 的檔頭與靜態資源那個
        location（第 37-38 行）都記著這件事。

        ⚠️ 本條釘的是「#441 的修法自己不要製造一個更大的洞」：CSP / HSTS / nosniff
        全部由 server 層的 include 提供，而承載它們的**正是 HTML 回應**。掉了不會有
        任何錯誤訊息，CSP 違規只進瀏覽器 console。
        """
        block = self._location("/")
        if "add_header" not in block:
            pytest.skip("location / 沒有 add_header，未觸發遮蔽規則")
        assert "include /etc/nginx/security-headers.conf" in block, (
            "location / 有 add_header 但未重新 include security-headers.conf"
            " → CSP / HSTS / nosniff 會從 HTML 回應上消失"
        )

    def test_雜湊資產仍為長效不可變快取(self) -> None:
        """⛔ 反方向的限制：不要為了修 #441 把靜態資產也改成不快取。

        Vite 產出的檔名帶內容雜湊，內容變了檔名就變，故永久快取是**正確且必要**的
        （否則每次進站重抓整包 bundle）。#441 的病根是入口 HTML 沒設，不是資產設錯。
        把資產一起改成 `no-cache` 會讓症狀消失而代價是全站變慢——那是最容易亂試出來
        的錯誤修法，故釘住。
        """
        block = self._location(r"~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$")
        match = re.search(r'add_header\s+Cache-Control\s+"([^"]+)"', block)
        assert match is not None, "靜態資產的 Cache-Control 不見了"
        value = match.group(1)
        assert "immutable" in value, f"雜湊資產應為 immutable，現值：{value}"
        assert "no-cache" not in value and "no-store" not in value, (
            f"雜湊資產不該關閉快取（#441 的病根在入口 HTML，不在這裡）：{value}"
        )

    def test_index_html_代換_csp_nonce(self) -> None:
        """SPA 入口把佔位字串換成本次請求的 `$request_id`，與 CSP 標頭的 nonce 為同一個值。

        漏了這行時 meta 仍是佔位字串、前端不帶 nonce，全站 MUI 樣式被 CSP 擋掉——本機
        dev 走 vite 不經 nginx，只有部署後才看得到。
        """
        block = self._location("/")
        assert "sub_filter '__CSP_NONCE__' '$request_id';" in block, "location / 未代換 CSP nonce 佔位字串"
        index_html = (self._CONF.parent.parent / "frontend" / "index.html").read_text(encoding="utf-8")
        assert '<meta name="csp-nonce" content="__CSP_NONCE__" />' in index_html, (
            "frontend/index.html 缺少 CSP nonce 佔位 meta"
        )

    def test_不揭露_nginx_版本(self) -> None:
        """nginx 自產錯誤頁（404、限流、上游不通）的內文會帶版本字串，並被 front-proxy 原樣轉送。"""
        text = self._CONF.read_text(encoding="utf-8")
        assert re.search(r"^\s*server_tokens\s+off;", text, re.MULTILINE), "nginx.conf 未設 server_tokens off"


class Test轉址契約:
    """`nginx/nginx.conf` 的轉址指令：一律送根相對的 Location，由 front-proxy 補回 `/edms` 前綴。

    本層不知道外部的 scheme 與掛載前綴，故轉址（目錄補尾斜線、後端 `redirect_slashes`）
    一律送根相對路徑，front-proxy 的 `proxy_redirect / /edms/;` 再補上前綴。

    與上面兩組契約同理，本機 dev 走 vite 不經 nginx，故以解析設定檔釘住；
    執行期行為見 `scripts/tests/test_nginx_redirects.sh`（需 docker）。
    """

    _NGINX_DIR = Path(__file__).resolve().parents[2].parent / "nginx"
    _CONF = _NGINX_DIR / "nginx.conf"
    # 會被 location include 的 proxy 設定：其中若另寫 proxy_redirect，會遮蔽 server 層那一條
    _INCLUDED = ("api-proxy.conf", "api-upload.conf")

    def _server_level(self) -> str:
        """server 區塊內、所有 location 之外的指令（去掉註解）。"""
        lines, depth = [], 0
        for raw in self._CONF.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0]
            if depth == 1 and not re.match(r"^\s*location\b", line):
                lines.append(line)
            depth += line.count("{") - line.count("}")
        return "\n".join(lines)

    def _directives(self, path: Path, name: str) -> list[str]:
        text = path.read_text(encoding="utf-8")
        return [m.group(0) for m in re.finditer(rf"^\s*{name}\s[^;]*;", text, re.MULTILINE)]

    def test_目錄補尾斜線送相對路徑(self) -> None:
        assert re.search(r"^\s*absolute_redirect\s+off;", self._server_level(), re.MULTILINE), (
            "nginx.conf 的 server 層未設 absolute_redirect off"
        )

    def test_後端轉址改寫為相對路徑(self) -> None:
        assert re.search(r"^\s*proxy_redirect\s+http://edms-backend/\s+/;", self._server_level(), re.MULTILINE), (
            "nginx.conf 的 server 層未設 proxy_redirect http://edms-backend/ /"
        )

    def test_proxy_redirect_只有_server_層一處(self) -> None:
        """location（含被 include 的檔）內另寫 proxy_redirect 會整組取代 server 層的設定。"""
        found = self._directives(self._CONF, "proxy_redirect")
        for name in self._INCLUDED:
            found += self._directives(self._NGINX_DIR / name, "proxy_redirect")
        assert len(found) == 1, f"proxy_redirect 應只在 nginx.conf 的 server 層出現一次，實際：{found}"
