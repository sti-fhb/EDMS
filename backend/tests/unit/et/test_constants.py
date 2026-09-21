"""ET Lookup 代碼常數（AC 2）。

2026-08-20 定案：9 類 Lookup **不建表、不 seed**，以應用層常數表達（比照 DM 之
`dm/detail/repository.py` `_OBSOLETE` 等模組層常數）。本測試鎖定代碼值與 data-model
§Lookup 代碼定義一致，避免日後有人改動常數卻未同步 spec。
"""

from app.et import constants as c


class TestRoleCodes:
    def test_三個角色代碼與_data_model_一致(self) -> None:
        assert c.ROLE_ADMIN == "ADMIN"
        assert c.ROLE_TEACHER == "TEACHER"
        assert c.ROLE_STUDENT == "STUDENT"
        assert c.ALL_ROLES == frozenset({"ADMIN", "TEACHER", "STUDENT"})


class TestCourseStatus:
    def test_三態且不含已廢除的_pending_close(self) -> None:
        assert c.ALL_COURSE_STATUSES == frozenset({"DRAFT", "PUBLISHED", "CLOSED"})
        # 2026-07-02 需求變更：PENDING_CLOSE 過渡狀態已移除、關閉改為可逆
        assert "PENDING_CLOSE" not in c.ALL_COURSE_STATUSES


class TestEnrollmentSource:
    def test_三種加入來源含標籤帶入(self) -> None:
        assert c.ALL_ENROLLMENT_SOURCES == frozenset({"EMAIL_INVITE", "INVITATION_CODE", "TAG_DEFAULT"})


class TestInvitationStatusRemoved:
    """`ET_INVITATION_STATUS` 隨 #362 廢除（原為 PENDING / JOINED / REVOKED）。

    邀請即加入之後沒有「待加入」這個中間狀態，整張 `ET_INVITATION` 一併移除。本條擋的
    是日後有人把它加回來卻沒重新檢討前提——見 `invitation/service.py` 模組 docstring
    的 🔴 那段（只邀請既有帳號才是這個決策成立的條件）。
    """

    def test_值域已不存在(self) -> None:
        assert not hasattr(c, "ALL_INVITATION_STATUSES")
        assert "ET_INVITATION_STATUS" not in c.LOOKUP_SETS


class TestAttemptStatus:
    def test_三態含逾時自動提交(self) -> None:
        assert c.ALL_ATTEMPT_STATUSES == frozenset({"IN_PROGRESS", "SUBMITTED", "TIMEOUT"})


class TestQuestionType:
    def test_單選多選(self) -> None:
        assert c.ALL_QUESTION_TYPES == frozenset({"SINGLE", "MULTIPLE"})


class TestItemType:
    def test_教材與測驗(self) -> None:
        assert c.ALL_ITEM_TYPES == frozenset({"MATERIAL", "QUIZ"})


class TestCompletionStatus:
    def test_三態(self) -> None:
        assert c.ALL_COMPLETION_STATUSES == frozenset({"NOT_STARTED", "IN_PROGRESS", "COMPLETED"})


class TestApprovalResult:
    def test_通過與不通過二態(self) -> None:
        # ET_APPROVAL 表屬 ET Issue #18，但代碼定義於本 issue 一併落地（data-model 列 9 類）
        assert c.ALL_APPROVAL_RESULTS == frozenset({"PASS", "FAIL"})


class TestLookupCoverage:
    def test_共九類代碼集合(self) -> None:
        """data-model §Lookup 代碼定義列 9 類，全部須有對應常數集合。

        沿革：#185 建置時 9 類 → #238（2026-08-28）新增 `ET_SURVEY_QUESTION_TYPE`
        （問卷加入問答題型，推翻「題型一律單選」）增為 10 類 → #362（2026-09-18）
        移除 `ET_INVITATION_STATUS`（邀請即加入，無中間狀態）回到 9 類。

        本條寫死類別數是刻意的：它是 `constants.py` 與 data-model §Lookup 之間唯一的
        守門。加了常數卻沒更新文件（或反之）時，這裡會先失敗。
        """
        assert len(c.LOOKUP_SETS) == 9
        # 每一類都非空，且成員皆為大寫英數底線（DB 欄位為 VARCHAR，值域由應用層把關）
        for name, values in c.LOOKUP_SETS.items():
            assert values, f"{name} 不得為空"
            assert all(v.replace("_", "").isalnum() and v.isupper() for v in values), name
