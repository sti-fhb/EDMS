"""上線前安全不變量（ET-14 / #341 T123 / AC 9）。

AC 9 列了四項上線門檻。前三項在程式碼裡**已經成立**，但**沒有任何測試守著**——它們靠的是
函式庫預設值或設定檔預設值，而那兩者都會在升級或改設定時無聲改變。本檔把它們釘住。

| AC 9 項目 | 現況 | 本檔 |
|---|---|---|
| 密碼雜湊 ≥ bcrypt cost 12 | ✅ 實測 `$2b$12$`，但**未明訂**——來自 passlib 預設 | 釘住 |
| SMTP 採 TLS | ✅ `MAIL_STARTTLS` 預設 true + production 檢查 | 釘住兩者 |
| token ≥ 32 bytes CSPRNG | ✅ `secrets.token_urlsafe(32)` | 釘住長度與熵來源 |
| 防帳號列舉 | ⚠️ 見 `tests/integration/dp/test_dp_login_no_enumeration.py`（#208）與殘留 #345 / #346 | 不在本檔 |

## 為什麼「已經成立」還需要測試

三項的共同形狀是**沒有人寫下過門檻**：

- bcrypt 的 12 round 是 passlib 當前版本的預設。passlib 升級改預設值不會有任何警告，
  而 `pyproject.toml` 沒有釘 passlib 的次版本
- `MAIL_STARTTLS: bool = True` 是欄位預設。任何人把 `.env` 寫成 `MAIL_STARTTLS=false`
  在 `DEBUG=true` 的環境下完全合法，而那正是「測試環境的設定被複製到別處」的起點
- token 長度寫在呼叫端（`secrets.token_urlsafe(32)`），不是常數

**這些不是「可能會壞」，是「壞了不會有人知道」**——沒有錯誤訊息、沒有紅燈，只有強度下降。
"""

import os
import re
import secrets

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
    """AC 9-2：SMTP 採 TLS。"""

    def _settings(self, **over) -> Settings:
        """建一份**除了待測項目外全部合法**的 production 設定。

        ⚠️ `Settings` 有多道 production 檢核（JWT 金鑰長度、`FRONTEND_BASE_URL` 不得為空或
        指向 localhost、MAIL TLS…）。基準設定若漏掉任何一項，下面那些「應拋 ValidationError」
        的測試會**因為錯的理由而通過**——撰寫初版時就是如此（漏了 `FRONTEND_BASE_URL`，
        兩條 TLS 測試綠得毫無意義）。故各條另以 `_tls_error` 確認錯的是 TLS 那一項。
        """
        base = {
            "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/x",
            "JWT_SECRET_KEY": "x" * 64,
            "FRONTEND_BASE_URL": "https://edms.example.gov.tw",
            "TRUSTED_PROXY_COUNT": 0,
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

    def test_production_明文_smtp_被拒絕啟動(self) -> None:
        """**啟動即失敗**，不是執行期才發現。

        若只在寄信當下檢查，明文設定會一路上線到第一封信寄出——而那封信的帳密與內容
        已經明文送出去了。
        """
        self._tls_error(MAIL_STARTTLS=False, MAIL_SSL_TLS=False)

    def test_implicit_tls_亦為合法(self) -> None:
        """埠 465 走 implicit TLS，同樣加密，不該被上一條的檢查誤擋。"""
        assert self._settings(MAIL_STARTTLS=False, MAIL_SSL_TLS=True, MAIL_PORT=465).MAIL_SSL_TLS is True

    def test_兩種_tls_不可同時啟用(self) -> None:
        """STARTTLS 是明文連線後升級、SSL_TLS 是一開始就加密；同時開會連不上。

        這條與上面兩條不同——它擋的不是弱設定，是**無效設定**，症狀是寄不出信而非不安全。
        """
        assert "不可同時" in self._tls_error(MAIL_STARTTLS=True, MAIL_SSL_TLS=True)

    def test_未設定_mail_server_時不強制(self) -> None:
        """尚未接上 SMTP 的環境（含本機開發）不該因此起不來。"""
        assert self._settings(MAIL_SERVER="", MAIL_STARTTLS=False, MAIL_SSL_TLS=False).MAIL_SERVER == ""


class TestProductionStartupGuards:
    """`DEBUG=false` 時**啟動即擋**的設定護欄總表。

    這組不對應 AC 9 的任一項，而是 T124（部署文件）的依據：部署時每一項設錯都會讓
    服務**起不來**，所以它們就是最短的上線檢查清單。逐項釘住是為了兩件事：

    1. 護欄被移除時會紅——它們都是「設錯了不會有錯誤訊息、只有靜默劣化」那一類，
       所以護欄本身就是唯一的偵測手段
    2. 部署文件與程式碼不會分岔——文件若漏列一項，這裡的清單仍然是完整的

    ⚠️ 撰寫本檔時逐一撞出了其中四項（原本只知道 MAIL TLS）。這說明**光讀 `config.py`
    的欄位定義看不出有幾道護欄**，它們散在五個 `model_validator` 裡。
    """

    def _base(self) -> dict:
        return {
            "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/x",
            "JWT_SECRET_KEY": "x" * 64,
            "FRONTEND_BASE_URL": "https://edms.example.gov.tw",
            "TRUSTED_PROXY_COUNT": 0,
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
            ("DM_FILE_STORAGE_ROOT", "./var/dm_files", "相對路徑依工作目錄解析，換啟動位置全部檔案讀不到"),
            ("ET_VIDEO_STORAGE_ROOT", "./var/et_videos", "同上"),
            ("MAIL_STARTTLS", False, "明文 SMTP，帳密與信件內容明文上線"),
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
