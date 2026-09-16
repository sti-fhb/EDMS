"""「DM 下載 → KPI 已看」端到端接縫測試（ET-14 / #341 AC 12）。

## 為什麼這一檔要單獨存在

`DM_DOC_READ` 的**寫入端**與**讀取端**各自都有測試，但**中間那段沒有**：

- `test_dm_detail.py::test_download_current_writes_read_and_dedup` 驗「下載會寫 `DM_DOC_READ`」，
  但用的是 `DM_EDITOR` context，而 KPI 母體只認 `DM_VIEWER`——就算寫進去了，KPI 也不會動。
- `test_dm_kpi.py` 驗 KPI 算式，但自行 `db.add(DmDocRead(...))` 造列，**從不經過下載端點**。

兩端各自為真，不蘊含「使用者按下下載，KPI 就會動」。本檔是目前**唯一**會走完整條路徑的測試：
真使用者 → HTTP 下載端點 → `DM_DOC_READ` → KPI 查詢端點。

## 為什麼不能省

「KPI 已看沒反應」有四個**設計性**原因（同人同版去重、母體兩層、預覽不寫、稽核下載不寫）。
少了這一檔，任何一個原因被誤改成 bug、或任何一端重構時把中間的契約弄斷，CI 都照樣全綠——
因為兩端的測試各自都還會過。
"""

import pytest
from sqlalchemy import func, select

from app.core.auth import create_access_token
from app.core.config import settings
from app.core.utils import utcnow
from app.dm.audience.models import DmUserTag
from app.dm.catalog.models import DmCategory, DmFunc, DmTag  # noqa: F401  # 註冊 FK 目標
from app.dm.document.models import DmDocRead, DmDocTag, DmDocument, DmDocVersion
from app.dm.roles.authz import DM_ADMIN, DM_VIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration


def _headers(sub: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=sub, ttl_minutes=15)}"}


async def _user(db, user_id: str, *roles: str) -> None:
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@e.com",
            pwd_hash="x",
            user_name=user_id,
            status="ACTIVE",
            pwd_changed_date=utcnow(),
            created_user="seed",
            created_date=utcnow(),
        )
    )
    await db.flush()
    for role in roles:
        db.add(DmUserRole(user_id=user_id, role_code=role, created_user="seed", created_date=utcnow()))
    await db.flush()


async def _audience_tag_id(db, tag_name: str) -> int:
    return await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "AUDIENCE", DmTag.tag_name == tag_name))


async def _doc_with_real_file(db, tmp_path, doc_id: str, *, version_no: str = "1.0") -> int:
    """建一份掛「全體」的已發布文件，且**磁碟上真的有檔**（FileResponse 會實際串流）。

    回目前發布版的 `version_id`。
    """
    path = tmp_path / f"{doc_id}-{version_no}.pdf"
    path.write_bytes(b"%PDF-1.4 seam")
    doc = await db.get(DmDocument, doc_id)
    if doc is None:
        doc = DmDocument(
            doc_id=doc_id,
            doc_name=f"文件{doc_id}",
            category_code="SOP",
            status="PUBLISHED",
            created_user="author",
            created_date=utcnow(),
        )
        db.add(doc)
        await db.flush()
        db.add(
            DmDocTag(
                doc_id=doc_id,
                tag_id=await _audience_tag_id(db, "全體"),
                created_user="seed",
                created_date=utcnow(),
            )
        )
    version = DmDocVersion(
        doc_id=doc_id,
        version_no=version_no,
        change_summary="摘要",
        file_name=f"{version_no}.pdf",
        file_path=str(path),
        file_size=path.stat().st_size,
        file_mime="application/pdf",
        status="PUBLISHED",
        published_date=utcnow(),
        created_user="author",
        created_date=utcnow(),
    )
    db.add(version)
    await db.flush()
    doc.current_version_id = version.version_id
    await db.flush()
    return version.version_id


def _file_url(doc_id: str, version_id: int, *, disposition: str = "download") -> str:
    return f"/api/dm/documents/{doc_id}/versions/{version_id}/file?disposition={disposition}"


async def _kpi_row(client, admin_id: str, doc_id: str) -> dict:
    """以管理者身分查 KPI，取回該文件那一列。"""
    resp = await client.get("/api/dm/kpi/documents", params={"limit": 100}, headers=_headers(admin_id))
    assert resp.status_code == 200, resp.text
    rows = [r for r in resp.json()["data"] if r["doc_id"] == doc_id]
    assert len(rows) == 1, f"KPI 應恰有一列 {doc_id}，實得 {len(rows)}"
    return rows[0]


async def _read_rows(db, doc_id: str) -> int:
    return await db.scalar(select(func.count()).select_from(DmDocRead).where(DmDocRead.doc_id == doc_id))


class TestDownloadToKpiSeam:
    """AC 12：閱覽者按下下載之後，管理者的 KPI 真的會動。"""

    async def test_閱覽者下載後已看由零變一(self, client, db, tmp_path, monkeypatch) -> None:
        """本檔的核心：**唯一**一條從下載端點走到 KPI 端點的測試。

        前後各查一次 KPI，驗的是「這次下載造成的差」，而非「事後看起來是 1」——後者用一筆
        造假的 `DmDocRead` 也會過。
        """
        monkeypatch.setattr(settings, "DM_FILE_STORAGE_ROOT", str(tmp_path))  # #160 storage-root 圍籬
        await _user(db, "seam_admin", DM_ADMIN)
        await _user(db, "seam_viewer", DM_VIEWER)
        doc_id = "DM-SOP-000801"
        version_id = await _doc_with_real_file(db, tmp_path, doc_id)

        before = await _kpi_row(client, "seam_admin", doc_id)
        assert before["should_see"] == 1 and before["seen"] == 0 and before["rate"] == 0.0

        download = await client.get(_file_url(doc_id, version_id), headers=_headers("seam_viewer"))
        assert download.status_code == 200, download.text
        assert download.content == b"%PDF-1.4 seam"

        after = await _kpi_row(client, "seam_admin", doc_id)
        assert after["seen"] == 1, "下載端點寫了 DM_DOC_READ，KPI 卻沒認到（接縫斷了）"
        assert after["unseen"] == 0
        assert after["rate"] == 1.0

    async def test_同一人重複下載只算一次(self, client, db, tmp_path, monkeypatch) -> None:
        """去重來自 `UQ_DM_DOC_READ_DOC_VER_USER`（`on_conflict_do_nothing`）。

        這是「已看數字不動」四個設計性原因之首，最容易被當成 bug 而「修」掉。
        """
        monkeypatch.setattr(settings, "DM_FILE_STORAGE_ROOT", str(tmp_path))
        await _user(db, "dedup_admin", DM_ADMIN)
        await _user(db, "dedup_viewer", DM_VIEWER)
        doc_id = "DM-SOP-000802"
        version_id = await _doc_with_real_file(db, tmp_path, doc_id)

        for _ in range(3):
            resp = await client.get(_file_url(doc_id, version_id), headers=_headers("dedup_viewer"))
            assert resp.status_code == 200, resp.text

        assert await _read_rows(db, doc_id) == 1, "唯一約束應讓重複下載 no-op"
        assert (await _kpi_row(client, "dedup_admin", doc_id))["seen"] == 1

    async def test_預覽不計入已看(self, client, db, tmp_path, monkeypatch) -> None:
        """`disposition=preview` 走的是不寫 `DM_DOC_READ` 的分支（`detail/service.py`）。

        使用者把 PDF 在瀏覽器裡讀完了，KPI 仍是未看——這是刻意的，不是漏寫。
        """
        monkeypatch.setattr(settings, "DM_FILE_STORAGE_ROOT", str(tmp_path))
        await _user(db, "prev_admin", DM_ADMIN)
        await _user(db, "prev_viewer", DM_VIEWER)
        doc_id = "DM-SOP-000803"
        version_id = await _doc_with_real_file(db, tmp_path, doc_id)

        resp = await client.get(_file_url(doc_id, version_id, disposition="preview"), headers=_headers("prev_viewer"))
        assert resp.status_code == 200, resp.text
        assert "inline" in resp.headers.get("content-disposition", "")

        assert await _read_rows(db, doc_id) == 0
        row = await _kpi_row(client, "prev_admin", doc_id)
        assert row["seen"] == 0 and row["should_see"] == 1

    async def test_管理者自己下載不計入已看(self, client, db, tmp_path, monkeypatch) -> None:
        """母體是兩層的：`DM_DOC_READ` 照樣寫，但 KPI 只在 `DM_VIEWER` 母體內取交集。

        沒有 `DM_VIEWER` 的管理者下載自己的文件，`seen` 不動——現場最常被回報成「KPI 壞掉」的一種。
        `reads_current` 會撈到這個人，`_compute` 的 `members & readers` 才把他濾掉。
        """
        monkeypatch.setattr(settings, "DM_FILE_STORAGE_ROOT", str(tmp_path))
        await _user(db, "only_admin", DM_ADMIN)  # 刻意不給 DM_VIEWER
        await _user(db, "bystander", DM_VIEWER)  # 撐出應看母體，否則 rate 為 None
        doc_id = "DM-SOP-000804"
        version_id = await _doc_with_real_file(db, tmp_path, doc_id)

        resp = await client.get(_file_url(doc_id, version_id), headers=_headers("only_admin"))
        assert resp.status_code == 200, resp.text

        assert await _read_rows(db, doc_id) == 1, "下載照樣寫閱讀紀錄（差別只在算不算進 KPI）"
        row = await _kpi_row(client, "only_admin", doc_id)
        assert row["should_see"] == 1 and row["seen"] == 0, "非閱覽者的下載不得計入已看"

    async def test_只有被授權的閱覽者算進母體(self, client, db, tmp_path, monkeypatch) -> None:
        """文件掛特定 AUDIENCE 標籤時，未獲該標籤的閱覽者**連下載都拿不到**（404），而非下載了不計。

        與上一條互補，且兩者的把關**位置不同**：

        | 情境 | 擋在哪 | 結果 |
        |---|---|---|
        | 管理者無 `DM_VIEWER`（上一條）| 不擋，KPI 算式的 `members & readers` 濾掉 | 200 下載、寫紀錄、`seen` 不動 |
        | 閱覽者未獲該 AUDIENCE 標籤（本條）| `get_document_meta` 的存取控制先擋 | **404**、不寫紀錄 |

        所以 KPI 母體外的人不會污染 `DM_DOC_READ` 是**兩層**保障：存取控制先擋一次，算式再濾一次。
        分開驗是因為壞掉時症狀相同（`seen` 不動）而原因不同。
        """
        monkeypatch.setattr(settings, "DM_FILE_STORAGE_ROOT", str(tmp_path))
        await _user(db, "aud_admin", DM_ADMIN)
        await _user(db, "aud_in", DM_VIEWER)
        await _user(db, "aud_out", DM_VIEWER)
        doc_id = "DM-SOP-000805"
        tag_name = "護理師"
        tag_id = await _audience_tag_id(db, tag_name)
        assert tag_id is not None, f"AUDIENCE 標籤「{tag_name}」應由 DM seed 種入"

        path = tmp_path / f"{doc_id}.pdf"
        path.write_bytes(b"%PDF-1.4 seam")
        doc = DmDocument(
            doc_id=doc_id,
            doc_name="限定文件",
            category_code="SOP",
            status="PUBLISHED",
            created_user="author",
            created_date=utcnow(),
        )
        db.add(doc)
        await db.flush()
        db.add(DmDocTag(doc_id=doc_id, tag_id=tag_id, created_user="seed", created_date=utcnow()))
        db.add(DmUserTag(user_id="aud_in", tag_id=tag_id, created_user="seed", created_date=utcnow()))
        version = DmDocVersion(
            doc_id=doc_id,
            version_no="1.0",
            change_summary="摘要",
            file_name="1.0.pdf",
            file_path=str(path),
            file_size=path.stat().st_size,
            file_mime="application/pdf",
            status="PUBLISHED",
            published_date=utcnow(),
            created_user="author",
            created_date=utcnow(),
        )
        db.add(version)
        await db.flush()
        doc.current_version_id = version.version_id
        await db.flush()

        before = await _kpi_row(client, "aud_admin", doc_id)
        assert before["should_see"] == 1, "只有掛該標籤的閱覽者進母體"
        assert before["seen"] == 0

        in_ = await client.get(_file_url(doc_id, version.version_id), headers=_headers("aud_in"))
        assert in_.status_code == 200, in_.text
        after = await _kpi_row(client, "aud_admin", doc_id)
        assert after["seen"] == 1 and after["rate"] == 1.0

        # 被擋下的呼叫放最後：失敗請求會回滾本測試的前置資料，其後不可再斷言 DB 狀態
        # （見 `.claude/rules/sti-testing.md`；`_read_rows` / `_kpi_row` 在這行之後都不可信）。
        out = await client.get(_file_url(doc_id, version.version_id), headers=_headers("aud_out"))
        assert out.status_code == 404, "未獲該標籤的閱覽者不該看得到這份文件，連下載入口都沒有"

    async def test_下載舊版後發新版已看歸零(self, client, db, tmp_path, monkeypatch) -> None:
        """`reads_current` 是 join `current_version_id`，不是 join `doc_id`。

        既有 KPI 測試以造假的 `DmDocRead` 驗過「發新版重置」，但那筆列的 `version_id` 是測試自己
        指定的。這裡驗的是**下載端點寫進去的 `version_id` 確實是當下的目前版**——若下載端寫錯版本
        （例如寫成 `doc.current_version_id` 以外的值），既有測試不會紅，KPI 卻會永遠算不到人。
        """
        monkeypatch.setattr(settings, "DM_FILE_STORAGE_ROOT", str(tmp_path))
        await _user(db, "ver_admin", DM_ADMIN)
        await _user(db, "ver_viewer", DM_VIEWER)
        doc_id = "DM-SOP-000806"
        v1 = await _doc_with_real_file(db, tmp_path, doc_id)

        resp = await client.get(_file_url(doc_id, v1), headers=_headers("ver_viewer"))
        assert resp.status_code == 200, resp.text
        assert (await _kpi_row(client, "ver_admin", doc_id))["seen"] == 1

        await _doc_with_real_file(db, tmp_path, doc_id, version_no="2.0")  # 發新版 → current 前進

        after = await _kpi_row(client, "ver_admin", doc_id)
        assert after["seen"] == 0, "新版尚未有人下載，已看應歸零"
        assert after["current_version_no"] == "2.0"
        assert await _read_rows(db, doc_id) == 1, "舊版的閱讀紀錄留著（append-only），只是不計入目前版"
