"""影片播放票（US5 / #255）。

票會進 URL 與 access log，故三道限制各自要有測試釘住：60 秒有效、綁單一影片、
與 access token 嚴格區隔。**第三道最關鍵**——若票能當一般 token 用，一個從 log 撈到
的票就等於一組帳號憑證。
"""

from datetime import timedelta
from unittest.mock import patch

import jwt
import pytest

from app.core.auth import create_access_token
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.utils import utcnow
from app.et.learning.video_ticket import TICKET_TTL_SECONDS, issue_video_ticket, verify_video_ticket

pytestmark = pytest.mark.unit


class TestIssueAndVerify:
    def test_簽發之票可驗證並回使用者(self) -> None:
        token = issue_video_ticket(user_id="stu001", video_id=42)
        assert verify_video_ticket(token, video_id=42) == "stu001"

    def test_有效期為六十秒(self) -> None:
        assert TICKET_TTL_SECONDS == 60
        raw = jwt.decode(
            issue_video_ticket(user_id="stu001", video_id=42),
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        assert raw["exp"] - raw["iat"] == 60


class TestScopedToOneVideo:
    def test_他支影片之票不通過(self) -> None:
        """票綁 `vid`——外洩也只能取那一支。"""
        token = issue_video_ticket(user_id="stu001", video_id=42)
        with pytest.raises(AppError) as exc:
            verify_video_ticket(token, video_id=43)
        assert exc.value.status_code == 404
        assert exc.value.error_code == "ET_LEARN_001"


class TestExpiry:
    def test_過期之票不通過(self) -> None:
        with patch("app.et.learning.video_ticket.utcnow", return_value=utcnow() - timedelta(seconds=120)):
            stale = issue_video_ticket(user_id="stu001", video_id=42)
        with pytest.raises(AppError) as exc:
            verify_video_ticket(stale, video_id=42)
        assert exc.value.error_code == "ET_LEARN_001"


class TestTypeIsolation:
    """**票與 access token 不可互換**——本檔最重要的一組。"""

    def test_一般_access_token_不可當票用(self) -> None:
        """否則等於把長效登入憑證引進 URL。"""
        token = create_access_token(sub="stu001", ttl_minutes=15)
        with pytest.raises(AppError) as exc:
            verify_video_ticket(token, video_id=42)
        assert exc.value.error_code == "ET_LEARN_001"

    def test_票不帶一般_token_之語意(self) -> None:
        """票的 claim 集刻意與 access token 不同。

        `decode_access_token` 需要 `auth_time` 等 claim；票沒有那些，故即使有人把票
        丟去一般認證閘也不會被當成有效登入。
        """
        from app.core.auth import decode_access_token

        ticket = issue_video_ticket(user_id="stu001", video_id=42)
        with pytest.raises(AppError):
            decode_access_token(ticket)

    def test_竄改簽章不通過(self) -> None:
        token = issue_video_ticket(user_id="stu001", video_id=42)
        forged = jwt.encode(
            {"sub": "attacker", "vid": 42, "typ": "et-video-ticket", "exp": 9999999999},
            "wrong-secret",
            algorithm=settings.JWT_ALGORITHM,
        )
        assert token != forged
        with pytest.raises(AppError):
            verify_video_ticket(forged, video_id=42)
