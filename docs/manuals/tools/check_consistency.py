"""交付文件一致性檢查（TBMS）

`check_manual.py` 驗的是**單檔格式**；本檔驗的是**跨檔關係**——手冊、測試項目、
圖片、產出之 Word 與待拍清單彼此是否對得上。

交付前跑一次，可攔下：
- Word 舊於其來源 md（改了 md 忘記重新產出）
- 手冊與測試項目之作業覆蓋不一致（有手冊沒測試項目，或反之）
- 同一支作業在檔名、文件標題、測試項目章節三處名稱不一致
- 圖片檔存在卻無人引用（孤兒圖），或待拍清單與實際缺圖對不上

⚠️ 仍驗不到**內容是否與系統一致**——按鈕、欄位、行為描述請對截圖或實機核對。

用法：
    python docs/manuals/tools/check_consistency.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from manual_config import (   # noqa: E402  專案專屬設定一律自本檔讀取
    MODULE_DIRS, OPERATION_CODE_RE as FILENAME_RE)

MANUAL_ROOT = Path("docs/manuals")
IMAGE_ROOT = MANUAL_ROOT / "_images"
TEST_ROOT = MANUAL_ROOT / "_tests"
REPORT_ROOT = MANUAL_ROOT / "測試報告"
SHOTS_ROOT = MANUAL_ROOT / "_shots"
SPEC = MANUAL_ROOT / "手冊撰寫規範.md"

IMAGE_RE = re.compile(r"!\[(?P<alt>.*?)\]\((?P<src>.+?)\)")
OPERATION_RE = re.compile(r"^##\s+(?P<code>[A-Z]{2}\d{2})\s+(?P<name>.+?)\s*$")


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(f"  {msg}")

    def warn(self, msg: str) -> None:
        self.warnings.append(f"  {msg}")


def _manuals() -> list[Path]:
    """僅取符合命名慣例（作業碼-作業名）者；其餘非本流程產出，不予檢查。"""
    return [p for d in MODULE_DIRS if (MANUAL_ROOT / d).is_dir()
            for p in sorted((MANUAL_ROOT / d).glob("*.md"))
            if FILENAME_RE.match(p.stem)]


def _in_progress() -> set[str]:
    """尚有待拍清單之作業碼——圖未拍齊，不應以「已交付」之標準檢查。"""
    if not SHOTS_ROOT.is_dir():
        return set()
    return {m.group(1) for shot in SHOTS_ROOT.glob("*.md")
            if (m := re.match(r"([A-Z]{2}\d{2})", shot.stem))}


def _title_of(md: Path) -> str | None:
    for line in md.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def check_outputs_fresh(report: Report) -> None:
    """Word 不得舊於其來源 md。"""
    pairs = [(md, md.with_suffix(".docx")) for md in _manuals()]
    pairs += [(md, REPORT_ROOT / f"{md.stem}.docx") for md in sorted(TEST_ROOT.glob("*.md"))]

    ongoing = _in_progress()
    for src, out in pairs:
        if not src.exists():
            continue
        if (m := FILENAME_RE.match(src.stem)) and m.group("code") in ongoing:
            continue                      # 進行中：圖未拍齊，尚不需產出
        if not out.exists():
            continue                      # 撰寫期間只維護 md，Word 待定版後統一產出
        if out.stat().st_mtime < src.stat().st_mtime:
            # 時間戳會因 git 操作（checkout／rebase／stash）而失真，故僅提示
            report.warn(f"產出可能過期：{out.name} 之時間早於 {src.name}；"
                        f"若非剛做過 git 操作，請重新產出")


def check_operation_coverage(report: Report) -> dict[str, str]:
    """手冊與測試項目之作業覆蓋須一致；回傳 {作業碼: 手冊標題}。"""
    manual_ops: dict[str, str] = {}
    for md in _manuals():
        match = FILENAME_RE.match(md.stem)
        if not match:
            report.warn(f"檔名不符慣例（作業碼-作業名）：{md.name}")
            continue
        manual_ops[match.group("code")] = match.group("name")

    test_ops: dict[str, str] = {}
    for md in sorted(TEST_ROOT.glob("*.md")):
        for line in md.read_text(encoding="utf-8").splitlines():
            if m := OPERATION_RE.match(line):
                test_ops[m.group("code")] = m.group("name")

    for code, name in manual_ops.items():
        if code not in test_ops:
            report.error(f"缺測試項目：{code} {name} 有手冊，測試項目檔無該作業章節")
    for code, name in test_ops.items():
        if code not in manual_ops:
            report.warn(f"缺手冊：{code} {name} 有測試項目，但無對應手冊")

    # 名稱三處一致：檔名、文件標題、測試項目章節
    for md in _manuals():
        match = FILENAME_RE.match(md.stem)
        if not match:
            continue
        code, name = match.group("code"), match.group("name")
        title = _title_of(md)
        if title != f"{code} {name}":
            report.error(f"名稱不一致：{md.name} 之標題為「{title}」，與檔名不符")
        if code in test_ops and test_ops[code] != name:
            report.error(
                f"名稱不一致：{code} 手冊作「{name}」、測試項目作「{test_ops[code]}」")
    return manual_ops


def check_images(report: Report) -> set[str]:
    """圖片須被引用；回傳所有被引用之圖檔名。"""
    referenced: set[str] = set()
    for md in _manuals():
        for image in IMAGE_RE.finditer(md.read_text(encoding="utf-8")):
            referenced.add(Path(image.group("src")).name)

    ongoing = _in_progress()
    for path in sorted(IMAGE_ROOT.rglob("*.png")):
        if path.name in referenced:
            continue
        if any(path.stem.upper().startswith(code) for code in ongoing):
            continue                      # 進行中：已拍待接，非孤兒
        report.warn(f"孤兒圖片：{path.relative_to(MANUAL_ROOT)} 未被任何手冊引用")
    return referenced


def check_pending_shots(report: Report, referenced: set[str]) -> None:
    """待拍清單與實際缺圖須對得上。"""
    if not SHOTS_ROOT.is_dir():
        return
    pattern = rf"((?:{'|'.join(MODULE_DIRS)})\d{{2}}-\d{{2}})\.png"
    listed: set[str] = set()
    for shot in sorted(SHOTS_ROOT.glob("*.md")):
        listed |= set(re.findall(pattern, shot.read_text(encoding="utf-8")))
    existing = {p.stem for p in IMAGE_ROOT.rglob("*.png")}

    done = listed & existing
    if done and len(done) == len(listed):
        report.warn(f"待拍清單可刪除：{len(done)} 張已全數拍攝完成，請移除 _shots/ 下之清單檔")

    missing = {Path(n).stem for n in referenced} - existing
    for name in sorted(missing):
        if name not in listed:
            report.error(f"缺圖未列清單：手冊引用 {name}.png 但檔案不存在，且未列入待拍清單")


def check_spec_catalog(report: Report, manual_ops: dict[str, str]) -> None:
    """手冊作業名稱須與規範之對照表相符。"""
    if not SPEC.exists():
        return
    catalog = dict(re.findall(r"\|\s*([A-Z]{2}\d{2})\s*\|\s*([^|]+?)\s*\|", SPEC.read_text(encoding="utf-8")))
    for code, name in manual_ops.items():
        if code in catalog and catalog[code] != name:
            report.error(
                f"名稱與規範對照表不符：{code} 手冊作「{name}」、規範作「{catalog[code]}」")


def main() -> int:
    if not MANUAL_ROOT.exists():
        print(f"找不到 {MANUAL_ROOT}，請於專案根目錄執行")
        return 1

    report = Report()
    check_outputs_fresh(report)
    manual_ops = check_operation_coverage(report)
    referenced = check_images(report)
    check_pending_shots(report, referenced)
    check_spec_catalog(report, manual_ops)

    print(f"一致性檢查：手冊 {len(manual_ops)} 支")
    if report.errors:
        print(f"\n錯誤 {len(report.errors)} 項（必須修正）：")
        print("\n".join(report.errors))
    if report.warnings:
        print(f"\n提醒 {len(report.warnings)} 項：")
        print("\n".join(report.warnings))
    if not report.errors and not report.warnings:
        print("各檔一致。")
    print("\n提醒：本檢查驗不到內容是否與系統一致——按鈕、欄位與行為描述請對截圖核對。")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
