"""多裝置同時編輯：後送出者被擋，且**先送出者的變更存活**（ET-14 / #341 T118 / AC 3）。

## 既有六條樂觀鎖測試少了哪一半

`ET_LOCK_001` 在既有測試裡出現六次（`course_crud` / `item_crud` / `material` / `quiz` /
`chapter_order` / `course_close_reopen`），**全部使用捏造的版本號**（`99`、`999`、`version + 99`）：

```python
r = await client.put(f"{_URL}/{cid}", json={"course_name": "改名", "version": 999}, ...)
assert r.json()["error_code"] == "ET_LOCK_001"
```

它們驗的是「**版本不符 → 409**」，而那只是樂觀鎖的一半。另一半是「**先送出者寫進去的東西
沒有被後送出者蓋掉**」——也就是 lost update 的可觀測定義，而那需要一次**成功的**寫入當作
對照，六條裡沒有任何一條有。

真實情境是兩個裝置**都載入了同一版**，不是有人拿著一個從未存在過的版本號。差別在於：

- 捏造版本：`UPDATE ... WHERE version = 999` 匹配 0 列 → 409。沒有任何資料被寫入過
- 真實情境：A 已經成功寫入（`version` 已 1 → 2），B 拿著 1 再寫。此時若守衛失效，
  B 會**覆蓋掉 A 的內容**且雙方都看到成功

## 真並發不在本檔的能力範圍內（明確記錄）

要驗「同一毫秒兩個請求」需要第二條 DB 連線，而整合測試的資料活在一個**未提交**的交易裡，
另一條連線看不到（同 ET-16 的 `start_scheduler` 限制，見該 issue 的說明）。

不過本專案的樂觀鎖**守在 SQL 上**而非應用層：

```python
update(EtCourse).where(..., EtCourse.version == version).values(version=EtCourse.version + 1)
ensure_version_matched(rowcount=rowcount, entity="ET_COURSE")
```

`WHERE version = :v` 由 DB 原子判定、以 `rowcount` 回報，故不存在「讀出來比對再寫回去」
那種 lost-update 窗口。本檔驗的是**這個保證在各條寫入路徑上都成立**，那是與並發時序無關
的性質——真正需要兩條連線才驗得到的，只剩「DB 本身的原子性」，而那不是本專案的程式碼。
"""

import os

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dm.catalog.models import DmCategory  # noqa: F401  # 使 FK 目標表進入 metadata
from app.dm.document.file_paths import storage_root
from app.dm.document.models import DmDocument, DmDocVersion
from app.dp.users.models import DpUser
from app.et.common.dm_client import TRAINING_CATEGORY
from app.et.constants import ITEM_MATERIAL, ROLE_TEACHER
from app.et.course.models import EtChapter, EtCourse
from app.et.material.models import EtMaterial, EtMaterialDoc
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _teacher(db, user_id: str) -> str:
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@edms.local",
            pwd_hash=hash_password("Abcd1234"),
            user_name=f"教師{user_id}",
            status="ACTIVE",
            login_fail_count=0,
            pwd_changed_date=now,
            must_change_pwd=False,
            created_user="admin01",
            created_date=now,
        )
    )
    db.add(
        EtUserRole(
            user_id=user_id, role=ROLE_TEACHER, is_active=True, created_user="SYSTEM", created_date=now, deleted=0
        )
    )
    await db.flush()
    return user_id


async def _dm_doc(db, doc_id: str) -> None:
    """建一份可被教材引用的 DM 訓練文件（含發布版）。"""
    now = utcnow()
    db.add(
        DmDocument(
            doc_id=doc_id,
            doc_name=f"文件{doc_id}",
            category_code=TRAINING_CATEGORY,
            func_code=None,
            current_version_id=None,
            status="PUBLISHED",
            created_user="ed",
            created_date=now,
        )
    )
    await db.flush()
    version = DmDocVersion(
        doc_id=doc_id,
        version_no="v1.0",
        change_summary="摘要",
        file_name="a.pdf",
        file_path=os.path.join(storage_root(), doc_id, "v1.0.pdf"),
        file_size=100,
        file_mime="application/pdf",
        status="PUBLISHED",
        approver_user_id="appr",
        published_date=now,
        created_user="ed",
        created_date=now,
    )
    db.add(version)
    await db.flush()
    doc = await db.get(DmDocument, doc_id)
    doc.current_version_id = version.version_id
    await db.flush()


async def _course(client, uid: str, name: str = "原始名稱") -> int:
    r = await client.post(_COURSES, json={"course_name": name}, headers=_bearer(uid))
    assert r.status_code == 201, r.text
    return r.json()["course_id"]


class TestCourseEdit:
    """`PUT /courses/{id}`——最常見的編輯路徑。"""

    async def test_兩裝置同載一版時後送出者被擋且前者變更存活(self, client, db) -> None:
        """AC 3 的核心。與既有 `test_版本不符回_409` 的差別在於**有一次成功的寫入**。

        少了那次成功寫入，就只驗到「不存在的版本會被擋」，而 lost update 的定義是
        「**存在的舊版本**被用來覆蓋新內容」——兩者是不同的事。
        """
        uid = await _teacher(db, "t_cc01")
        course_id = await _course(client, uid)
        loaded_version = 0  # 兩個裝置都在這一版載入畫面

        first = await client.put(
            f"{_COURSES}/{course_id}",
            json={"course_name": "A 裝置改的名稱", "version": loaded_version},
            headers=_bearer(uid),
        )
        assert first.status_code == 204, first.text

        second = await client.put(
            f"{_COURSES}/{course_id}",
            json={"course_name": "B 裝置改的名稱", "version": loaded_version},
            headers=_bearer(uid),
        )
        assert second.status_code == 409, second.text
        assert second.json()["error_code"] == "ET_LOCK_001"

        row = await db.scalar(select(EtCourse).where(EtCourse.course_id == course_id))
        await db.refresh(row)
        assert row.course_name == "A 裝置改的名稱", "後送出者的內容覆蓋了先送出者——這就是 lost update"
        assert row.version == loaded_version + 1, "被擋下的那次不得推進版本"

    async def test_重新載入後以新版本可正常存檔(self, client, db) -> None:
        """被擋下之後 UI 的唯一出路：重載取新版本再存。

        若 409 的同時版本也被推進（例如守衛寫在 `UPDATE` 之後），使用者重載拿到的版本
        會立刻又是舊的——畫面會變成「永遠存不進去」，而錯誤訊息只說「請重新載入」。
        """
        uid = await _teacher(db, "t_cc02")
        course_id = await _course(client, uid)

        await client.put(f"{_COURSES}/{course_id}", json={"course_name": "先寫入", "version": 0}, headers=_bearer(uid))
        blocked = await client.put(
            f"{_COURSES}/{course_id}", json={"course_name": "被擋", "version": 0}, headers=_bearer(uid)
        )
        assert blocked.status_code == 409

        detail = await client.get(f"{_COURSES}/{course_id}", headers=_bearer(uid))
        assert detail.status_code == 200, detail.text
        retried = await client.put(
            f"{_COURSES}/{course_id}",
            json={"course_name": "重載後再寫", "version": detail.json()["version"]},
            headers=_bearer(uid),
        )
        assert retried.status_code == 204, f"重載後應存得進去，實得 {retried.text}"

        row = await db.scalar(select(EtCourse).where(EtCourse.course_id == course_id))
        await db.refresh(row)
        assert row.course_name == "重載後再寫"


class TestChapterReorder:
    """章節重排以**課程層**版本保護——並發面比單筆編輯更寬，因為它一次動整批順序。"""

    async def test_重排與改名互相擋且先送出者存活(self, client, db) -> None:
        """兩個裝置一個在重排、一個在改名，兩者共用課程層版本。

        這是既有測試補不到的形狀：`test_et_chapter_order.py::test_重排以課程層版本保護`
        用的是 `version=999`，驗不到「改名成功之後重排仍拿舊版本」這條真實路徑。
        """
        uid = await _teacher(db, "t_cc03")
        course_id = await _course(client, uid)
        ch_a = await client.post(
            f"{_COURSES}/{course_id}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(uid)
        )
        ch_b = await client.post(
            f"{_COURSES}/{course_id}/chapters", json={"chapter_name": "第二章"}, headers=_bearer(uid)
        )
        assert ch_a.status_code == 201 and ch_b.status_code == 201
        ids = [ch_a.json()["chapter_id"], ch_b.json()["chapter_id"]]

        detail = await client.get(f"{_COURSES}/{course_id}", headers=_bearer(uid))
        shared_version = detail.json()["version"]

        renamed = await client.put(
            f"{_COURSES}/{course_id}",
            json={"course_name": "A 裝置改的名稱", "version": shared_version},
            headers=_bearer(uid),
        )
        assert renamed.status_code == 204, renamed.text

        reordered = await client.put(
            f"{_COURSES}/{course_id}/chapters/order",
            json={"chapter_ids": list(reversed(ids)), "version": shared_version},
            headers=_bearer(uid),
        )
        assert reordered.status_code == 409, reordered.text
        assert reordered.json()["error_code"] == "ET_LOCK_001"

        rows = (
            (
                await db.execute(
                    select(EtChapter)
                    .where(EtChapter.course_id == course_id, EtChapter.deleted == 0)
                    .order_by(EtChapter.sort_order)
                )
            )
            .scalars()
            .all()
        )
        assert [c.chapter_id for c in rows] == ids, "被擋下的重排不得留下部分寫入"
        course = await db.scalar(select(EtCourse).where(EtCourse.course_id == course_id))
        await db.refresh(course)
        assert course.course_name == "A 裝置改的名稱"


class TestMaterialEdit:
    """教材是**全量覆寫**契約，被擋下時的部分寫入風險最高。"""

    async def test_教材被擋時不留下部分寫入(self, client, db) -> None:
        """全量覆寫（未列出的既有引用 / 影片會被刪）意味著一次請求裡有多筆刪改。
        被擋下時**一筆都不可以落地**。

        ## 守住這件事的是交易邊界，不是步驟順序（實測更正）

        撰寫時原本以為關鍵在 `material/service.update` 的順序（「樂觀鎖更新本體 → 套用
        文件 / 影片差異」）。**實測推翻**：把守衛搬到差異之後，本檔 4 條與既有
        `test_et_material.py` 29 條**全部仍然綠**——因為 `ensure_version_matched` 拋的是
        `AppError`，`get_db` 會把整筆請求交易回滾，刪除從來沒有機會落地。

        所以本條真正釘住的是「**被拒絕的編輯沒有任何部分逃出交易**」。這不是空話：同一個
        codebase 裡就有刻意繞過回滾的先例——`dp/user/service._fail` 在拋錯**之前**先
        `commit()`（為了讓登入失敗計數不被回滾抹除）。以同型的 `commit()` 做變異，本條
        會紅——不過既有 29 條裡也有 1 條會紅，所以這不是獨有的覆蓋，差別在於本條**明說**
        它在驗這件事：既有那條紅是因為 commit 破壞了它自己的前置狀態，訊息不會指向病因。

        B 的請求必須真的有東西可刪，否則差異是 no-op、測不到任何東西：A 先掛上一份 DM
        文件，B 再以**舊版本**送出空的 `doc_ids`（＝要求清空）。
        """
        uid = await _teacher(db, "t_cc04")
        course_id = await _course(client, uid)
        chapter = await client.post(
            f"{_COURSES}/{course_id}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(uid)
        )
        item = await client.post(
            f"/api/et/chapters/{chapter.json()['chapter_id']}/items",
            json={"item_type": ITEM_MATERIAL, "title": "教材"},
            headers=_bearer(uid),
        )
        material_id = item.json()["material_id"]
        doc_id = "DM-TRAINING-000950"
        await _dm_doc(db, doc_id)

        def _body(description: str, version: int, doc_ids: list[str]) -> dict:
            return {
                "material_name": "教材",
                "description_html": description,
                "doc_ids": doc_ids,
                "video_ids": [],
                "version": version,
            }

        first = await client.put(
            f"/api/et/materials/{material_id}",
            json=_body("<p>A 裝置寫的說明</p>", 0, [doc_id]),
            headers=_bearer(uid),
        )
        assert first.status_code == 204, first.text

        # B 拿著舊版本，且要求把文件清空——這正是「被擋下時會不會先刪掉東西」的觸發條件
        second = await client.put(
            f"/api/et/materials/{material_id}",
            json=_body("<p>B 裝置寫的說明</p>", 0, []),
            headers=_bearer(uid),
        )
        assert second.status_code == 409, second.text
        assert second.json()["error_code"] == "ET_LOCK_001"

        row = await db.scalar(select(EtMaterial).where(EtMaterial.material_id == material_id))
        await db.refresh(row)
        assert "A 裝置寫的說明" in (row.description_html or ""), "被擋下的全量覆寫覆蓋了本體"

        docs = (
            (
                await db.execute(
                    select(EtMaterialDoc).where(EtMaterialDoc.material_id == material_id, EtMaterialDoc.deleted == 0)
                )
            )
            .scalars()
            .all()
        )
        assert [d.doc_id for d in docs] == [doc_id], "被擋下的請求把文件引用刪掉了——版本守衛跑在差異之後"
