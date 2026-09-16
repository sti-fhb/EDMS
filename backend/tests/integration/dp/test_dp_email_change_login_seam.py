"""Email 變更期間「哪一個信箱能登入」（ET-14 / #341 T121 / AC 6）。

## 盤點查到的缺口

`test_dp_user_profile.py::test_email_change_request_creates_token_and_pending` 的 docstring
寫著「EMAIL 未變（**舊仍可登入**）」，但它的斷言只有：

```python
assert user.email == "old@edms.local" and user.pending_email == "new@edms.local"
```

**全 repo 沒有任何測試在 `PENDING_EMAIL` 有值的狀態下真的打一次登入。** 「舊信箱仍可登入」
是從「`EMAIL` 欄位沒變」**推論**出來的，不是驗出來的。

而登入查詢會不會誤中 `PENDING_EMAIL`，正是這條 AC 唯一要問的事——同一個 repository
裡就有一支 `email_taken_for_change()` **刻意同時看 `EMAIL` 與 `PENDING_EMAIL`**
（`repository.py:43`）。兩支查詢對「Email」的定義不同是**設計**，但也正因如此，哪天有人
為了「一致性」把 `get_by_email` 也加上 `pending_email` 的條件，資料層斷言不會紅，
而使用者會在自己都還沒確認新信箱之前就能用它登入——延遲生效的意義整個消失。

## 為什麼要走完整條時間軸

AC 6 的兩個半句（「驗證後切換」「未驗證前舊 Email 仍可登入」）描述的是**同一個帳號在三個
時點**的行為。分成三條各自建資料的測試也會全綠，但驗不到「切換」本身——真正會出事的是
狀態轉移，不是任一時點的靜態樣貌。
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.exceptions import AppError
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.user.email_change_service import EmailChangeService
from app.dp.user.models import DpPwdReset
from app.dp.user.service import AuthService
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_PWD = "Abcd1234"
_OLD = "before-change@edms.local"
_NEW = "after-change@edms.local"


class _NotifyStub:
    """記錄 send_email 呼叫；驗證連結由此取出（避免依賴真範本渲染）。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send_email(self, db, *, recipients, template_code, module, params, caller_module):
        self.calls.append({"recipients": recipients, "params": params})


async def _user(db, *, user_id: str, email: str) -> DpUser:
    now = utcnow()
    user = DpUser(
        user_id=user_id,
        email=email,
        pwd_hash=hash_password(_PWD),
        user_name="換信箱測試",
        status="ACTIVE",
        login_fail_count=0,
        pwd_changed_date=now - timedelta(days=1),
        must_change_pwd=False,
        created_user="admin01",
        created_date=now,
    )
    db.add(user)
    await db.flush()
    return user


async def _request_change(db, *, user_id: str, new_email: str) -> str:
    """送出變更申請，回傳驗證信裡的明文 token。"""
    notify = _NotifyStub()
    await EmailChangeService(notify=notify).request(db, user_id=user_id, new_email=new_email)
    assert notify.calls[0]["recipients"] == [new_email], "驗證信必須寄到**新**信箱"
    return notify.calls[0]["params"]["verify_link"].split("token=")[1]


async def _login_ok(db, email: str) -> None:
    result = await AuthService().login(db, email=email, password=_PWD)
    assert result.access_token, f"{email} 應可登入"


async def _login_rejected(db, email: str) -> AppError:
    with pytest.raises(AppError) as exc:
        await AuthService().login(db, email=email, password=_PWD)
    assert exc.value.status_code == 401
    return exc.value


class TestPendingWindow:
    """未驗證期間：兩個信箱同時存在於系統裡，但只有舊的能認證。"""

    async def test_申請後舊信箱仍可實際登入(self, db) -> None:
        """既有測試只斷言 `EMAIL` 欄位沒變；這條真的走一次登入。

        差別在：欄位沒變**不蘊含**登入查得到——中間隔著 `get_by_email` 的 where 條件。
        """
        await _user(db, user_id="ec_stay", email=_OLD)
        await _request_change(db, user_id="ec_stay", new_email=_NEW)

        await _login_ok(db, _OLD)

    async def test_申請後新信箱尚不可登入(self, db) -> None:
        """延遲生效的**實質**定義：`PENDING_EMAIL` 不是可用來認證的身分。

        同一個 repository 的 `email_taken_for_change()` 刻意同時看 `EMAIL` 與 `PENDING_EMAIL`
        （唯一性檢核需要），若有人為「一致性」把 `get_by_email` 一起改掉，使用者在自己確認
        新信箱之前就能用它登入——這條是唯一會紅的守衛。
        """
        await _user(db, user_id="ec_notyet", email=_OLD)
        await _request_change(db, user_id="ec_notyet", new_email=_NEW)

        err = await _login_rejected(db, _NEW)
        assert err.error_code == "DP_AUTH_007", "新信箱此時對系統而言就是「查無帳號」"

    async def test_兩個信箱同時存在但只有一個能認證(self, db) -> None:
        """「雙信箱共存」的完整樣貌：DB 裡兩欄都有值，而認證只認其中一欄。

        資料面與行為面在同一條裡比對，才看得出「共存」不等於「都能用」。
        """
        await _user(db, user_id="ec_both", email=_OLD)
        await _request_change(db, user_id="ec_both", new_email=_NEW)

        user = (await db.execute(select(DpUser).where(DpUser.user_id == "ec_both"))).scalar_one()
        assert user.email == _OLD and user.pending_email == _NEW, "兩欄應同時有值"

        await _login_ok(db, _OLD)
        await _login_rejected(db, _NEW)


class TestAfterVerify:
    """驗證之後：身分**整個換過去**，不是兩個都能用。"""

    async def test_驗證後新信箱可登入(self, db) -> None:
        await _user(db, user_id="ec_done", email=_OLD)
        token = await _request_change(db, user_id="ec_done", new_email=_NEW)

        await EmailChangeService().verify(db, token=token)

        await _login_ok(db, _NEW)

    async def test_驗證後舊信箱不可再登入(self, db) -> None:
        """切換必須是**取代**而非新增。

        少了這條，把 verify 實作成「只寫 `EMAIL`、不清 `PENDING_EMAIL`」之類的半套改法
        仍會讓上一條通過，而舊信箱的持有者（可能正是要被移除的那個人）會保有登入能力。
        """
        await _user(db, user_id="ec_moved", email=_OLD)
        token = await _request_change(db, user_id="ec_moved", new_email=_NEW)
        await EmailChangeService().verify(db, token=token)

        await _login_ok(db, _NEW)  # 先確認新信箱真的生效，避免下面的 401 其實是「帳號壞了」
        err = await _login_rejected(db, _OLD)
        assert err.error_code == "DP_AUTH_007"


class TestExpiredChange:
    """逾時未驗證：回到原點，不留半套狀態。"""

    async def test_逾時後舊信箱繼續有效(self, db) -> None:
        """使用者申請了卻沒點連結，不該因此失去登入能力。

        `EMAIL` 從未被動過，所以「舊的還能用」在實作上是必然——但這條的價值在於，它會在
        有人把切換提前到申請步（例如為了少一次寫入）時轉紅。
        """
        await _user(db, user_id="ec_expire", email=_OLD)
        await _request_change(db, user_id="ec_expire", new_email=_NEW)

        token_row = (await db.execute(select(DpPwdReset).where(DpPwdReset.user_id == "ec_expire"))).scalar_one()
        token_row.expires_date = utcnow() - timedelta(minutes=1)
        await db.flush()

        await _login_ok(db, _OLD)

    async def test_逾時後新信箱始終不可登入(self, db) -> None:
        await _user(db, user_id="ec_expire2", email=_OLD)
        await _request_change(db, user_id="ec_expire2", new_email=_NEW)

        token_row = (await db.execute(select(DpPwdReset).where(DpPwdReset.user_id == "ec_expire2"))).scalar_one()
        token_row.expires_date = utcnow() - timedelta(minutes=1)
        await db.flush()

        err = await _login_rejected(db, _NEW)
        assert err.error_code == "DP_AUTH_007"
