"""上傳共用層加固（#211 L1）整合測試：US5 文件上傳與 US8 廢止附件兩條 HTTP 路徑行為一致。

兩條路徑共用 `file_store.read_upload`（讀取時即把關大小）與 `resolve_upload_mime`（檔頭驗真實型別）；
純函式層的邊界（超限中止、各格式檔頭）由 `tests/unit/dm/test_dm_file_store_hardening.py` 驗證，
本檔只驗「接線」：偽裝副檔名的檔案在兩條路徑都回同一個 422，且未落盤。

⚠️ 不斷言 DB「未寫入」：請求以 AppError 結束時，測試共用的 session 會被 rollback、連種子資料一起消失，
事後查 DB 恆為空，那種斷言證明不了任何事。檔案系統不受 rollback 影響，才是能觀察到的副作用。
"""

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.config import settings
from app.core.utils import utcnow
from app.dm.catalog.models import DmTag
from app.dm.document.models import DmDocument
from app.dm.roles.authz import DM_EDITOR, DM_REVIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
#: `.exe` 的檔頭，副檔名卻是 `.docx`——改版前 Office 類只驗副檔名，會照樣落盤
_RENAMED_EXE = ("evil.docx", b"MZ\x90\x00 renamed exe", _DOCX)


@pytest.fixture
def storage_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DM_FILE_STORAGE_ROOT", str(tmp_path))
    return tmp_path


async def _seed_user(db, user_id, role):
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@e.com",
            pwd_hash="x",
            user_name=user_id,
            pwd_changed_date=now,
            created_user="seed",
            created_date=now,
        )
    )
    await db.flush()
    db.add(DmUserRole(user_id=user_id, role_code=role, created_user="seed", created_date=now))
    await db.flush()


async def _tag_id(db, group, name):
    return await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == group, DmTag.tag_name == name))


def _assert_rejected_as_mismatch(resp, storage_dir):
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "DM_FILE_005"
    assert not any(p.is_file() for p in storage_dir.rglob("*")), "檔頭不符的檔案不得落盤"


async def test_us5_document_upload_rejects_renamed_executable(db, client, storage_dir):
    await _seed_user(db, "editor1", DM_EDITOR)
    token = create_access_token(sub="editor1", ttl_minutes=15)

    resp = await client.post(
        "/api/dm/documents",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "doc_name": "偽裝檔",
            "category_code": "SOP",
            "version_no": "1.0",
            "change_summary": "首版",
            "audience_unit_ids": [await _tag_id(db, "UNIT", "全單位")],
            "audience_role_ids": [await _tag_id(db, "AUDIENCE", "全體")],
        },
        files={"file": _RENAMED_EXE},
    )

    _assert_rejected_as_mismatch(resp, storage_dir)


async def test_us8_obsolete_attachment_rejects_renamed_executable(db, client, storage_dir):
    await _seed_user(db, "editor1", DM_EDITOR)
    await _seed_user(db, "rev1", DM_REVIEWER)
    now = utcnow()
    db.add(
        DmDocument(
            doc_id="DM-SOP-000901",
            doc_name="現行文件",
            category_code="SOP",
            status="PUBLISHED",
            created_user="editor1",
            created_date=now,
        )
    )
    await db.flush()
    token = create_access_token(sub="editor1", ttl_minutes=15)

    resp = await client.post(
        "/api/dm/documents/DM-SOP-000901/obsolete",
        headers={"Authorization": f"Bearer {token}"},
        data={"reason": "流程停辦", "reviewer_id": "rev1"},
        files={"file": _RENAMED_EXE},
    )

    _assert_rejected_as_mismatch(resp, storage_dir)
