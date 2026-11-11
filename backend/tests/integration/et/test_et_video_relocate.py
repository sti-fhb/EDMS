"""既有影片目錄遷移腳本（#871，`python -m app.et.material.relocate_videos`）。

#871 之前暫存上傳的影片落在 `abs(暫存 id)/`，與所屬 `MATERIAL_ID` 不同；腳本把它們掛進
`{MATERIAL_ID}/` 並改寫 `FILE_PATH`，全部完成後寫入標記檔使播放端歸屬圍籬生效。

🔴 **儲存根目錄一律改指 `tmp_path`**（理由同 `test_et_video_ownership.py`）。

⚠️ 測試 DB 在同一個 worker 內跨檔共用，其他測試留下的影片列（如 `dummy/not-a-real-file.mp4`）
也會被腳本看到。驗「全部完成才寫標記檔」的測試以 `scoped` 把腳本的視野限縮到本檔建的列——
否則結果取決於前面跑過哪些測試；而**不限縮的那幾條只斷言本檔的列**，不碰別人的。
"""

import json
import os
import tempfile
import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.utils import utcnow
from app.et.course.models import EtCourseContentStage
from app.et.course.stage_rules import ENTITY_MATERIAL_VIDEO
from app.et.material import relocate_videos, storage
from app.et.material.models import EtMaterialVideo
from tests.integration.et.test_et_staged_write_paths import _bearer, _course_with_content, _publish, _user

pytestmark = pytest.mark.integration

_CONTENT = b"legacy-video"


def _posix_file_modes_supported() -> bool:
    """此平台能否設定並讀回 POSIX 的擁有者／群組／其他權限位元（#937）。

    以實際設一次 0600 再讀回判定，而非看平台名稱。Windows 的 `chmod` 只控制唯讀旗標，
    `stat` 一律回報 0666 或 0444，紀錄檔權限的安全性質在該平台上本來就不存在。
    """
    with tempfile.TemporaryDirectory() as d:
        probe = os.path.join(d, "probe")
        open(probe, "w").close()
        os.chmod(probe, 0o600)
        return os.stat(probe).st_mode & 0o777 == 0o600


#: 紀錄檔權限相關測試：遷移腳本只在正式機（Linux）執行，GitHub CI 照常驗證這兩條。
_requires_posix_file_modes = pytest.mark.skipif(
    not _posix_file_modes_supported(),
    reason="此平台沒有 POSIX 檔案權限位元（Windows），0600 無從設定與驗證；正式機 Linux 與 GitHub CI 照常執行",
)


@pytest.fixture
def root(tmp_path, monkeypatch) -> str:
    monkeypatch.setattr(settings, "ET_VIDEO_STORAGE_ROOT", str(tmp_path))
    return os.path.realpath(str(tmp_path))


@pytest.fixture
def scoped(monkeypatch):
    """把腳本的視野限縮到指定 `VIDEO_ID`（見模組 docstring）。"""
    ids: set[int] = set()
    original = relocate_videos.load_rows

    async def only_mine(db):
        return [r for r in await original(db) if r.video_id in ids]

    monkeypatch.setattr(relocate_videos, "load_rows", only_mine)
    return ids


async def _legacy_video(client, db, uid: str, root: str, *, with_file: bool = True, deleted: int = 0) -> dict:
    """一門已發布課程、教材下一支落在**他號目錄**的影片（模擬 #871 之前暫存上傳後發布的列）。"""
    ids = await _course_with_content(client, db, uid)
    await _publish(client, db, uid, ids["course_id"])
    old = f"{ids['material_id'] + 7_000_000}/{uuid.uuid4().hex}.mp4"
    if with_file:
        os.makedirs(os.path.join(root, old.split("/")[0]), exist_ok=True)
        with open(os.path.join(root, old), "wb") as f:
            f.write(_CONTENT)
    video = EtMaterialVideo(
        material_id=ids["material_id"],
        file_path=old,
        file_name="舊影片.mp4",
        duration_sec=3,
        file_size_bytes=len(_CONTENT),
        sort_order=9,
        created_user=uid,
        created_date=utcnow(),
        deleted=deleted,
    )
    db.add(video)
    await db.commit()
    return ids | {"video_id": video.video_id, "old": old, "new": f"{ids['material_id']}/{old.split('/')[1]}"}


async def _path_of(db, video_id: int) -> str:
    db.expire_all()
    return await db.scalar(select(EtMaterialVideo.file_path).where(EtMaterialVideo.video_id == video_id))


async def _play(client, uid: str, video_id: int):
    ticket = await client.post(f"/api/et/videos/{video_id}/ticket", headers=_bearer(uid))
    assert ticket.status_code == 200, ticket.text
    return await client.get(f"/api/et/videos/{video_id}/file", params={"t": ticket.json()["ticket"]})


def _log_entries(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class TestDryRun:
    async def test_只列出不動手(self, client, db, root, capsys) -> None:
        uid = await _user(db, "ZT_RL1")
        v = await _legacy_video(client, db, uid, root)
        before = sorted(os.listdir(root))

        code = await relocate_videos.run(db, apply=False)

        assert code == 0
        assert v["old"] in capsys.readouterr().out
        assert await _path_of(db, v["video_id"]) == v["old"]
        assert sorted(os.listdir(root)) == before
        assert not storage.ownership_fence_enforced(root)


class TestApply:
    async def test_掛進正式目錄並改寫_FILE_PATH_全部完成才使圍籬生效(self, client, db, root, scoped) -> None:
        uid = await _user(db, "ZT_RL2")
        v = await _legacy_video(client, db, uid, root)
        scoped.add(v["video_id"])
        log = os.path.join(root, "relocate.jsonl")

        code = await relocate_videos.run(db, apply=True, log_path=log)

        assert code == 0
        assert await _path_of(db, v["video_id"]) == v["new"]
        assert os.path.samefile(os.path.join(root, v["new"]), os.path.join(root, v["old"])), "原名字留著供回復"
        assert storage.ownership_fence_enforced(root)
        (entry,) = _log_entries(log)
        assert entry["video_id"] == v["video_id"] and entry["old"] == v["old"] and entry["new"] == v["new"]

    async def test_遷移後仍可播放(self, client, db, root, scoped) -> None:
        """驗收條件 2：遷移後全部影片仍可播放（圍籬已生效的前提下）。"""
        uid = await _user(db, "ZT_RL3")
        v = await _legacy_video(client, db, uid, root)
        scoped.add(v["video_id"])
        assert (await _play(client, uid, v["video_id"])).status_code == 200, "前置：遷移前可播（放行模式）"

        await relocate_videos.run(db, apply=True, log_path=os.path.join(root, "r.jsonl"))

        assert storage.ownership_fence_enforced(root)
        r = await _play(client, uid, v["video_id"])
        assert r.status_code == 200, r.text
        assert r.content == _CONTENT

    async def test_重跑為冪等(self, client, db, root, scoped) -> None:
        uid = await _user(db, "ZT_RL4")
        v = await _legacy_video(client, db, uid, root)
        scoped.add(v["video_id"])
        log = os.path.join(root, "r.jsonl")
        await relocate_videos.run(db, apply=True, log_path=log)

        code = await relocate_videos.run(db, apply=True, log_path=log)

        assert code == 0
        assert await _path_of(db, v["video_id"]) == v["new"]
        assert len(_log_entries(log)) == 1, "第二輪沒有待遷移的列，不應再記"

    async def test_中途失敗可重跑接續(self, client, db, root, scoped, monkeypatch) -> None:
        uid = await _user(db, "ZT_RL5")
        first = await _legacy_video(client, db, uid, root)
        second = await _legacy_video(client, db, uid, root)
        scoped.update({first["video_id"], second["video_id"]})
        log = os.path.join(root, "r.jsonl")
        real_link = storage.link_into_material
        calls = {"n": 0}

        def flaky(file_path: str, material_id: int) -> str:
            calls["n"] += 1
            if calls["n"] == 2:
                raise PermissionError("模擬第二支失敗")
            return real_link(file_path, material_id)

        monkeypatch.setattr(storage, "link_into_material", flaky)
        code = await relocate_videos.run(db, apply=True, log_path=log)

        assert code == 1
        assert not storage.ownership_fence_enforced(root), "還有待遷移的列，圍籬不得生效"
        done = [v for v in (first, second) if await _path_of(db, v["video_id"]) == v["new"]]
        assert len(done) == 1, "失敗的那支不得影響已完成的那支"

        monkeypatch.setattr(storage, "link_into_material", real_link)
        assert await relocate_videos.run(db, apply=True, log_path=log) == 0
        assert await _path_of(db, first["video_id"]) == first["new"]
        assert await _path_of(db, second["video_id"]) == second["new"]
        assert storage.ownership_fence_enforced(root)

    async def test_已軟刪的影片一併遷移(self, client, db, root, scoped) -> None:
        """軟刪可回復——回復後要能播。"""
        uid = await _user(db, "ZT_RL6")
        v = await _legacy_video(client, db, uid, root, deleted=1)
        scoped.add(v["video_id"])

        await relocate_videos.run(db, apply=True, log_path=os.path.join(root, "r.jsonl"))

        assert await _path_of(db, v["video_id"]) == v["new"]

    async def test_未限縮時只動到待遷移的列(self, client, db, root) -> None:
        """不限縮視野、對整個測試 DB 跑：本檔的列照樣被處理（其他列各自的結果不斷言）。"""
        uid = await _user(db, "ZT_RL7")
        v = await _legacy_video(client, db, uid, root)

        await relocate_videos.run(db, apply=True, log_path=os.path.join(root, "r.jsonl"))

        assert await _path_of(db, v["video_id"]) == v["new"]


class TestMissingFile:
    async def test_檔案不存在者略過且圍籬不生效(self, client, db, root, scoped) -> None:
        """影片目錄沒掛上時所有來源都「不存在」——若照樣改寫，掛回來之後全部播不出來。"""
        uid = await _user(db, "ZT_RL8")
        v = await _legacy_video(client, db, uid, root, with_file=False)
        scoped.add(v["video_id"])

        code = await relocate_videos.run(db, apply=True, log_path=os.path.join(root, "r.jsonl"))

        assert code == 1
        assert await _path_of(db, v["video_id"]) == v["old"]
        assert not storage.ownership_fence_enforced(root)

    async def test_明示接受後改寫路徑並使圍籬生效(self, client, db, root, scoped) -> None:
        uid = await _user(db, "ZT_RL9")
        v = await _legacy_video(client, db, uid, root, with_file=False)
        scoped.add(v["video_id"])
        log = os.path.join(root, "r.jsonl")

        code = await relocate_videos.run(db, apply=True, accept_missing=True, log_path=log)

        assert code == 0
        assert await _path_of(db, v["video_id"]) == v["new"]
        assert storage.ownership_fence_enforced(root)
        assert _log_entries(log)[0]["source_missing"] is True


class TestRevert:
    async def test_依紀錄回復路徑並撤銷圍籬(self, client, db, root, scoped) -> None:
        uid = await _user(db, "ZT_RL10")
        v = await _legacy_video(client, db, uid, root)
        scoped.add(v["video_id"])
        log = os.path.join(root, "r.jsonl")
        await relocate_videos.run(db, apply=True, log_path=log)
        # 原名字已被孤兒清理收掉——回復時要從新名字掛回去
        os.remove(os.path.join(root, v["old"]))

        code = await relocate_videos.revert(db, log_path=log)

        assert code == 0
        assert await _path_of(db, v["video_id"]) == v["old"]
        with open(os.path.join(root, v["old"]), "rb") as f:
            assert f.read() == _CONTENT
        assert not storage.ownership_fence_enforced(root)

    async def test_紀錄之後又被改過的列不回復(self, client, db, root, scoped) -> None:
        uid = await _user(db, "ZT_RL11")
        v = await _legacy_video(client, db, uid, root)
        scoped.add(v["video_id"])
        log = os.path.join(root, "r.jsonl")
        await relocate_videos.run(db, apply=True, log_path=log)
        changed = f"{v['material_id']}/{uuid.uuid4().hex}.mp4"
        row = await db.scalar(select(EtMaterialVideo).where(EtMaterialVideo.video_id == v["video_id"]))
        row.file_path = changed
        await db.commit()

        code = await relocate_videos.revert(db, log_path=log)

        assert code == 1
        assert await _path_of(db, v["video_id"]) == changed


class TestRevertEdgeCases:
    async def test_舊名字仍在時直接改回(self, client, db, root, scoped) -> None:
        uid = await _user(db, "ZT_RL12")
        v = await _legacy_video(client, db, uid, root)
        scoped.add(v["video_id"])
        log = os.path.join(root, "r.jsonl")
        await relocate_videos.run(db, apply=True, log_path=log)

        assert await relocate_videos.revert(db, log_path=log) == 0

        assert await _path_of(db, v["video_id"]) == v["old"]
        assert (await _play(client, uid, v["video_id"])).status_code == 200

    async def test_檔案不存在而接受改寫的列_回復時只改回路徑(self, client, db, root, scoped) -> None:
        uid = await _user(db, "ZT_RL13")
        v = await _legacy_video(client, db, uid, root, with_file=False)
        scoped.add(v["video_id"])
        log = os.path.join(root, "r.jsonl")
        await relocate_videos.run(db, apply=True, accept_missing=True, log_path=log)

        assert await relocate_videos.revert(db, log_path=log) == 0

        assert await _path_of(db, v["video_id"]) == v["old"]
        assert not os.path.exists(os.path.join(root, v["old"]))

    async def test_紀錄最後一行截斷時略過該行_其餘照常回復(self, client, db, root, scoped) -> None:
        """執行中被中斷時，紀錄的最後一行可能只寫了一半。"""
        uid = await _user(db, "ZT_RL14")
        v = await _legacy_video(client, db, uid, root)
        scoped.add(v["video_id"])
        log = os.path.join(root, "r.jsonl")
        await relocate_videos.run(db, apply=True, log_path=log)
        with open(log, "a", encoding="utf-8") as f:
            f.write('{"video_id": 1, "old": "x')

        await relocate_videos.revert(db, log_path=log)

        assert await _path_of(db, v["video_id"]) == v["old"]


class TestDbOnlyRestore:
    async def test_只還原_DB_後重跑_舊名字已被清掉者改指正式目錄裡已有的檔(self, client, db, root, scoped) -> None:
        """DB 與影片目錄的備份是兩條流程；只還原 DB 時，舊名字可能早已被孤兒清理收掉。"""
        uid = await _user(db, "ZT_RL15")
        v = await _legacy_video(client, db, uid, root)
        scoped.add(v["video_id"])
        await relocate_videos.run(db, apply=True, log_path=os.path.join(root, "r.jsonl"))
        os.remove(os.path.join(root, v["old"]))  # 孤兒清理收掉舊名字
        row = await db.scalar(select(EtMaterialVideo).where(EtMaterialVideo.video_id == v["video_id"]))
        row.file_path = v["old"]  # DB 還原到遷移前
        await db.commit()

        code = await relocate_videos.run(db, apply=True, log_path=os.path.join(root, "r2.jsonl"))

        assert code == 0
        assert await _path_of(db, v["video_id"]) == v["new"]
        r = await _play(client, uid, v["video_id"])
        assert r.status_code == 200 and r.content == _CONTENT


class TestWriteAheadLog:
    async def test_改_DB_之前紀錄已寫入(self, client, db, root, scoped, monkeypatch) -> None:
        """紀錄先寫：改寫 DB 的那一刻，紀錄裡必須已經有這一列——之後被中斷也回復得到。"""
        uid = await _user(db, "ZT_RL16")
        v = await _legacy_video(client, db, uid, root)
        scoped.add(v["video_id"])
        log = os.path.join(root, "r.jsonl")
        seen: list[int] = []
        real_rewrite = relocate_videos._rewrite

        async def spy(db_, video_id, **kw):
            seen.extend(e["video_id"] for e in _log_entries(log))
            return await real_rewrite(db_, video_id, **kw)

        monkeypatch.setattr(relocate_videos, "_rewrite", spy)
        await relocate_videos.run(db, apply=True, log_path=log)

        assert v["video_id"] in seen


class TestSecurityHardening:
    """Security review（#871）：錯指的列不自動合法化；搬移紀錄不當成可信輸入。"""

    async def test_同一支檔被不同教材引用者需人工確認(self, client, db, root, scoped) -> None:
        uid = await _user(db, "ZT_RL17")
        v = await _legacy_video(client, db, uid, root)
        other = await _legacy_video(client, db, uid, root)
        # 另一份教材的列錯指到 v 的同一支檔
        row = await db.scalar(select(EtMaterialVideo).where(EtMaterialVideo.video_id == other["video_id"]))
        row.file_path = v["old"]
        await db.commit()
        scoped.update({v["video_id"], other["video_id"]})
        log = os.path.join(root, "r.jsonl")

        code = await relocate_videos.run(db, apply=True, log_path=log)

        assert code == 1
        assert await _path_of(db, v["video_id"]) == v["old"]
        assert await _path_of(db, other["video_id"]) == v["old"]
        assert not storage.ownership_fence_enforced(root)

        assert await relocate_videos.run(db, apply=True, allow_shared=True, log_path=log) == 0
        assert await _path_of(db, v["video_id"]) == v["new"]

    @_requires_posix_file_modes
    async def test_他人可寫的紀錄拒絕回復(self, client, db, root, scoped) -> None:
        uid = await _user(db, "ZT_RL18")
        v = await _legacy_video(client, db, uid, root)
        scoped.add(v["video_id"])
        log = os.path.join(root, "r.jsonl")
        await relocate_videos.run(db, apply=True, log_path=log)
        assert os.stat(log).st_mode & 0o777 == 0o600, "紀錄以 0600 建立"
        os.chmod(log, 0o666)  # noqa: S103 - 測試刻意造出他人可寫的紀錄

        code = await relocate_videos.revert(db, log_path=log)

        assert code == 2
        assert await _path_of(db, v["video_id"]) == v["new"]
        assert storage.ownership_fence_enforced(root), "拒絕回復時不得先撤銷圍籬"

    @pytest.mark.parametrize(
        ("tag", "tamper"),
        [
            ("A", {"old": "../../outside.mp4"}),
            ("B", {"new": "999/whatever.mp4"}),
            ("C", {"material_id": 999}),
            ("D", {"video_id": "1"}),
        ],
    )
    async def test_形狀不合或與_DB_不符的紀錄行不動(self, client, db, root, scoped, tag: str, tamper: dict) -> None:
        uid = await _user(db, f"ZT_RL19{tag}")
        v = await _legacy_video(client, db, uid, root)
        scoped.add(v["video_id"])
        log = os.path.join(root, "r.jsonl")
        await relocate_videos.run(db, apply=True, log_path=log)
        (entry,) = _log_entries(log)
        with open(log, "w", encoding="utf-8") as f:
            f.write(json.dumps(entry | tamper) + "\n")

        code = await relocate_videos.revert(db, log_path=log)

        assert code in (0, 1)
        assert await _path_of(db, v["video_id"]) == v["new"], "被竄改的行不得回復任何東西"
        assert not os.path.exists(os.path.join(root, "..", "outside.mp4"))


class TestStagedSnapshotAfterRelocation:
    """Review H-1（#887）：遷移前開的編輯工作階段，按「更新」不得把遷移後的路徑蓋回舊目錄。"""

    async def test_既有影片的暫存快照帶舊路徑_遷移後按更新_路徑不被蓋回且可播(self, client, db, root, scoped) -> None:
        uid = await _user(db, "ZT_RL20")
        v = await _legacy_video(client, db, uid, root)
        scoped.add(v["video_id"])
        # 遷移前開工：任一內容編輯都會把整棵活表複製進暫存區，影片的 file_path 是舊路徑。
        # 用「教材原樣存一次」開工——不改任何內容，「更新」的發布檢核才不會擋在前置
        mid = v["material_id"]
        detail = (await client.get(f"/api/et/materials/{mid}", headers=_bearer(uid))).json()
        r = await client.put(
            f"/api/et/materials/{mid}",
            json={
                "material_name": detail["material_name"],
                "description_html": detail["description_html"],
                "doc_ids": [d["doc_id"] for d in detail["docs"]],
                "video_ids": [x["video_id"] for x in detail["videos"]],
                "version": detail["version"],
            },
            headers=_bearer(uid),
        )
        assert r.status_code == 204, r.text
        await db.commit()
        snapshot = await db.scalar(
            select(EtCourseContentStage.payload).where(
                EtCourseContentStage.entity_type == ENTITY_MATERIAL_VIDEO,
                EtCourseContentStage.source_id == v["video_id"],
            )
        )
        assert json.loads(snapshot)["file_path"] == v["old"], "前置：快照帶的是舊路徑"

        assert await relocate_videos.run(db, apply=True, log_path=os.path.join(root, "r.jsonl")) == 0
        r = await client.post(f"/api/et/courses/{v['course_id']}/content/apply", headers=_bearer(uid))
        assert r.status_code == 200, r.text
        await db.commit()

        assert await _path_of(db, v["video_id"]) == v["new"], "更新不得把遷移後的路徑蓋回舊目錄"
        r = await _play(client, uid, v["video_id"])
        assert r.status_code == 200 and r.content == _CONTENT


class TestLogFileHandling:
    @_requires_posix_file_modes
    async def test_既有的寬權限紀錄檔會被收緊(self, client, db, root, scoped) -> None:
        uid = await _user(db, "ZT_RL21")
        v = await _legacy_video(client, db, uid, root)
        scoped.add(v["video_id"])
        log = os.path.join(root, "r.jsonl")
        open(log, "w").close()
        os.chmod(log, 0o644)

        await relocate_videos.run(db, apply=True, log_path=log)

        assert os.stat(log).st_mode & 0o777 == 0o600

    async def test_沒有動手任何一筆時不印紀錄路徑(self, client, db, root, scoped) -> None:
        scoped.add(-1)  # 視野限縮到不存在的列：沒有待遷移
        log = os.path.join(root, "never.jsonl")
        lines: list[str] = []

        await relocate_videos.run(db, apply=True, log_path=log, out=lines.append)

        assert not os.path.exists(log)
        assert all(log not in line for line in lines)
