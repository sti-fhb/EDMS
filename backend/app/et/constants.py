"""ET Lookup 代碼定義（應用層常數，**不建表**）。

2026-08-20 定案（#185）：本專案無 lookup 代碼表機制——DM 之狀態欄位為 `String(20)`，
無 lookup 表、無 CHECK constraint、無 Enum，代碼以模組層常數表達（如
`app/dm/detail/repository.py` 之 `_OBSOLETE` / `_BROWSABLE_STATUSES`）。ET 若為 9 類代碼
各建一張表，將與 DM / DP 做法分歧並平白多出 9 張表與其維護成本。

因此 9 類代碼一律以本模組之常數表達；DB 欄位維持 `VARCHAR`，**值域由應用層把關**
（不加 CHECK constraint，比照 DM）。權威定義見 `docs/specs/et/data-model.md`
§Lookup 代碼定義；改動常數時必須同步該文件。

跨多個功能模組共用者（角色 / 課程狀態 / 完課狀態）集中於此；僅單一功能模組使用者
亦置於此以便一處對照 spec。
"""

from typing import Final, Literal

# ── ET_USER_ROLE_TYPE：使用者於 ET 之角色（可多重指派，權限取聯集）──────────────
RoleCode = Literal["ADMIN", "TEACHER", "STUDENT"]

ROLE_ADMIN: Final = "ADMIN"
ROLE_TEACHER: Final = "TEACHER"
ROLE_STUDENT: Final = "STUDENT"

ALL_ROLES: Final = frozenset({ROLE_ADMIN, ROLE_TEACHER, ROLE_STUDENT})

# ── ET_COURSE_STATUS：課程狀態 ────────────────────────────────────────────────
# DRAFT → PUBLISHED ⇄ CLOSED（2026-07-02 變更：關閉可逆，PENDING_CLOSE 過渡狀態已移除）
CourseStatus = Literal["DRAFT", "PUBLISHED", "CLOSED"]

COURSE_DRAFT: Final = "DRAFT"
COURSE_PUBLISHED: Final = "PUBLISHED"
COURSE_CLOSED: Final = "CLOSED"

ALL_COURSE_STATUSES: Final = frozenset({COURSE_DRAFT, COURSE_PUBLISHED, COURSE_CLOSED})

# ── ET_ENROLLMENT_SOURCE：學員加入課程之來源 ──────────────────────────────────
# TAG_DEFAULT 為 2026-07-02 變更後之標籤自動邀請（原 MODULE_DEFAULT 已廢除）
EnrollmentSource = Literal["EMAIL_INVITE", "INVITATION_CODE", "TAG_DEFAULT"]

SOURCE_EMAIL_INVITE: Final = "EMAIL_INVITE"
SOURCE_INVITATION_CODE: Final = "INVITATION_CODE"
SOURCE_TAG_DEFAULT: Final = "TAG_DEFAULT"

ALL_ENROLLMENT_SOURCES: Final = frozenset({SOURCE_EMAIL_INVITE, SOURCE_INVITATION_CODE, SOURCE_TAG_DEFAULT})

# ── ET_INVITATION_STATUS：Email 邀請狀態（JOINED / REVOKED 為終態）─────────────
InvitationStatus = Literal["PENDING", "JOINED", "REVOKED"]

INVITATION_PENDING: Final = "PENDING"
INVITATION_JOINED: Final = "JOINED"
INVITATION_REVOKED: Final = "REVOKED"

ALL_INVITATION_STATUSES: Final = frozenset({INVITATION_PENDING, INVITATION_JOINED, INVITATION_REVOKED})

# ── ET_ATTEMPT_STATUS：測驗作答狀態 ───────────────────────────────────────────
AttemptStatus = Literal["IN_PROGRESS", "SUBMITTED", "TIMEOUT"]

ATTEMPT_IN_PROGRESS: Final = "IN_PROGRESS"
ATTEMPT_SUBMITTED: Final = "SUBMITTED"
ATTEMPT_TIMEOUT: Final = "TIMEOUT"

ALL_ATTEMPT_STATUSES: Final = frozenset({ATTEMPT_IN_PROGRESS, ATTEMPT_SUBMITTED, ATTEMPT_TIMEOUT})

# ── ET_QUESTION_TYPE：題型（多選採部分計分）───────────────────────────────────
QuestionType = Literal["SINGLE", "MULTIPLE"]

QUESTION_SINGLE: Final = "SINGLE"
QUESTION_MULTIPLE: Final = "MULTIPLE"

ALL_QUESTION_TYPES: Final = frozenset({QUESTION_SINGLE, QUESTION_MULTIPLE})

# ── ET_ITEM_TYPE：章節項目類型（MATERIAL_ID / QUIZ_ID 互斥）────────────────────
ItemType = Literal["MATERIAL", "QUIZ"]

ITEM_MATERIAL: Final = "MATERIAL"
ITEM_QUIZ: Final = "QUIZ"

ALL_ITEM_TYPES: Final = frozenset({ITEM_MATERIAL, ITEM_QUIZ})

# ── ET_COMPLETION_STATUS：完課狀態（即時計算）─────────────────────────────────
CompletionStatus = Literal["NOT_STARTED", "IN_PROGRESS", "COMPLETED"]

COMPLETION_NOT_STARTED: Final = "NOT_STARTED"
COMPLETION_IN_PROGRESS: Final = "IN_PROGRESS"
COMPLETION_COMPLETED: Final = "COMPLETED"

ALL_COMPLETION_STATUSES: Final = frozenset({COMPLETION_NOT_STARTED, COMPLETION_IN_PROGRESS, COMPLETION_COMPLETED})

# ── ET_APPROVAL_RESULT：線下核可結果 ──────────────────────────────────────────
# `ET_APPROVAL` 表屬 ET Issue #18（2026-07-17 線下核可），代碼定義於本 issue 一併落地
ApprovalResult = Literal["PASS", "FAIL"]


# （PASS = 考核通過 / FAIL = 不通過），與密碼無關。
APPROVAL_PASS: Final = "PASS"  # noqa: S105
APPROVAL_FAIL: Final = "FAIL"

ALL_APPROVAL_RESULTS: Final = frozenset({APPROVAL_PASS, APPROVAL_FAIL})

# ── 全部 9 類之對照（供測試與文件比對；非執行期邏輯使用）──────────────────────
LOOKUP_SETS: Final[dict[str, frozenset[str]]] = {
    "ET_USER_ROLE_TYPE": ALL_ROLES,
    "ET_COURSE_STATUS": ALL_COURSE_STATUSES,
    "ET_ENROLLMENT_SOURCE": ALL_ENROLLMENT_SOURCES,
    "ET_INVITATION_STATUS": ALL_INVITATION_STATUSES,
    "ET_ATTEMPT_STATUS": ALL_ATTEMPT_STATUSES,
    "ET_QUESTION_TYPE": ALL_QUESTION_TYPES,
    "ET_ITEM_TYPE": ALL_ITEM_TYPES,
    "ET_COMPLETION_STATUS": ALL_COMPLETION_STATUSES,
    "ET_APPROVAL_RESULT": ALL_APPROVAL_RESULTS,
}
