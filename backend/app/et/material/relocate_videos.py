"""既有影片目錄遷移（#871，一次性維運腳本）。

#871 之前，暫存模式新增的教材其影片落在 `abs(暫存 id)/`，發布後 `FILE_PATH` 原樣寫進活表——目錄名
與所屬 `MATERIAL_ID` 不同。本腳本把這些影片掛進 `{MATERIAL_ID}/`（hard link，檔名不變）並改寫
`FILE_PATH`；確認沒有待遷移的列之後寫入 `storage.OWNERSHIP_FENCE_MARKER`，播放端的歸屬圍籬自此
強制生效。

    python -m app.et.material.relocate_videos              # dry-run：只列出將搬移的影片
    python -m app.et.material.relocate_videos --apply      # 執行
    python -m app.et.material.relocate_videos --revert LOG # 依搬移紀錄回復

退出碼：0＝完成（dry-run 一律 0）、1＝仍有待處理的列（圍籬未生效）、2＝執行錯誤。

## 為何不寫在 Alembic migration 裡

migration 的執行環境不保證掛載影片目錄；在沒掛上的環境跑，所有來源都會「不存在」。

## 不停機、可重跑、可回復

| 性質 | 做法 |
|------|------|
| 不停機 | 逐列「先掛新名字、再改 DB」：改 DB 之前舊路徑照常可播，之後新路徑可播；兩個名字指向同一份內容 |
| 可重跑 | 每列各自 commit；`UPDATE … WHERE FILE_PATH = 舊值`。中途失敗重跑時，已完成的列不再出現在待遷移清單 |
| 可回復 | 搬移紀錄（JSON Lines）**先寫後做**；`--revert` 依紀錄改回舊路徑並移除標記檔 |

🔴 **紀錄先寫（write-ahead）**：改 DB 之後才記的話，commit 與寫紀錄之間被中斷（連線斷、kill、磁碟滿），
那一列就「已遷移卻無紀錄」，重跑時又不再是待遷移——`--revert` 永遠回復不到它。先記的代價只是紀錄
可能多出「沒做成」的列，而 `--revert` 以 `WHERE FILE_PATH = 新值` 守門，那些列不會被動到。

舊名字在改寫後成為孤兒、約一天後由孤兒清理收掉；`--revert` 遇到舊名字已不在時從新名字掛回去。

## 同一支檔被不同教材引用的列：預設略過、圍籬不生效

舊式暫存目錄與正式教材共用數字命名空間，單看目錄名分不出「暫存上傳後發布」與「錯指到他份教材的檔」。
後者正是歸屬圍籬要擋的列，所以「同一支檔被兩份以上教材引用」者列為需人工確認；確認屬正常後以
`--allow-shared` 處理。

## 搬移紀錄不是可信輸入

紀錄放在影片目錄（與資料一起備份），對該目錄有寫入權者都改得到。寫入以 0600 建立；`--revert` 只讀
執行者本人所有、他人不可寫的紀錄，逐行驗證形狀，且每列先在 DB 確認狀態才動檔案。

## 來源檔不存在的列：預設略過、圍籬不生效

最可能的成因是**影片目錄沒掛上**——此時照樣改寫 `FILE_PATH`，掛回來之後那些影片全都播不出來。
確認檔案確實已遺失（DB↔磁碟早已不一致）後，以 `--accept-missing` 明示接受：路徑照樣改寫
（那支影片改前改後都是 404），圍籬才能生效。
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal
from app.core.utils import utcnow
from app.et.audit_target import course_audit_payload
from app.et.course.models import EtChapter, EtItem
from app.et.material import storage
from app.et.material.models import EtMaterialVideo
from app.et.material.rules import is_managed_video_path
from app.services import AuditLogService

logger = logging.getLogger(__name__)

_SYSTEM = "SYSTEM"
_MODULE = "ET"
_FUNC_NAME = "ET-COURSE"


@dataclass(frozen=True)
class VideoPathRow:
    """`ET_MATERIAL_VIDEO` 中判定歸屬所需的欄位；`course_id` 供稽核（教材已脫離項目時為 `None`）。"""

    video_id: int
    material_id: int
    file_path: str
    course_id: int | None = None


@dataclass(frozen=True)
class Relocation:
    """一列待遷移的影片。"""

    video_id: int
    material_id: int
    old: str
    new: str
    source_missing: bool
    course_id: int | None = None
    #: 同一支檔另被**其他教材**的列引用——資料異常，不自動遷移（見 `plan`）。
    shared: bool = False


@dataclass(frozen=True)
class Plan:
    """待遷移清單，以及逃出 storage root、無從遷移的列數（那些列在 root 圍籬就已是 404）。"""

    relocations: list[Relocation]
    escaped: int


async def load_rows(db: AsyncSession) -> list[VideoPathRow]:
    """全部影片列——**含已軟刪**：軟刪可回復，回復後要能播。

    `course_id` 經教材所屬項目 → 章節取得（outer join：教材已脫離項目者仍要遷移，只是稽核掛不上課程）。
    """
    stmt = (
        select(EtMaterialVideo.video_id, EtMaterialVideo.material_id, EtMaterialVideo.file_path, EtChapter.course_id)
        .outerjoin(EtItem, EtItem.material_id == EtMaterialVideo.material_id)
        .outerjoin(EtChapter, EtChapter.chapter_id == EtItem.chapter_id)
        .order_by(EtMaterialVideo.video_id)
    )
    # 一份教材恆對一個項目（`stage_apply` 模組 docstring）；萬一有多列，取第一列即可——只影響稽核掛哪門課
    seen: dict[int, VideoPathRow] = {}
    for video_id, material_id, file_path, course_id in (await db.execute(stmt)).all():
        seen.setdefault(video_id, VideoPathRow(video_id, material_id, file_path, course_id))
    return list(seen.values())


def _inode(path: str) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_dev, st.st_ino


def plan(rows: Sequence[VideoPathRow], root: str) -> Plan:
    """挑出檔案不在 `{root}/{MATERIAL_ID}/` 之下的列（判定與播放端圍籬同一套）。

    🔴 **同一支檔被不同教材的列引用者標為 `shared`、不自動遷移。** 舊式暫存目錄（`{暫存 id}/`）與
    正式教材共用數字命名空間，單看目錄名分不出「暫存上傳後發布」與「錯指到他份教材的檔」；後者正是
    歸屬圍籬要擋的列，自動掛過去等於把它合法化。正常資料裡一支檔只屬於一份教材，所以「被兩份以上
    教材引用」就是需要人看的訊號。
    """
    located: list[tuple[VideoPathRow, str]] = []
    escaped = 0
    owners: dict[tuple[int, int], set[int]] = {}
    for row in rows:
        resolved = storage.locate_in_root(row.file_path, root)
        if resolved is None:
            escaped += 1
            continue
        located.append((row, resolved))
        if (key := _inode(resolved)) is not None:
            owners.setdefault(key, set()).add(row.material_id)

    relocations: list[Relocation] = []
    for row, resolved in located:
        if storage.belongs_to_material(resolved, row.material_id, root):
            continue
        new = f"{row.material_id}/{os.path.basename(resolved)}"
        relocations.append(
            Relocation(
                video_id=row.video_id,
                material_id=row.material_id,
                old=row.file_path,
                new=new,
                # 舊名字不在、但新位置已有檔：先前遷移過、之後只有 DB 被還原（舊名字已被孤兒清理收掉）
                # ——新位置那支就是它（`{MATERIAL_ID}/{uuid}` 只會由掛這支檔產生），改寫 DB 即可
                source_missing=not (os.path.lexists(os.path.join(root, row.file_path)) or _is_file(root, new)),
                course_id=row.course_id,
                shared=len(owners.get(_inode(resolved) or (-1, -1), ())) > 1,
            )
        )
    return Plan(relocations=relocations, escaped=escaped)


def _is_file(root: str, rel: str) -> bool:
    return os.path.isfile(os.path.join(root, rel))


async def _rewrite(
    db: AsyncSession, video_id: int, *, old: str, new: str, course_id: int | None, description: str
) -> bool:
    """`FILE_PATH` 由 old 改為 new 並寫稽核、commit；該列已被改成別的值時不動，回 False。"""
    result = await db.execute(
        update(EtMaterialVideo)
        .where(EtMaterialVideo.video_id == video_id, EtMaterialVideo.file_path == old)
        .values(file_path=new, updated_user=_SYSTEM, updated_date=utcnow())
    )
    if result.rowcount != 1:
        await db.rollback()
        return False
    # ET-COURSE 稽核的 target_id 是課程 id（DP05 依此顯示對象，#717）；影片 id 放描述。
    # 不帶路徑：路徑含教材 id 與內部檔名，DP05 管理者看得到稽核內容；完整對照在搬移紀錄
    await AuditLogService().log_action(
        db,
        module=_MODULE,
        func_name=_FUNC_NAME,
        action_type="UPDATE",
        result="SUCCESS",
        operator_id=_SYSTEM,
        target_id=None if course_id is None else str(course_id),
        description=f"{description}：影片 {video_id}",
        after_value=(await course_audit_payload(db, course_id) or None) if course_id is not None else None,
        # 維運腳本沒有發起請求的使用者（同排程），明示不帶而非漏帶
        source_ip=None,
    )
    await db.commit()
    return True


#: Windows 沒有 `O_NOFOLLOW`（該平台的檔名層級連結需管理者權限才建得出來）。
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _append_log(log_path: str, entry: dict) -> None:
    """追加一行到搬移紀錄。0600、不跟隨連結：紀錄是 `--revert` 的輸入，只該由執行本腳本的帳號寫。"""
    fd = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | _O_NOFOLLOW, 0o600)
    # 0600 只對新建檔生效；`--log` 指向既有檔時一併收緊，否則 `--revert` 會以「他人可寫」拒讀
    if hasattr(os, "fchmod"):
        os.fchmod(fd, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry | {"at": utcnow().isoformat()}, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


async def _relocate_one(db: AsyncSession, item: Relocation, *, log_path: str) -> bool:
    """記紀錄 → 掛新名字 → 改 DB。紀錄先寫的理由見模組 docstring。"""
    _append_log(
        log_path,
        {
            "video_id": item.video_id,
            "material_id": item.material_id,
            "course_id": item.course_id,
            "old": item.old,
            "new": item.new,
            "source_missing": item.source_missing,
        },
    )
    # 先掛再改 DB：反過來的話，掛失敗時那列指向一個不存在的檔。舊名字不在時（新位置已有檔，或
    # `--accept-missing`）沒有東西可掛
    if os.path.lexists(os.path.join(storage.storage_root(), item.old)):
        storage.link_into_material(item.old, item.material_id)
    return await _rewrite(
        db, item.video_id, old=item.old, new=item.new, course_id=item.course_id, description="影片目錄遷移（#871）"
    )


def _default_log_path(root: str) -> str:
    # 放在影片目錄：與資料一起備份；檔名不合 `is_managed_video_path`，孤兒清理不會碰
    return os.path.join(root, f".relocate-videos-{utcnow().strftime('%Y%m%d%H%M%S')}.jsonl")


async def run(
    db: AsyncSession,
    *,
    apply: bool,
    accept_missing: bool = False,
    allow_shared: bool = False,
    log_path: str | None = None,
    out: Callable[[str], None] = print,
) -> int:
    """dry-run 或執行遷移；回退出碼（見模組 docstring）。"""
    root = storage.storage_root()
    if not os.path.isdir(root):
        out(f"❌ 影片目錄不存在：{root}（確認 ET_VIDEO_STORAGE_ROOT 與掛載）")
        return 2

    current = plan(await load_rows(db), root)
    if current.escaped:
        out(f"⚠️ {current.escaped} 筆影片路徑逃出影片目錄，無從遷移（這些影片目前即無法播放），略過")
    for item in current.relocations:
        note = ("（檔案不存在）" if item.source_missing else "") + (
            "（⚠️ 同一支檔另被其他教材引用）" if item.shared else ""
        )
        out(f"video_id={item.video_id} material_id={item.material_id}：{item.old} → {item.new}{note}")
    missing = sum(r.source_missing for r in current.relocations)
    shared = sum(r.shared for r in current.relocations)
    out(f"待遷移 {len(current.relocations)} 筆（其中檔案不存在 {missing} 筆、需人工確認 {shared} 筆）")

    if not apply:
        enforced = "已生效" if storage.ownership_fence_enforced(root) else "尚未生效"
        out(f"dry-run：未做任何變更。歸屬圍籬{enforced}；加 --apply 執行")
        return 0

    log_path = log_path or _default_log_path(root)
    done = failed = 0
    for item in current.relocations:
        if (item.source_missing and not accept_missing) or (item.shared and not allow_shared):
            continue
        try:
            if await _relocate_one(db, item, log_path=log_path):
                done += 1
            else:
                failed += 1
                out(f"⚠️ video_id={item.video_id} 的 FILE_PATH 已被其他操作改動，略過（重跑時重新判定）")
        except (OSError, ValueError) as exc:
            await db.rollback()
            failed += 1
            out(f"❌ video_id={item.video_id} 遷移失敗：{type(exc).__name__}: {exc}")
    # 一筆都沒動手時紀錄檔不會被建立，不印一個不存在的路徑
    where = f"；搬移紀錄：{log_path}" if os.path.exists(log_path) else "；無搬移紀錄（未動手任何一筆）"
    out(f"已遷移 {done} 筆、失敗 {failed} 筆{where}")

    remaining = plan(await load_rows(db), root).relocations
    if remaining:
        out(
            f"⚠️ 仍有 {len(remaining)} 筆待處理，歸屬圍籬未生效。處理後重跑；檔案確定遺失者加 --accept-missing、"
            "確認「另被其他教材引用」屬正常者加 --allow-shared"
        )
        return 1
    storage.mark_ownership_fence_enforced(root)
    if not storage.ownership_fence_enforced(root):
        out("❌ 標記檔寫入後讀回不是一般檔（該位置可能被放了連結或目錄），歸屬圍籬未生效")
        return 2
    out("✅ 全部影片皆已落在所屬教材目錄，歸屬圍籬已生效")
    return 0


def _read_log(log_path: str, out: Callable[[str], None]) -> list[dict] | None:
    """讀搬移紀錄；檔案不可信時回 `None`，截斷 / 損壞的行略過並提示（中斷時最後一行可能只寫了一半）。

    紀錄放在影片目錄，對該目錄有寫入權者都改得到——須為執行者本人所有、他人不可寫，否則不讀。
    """
    try:
        fd = os.open(log_path, os.O_RDONLY | _O_NOFOLLOW)
    except OSError as exc:
        out(f"❌ 無法開啟搬移紀錄：{type(exc).__name__}")
        return None
    with os.fdopen(fd, encoding="utf-8") as f:
        st = os.fstat(f.fileno())
        if hasattr(os, "getuid") and (st.st_uid != os.getuid() or st.st_mode & 0o022):
            out("❌ 搬移紀錄不屬於目前帳號或可被他人寫入，拒絕依它回復")
            return None
        lines = f.readlines()
    entries: list[dict] = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            entry = None
        if _valid_entry(entry):
            entries.append(entry)
        else:
            out(f"⚠️ 搬移紀錄第 {lineno} 行無法解析或內容不合，略過")
    return entries


def _valid_entry(e: object) -> bool:
    """一行紀錄的形狀與 `_relocate_one` 寫出的一致：型別正確，`new` 是 `{material_id}/{舊檔名}`。"""
    if not isinstance(e, dict):
        return False
    vid, mid, old, new, missing = (e.get(k) for k in ("video_id", "material_id", "old", "new", "source_missing"))
    return (
        type(vid) is int
        and type(mid) is int
        and isinstance(old, str)
        and bool(old)
        and isinstance(missing, bool)
        and new == f"{mid}/{os.path.basename(old)}"
        and is_managed_video_path(new)
    )


async def _current(db: AsyncSession, video_id: int) -> tuple[str, int] | None:
    row = (
        await db.execute(
            select(EtMaterialVideo.file_path, EtMaterialVideo.material_id).where(EtMaterialVideo.video_id == video_id)
        )
    ).first()
    return None if row is None else (row[0], row[1])


async def _course_id_of(db: AsyncSession, material_id: int) -> int | None:
    return await db.scalar(
        select(EtChapter.course_id)
        .join(EtItem, EtItem.chapter_id == EtChapter.chapter_id)
        .where(EtItem.material_id == material_id)
        .limit(1)
    )


async def revert(db: AsyncSession, *, log_path: str, out: Callable[[str], None] = print) -> int:
    """依搬移紀錄把 `FILE_PATH` 改回舊值，並移除標記檔（先移除——回復期間播放端退回放行模式）。

    紀錄不當成可信輸入（見 `_read_log`）：每列**先在 DB 確認**目前確實是紀錄中的新路徑、且屬同一份
    教材，才動檔案；舊路徑須在 root 內；`course_id` 由 DB 重新推導。紀錄先寫後做，可能含沒做成的列，
    那些列不動、只提示。
    """
    root = storage.storage_root()
    entries = _read_log(log_path, out)
    if entries is None:
        return 2
    storage.clear_ownership_fence_marker(root)

    reverted = skipped = 0
    for e in reversed(entries):
        vid = e["video_id"]
        if await _current(db, vid) != (e["new"], e["material_id"]) or storage.locate_in_root(e["old"], root) is None:
            skipped += 1
            out(f"⚠️ video_id={vid} 的 FILE_PATH 不是紀錄中的新路徑（未遷移成功或之後被改過），未回復")
            continue
        try:
            if not e["source_missing"]:
                storage.link_back(e["new"], e["old"])
            ok = await _rewrite(
                db,
                vid,
                old=e["new"],
                new=e["old"],
                course_id=await _course_id_of(db, e["material_id"]),
                description="影片目錄遷移回復（#871）",
            )
        except (OSError, ValueError) as exc:
            await db.rollback()
            ok = False
            out(f"❌ video_id={vid} 回復失敗：{type(exc).__name__}: {exc}")
        if ok:
            reverted += 1
        else:
            skipped += 1
    out(f"已回復 {reverted} 筆、未回復 {skipped} 筆；歸屬圍籬已撤銷")
    return 0 if skipped == 0 else 1


async def _amain(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.et.material.relocate_videos", description=__doc__.split("\n")[0]
    )
    parser.add_argument("--apply", action="store_true", help="執行遷移（未指定時為 dry-run）")
    parser.add_argument("--accept-missing", action="store_true", help="來源檔不存在者照樣改寫路徑")
    parser.add_argument("--allow-shared", action="store_true", help="同一支檔另被其他教材引用者照樣遷移（先人工確認）")
    parser.add_argument("--log", help="搬移紀錄路徑（預設寫在影片目錄下）")
    parser.add_argument("--revert", metavar="LOG", help="依搬移紀錄回復")
    args = parser.parse_args(argv)

    try:
        async with AsyncSessionLocal() as db:
            if args.revert:
                return await revert(db, log_path=args.revert)
            return await run(
                db,
                apply=args.apply,
                accept_missing=args.accept_missing,
                allow_shared=args.allow_shared,
                log_path=args.log,
            )
    except Exception as exc:
        print(f"❌ 執行錯誤：{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(_amain()))
