"""操作手冊 md 檢查（TBMS）

產出 Word 之前先跑本檔，攔下格式與規範問題。

本檔只驗「機器判得出來」的部分——圖片是否存在、表格欄數、標題層級、禁用字樣。
內容是否與系統一致（按鈕名稱、欄位名稱、實際行為）**驗不到**，那只能對截圖或實機
核對。產生器不會因內容寫錯而失敗，Word 產得出來不代表內容是對的。

用法：
    python docs/manuals/tools/check_manual.py            # 檢查全部
    python docs/manuals/tools/check_manual.py <檔案.md>  # 檢查單檔
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from manual_config import (   # noqa: E402  專案專屬設定一律自本檔讀取
    MODULE_DIRS, MANUAL_NAME_RE, MSG_CODE_RE, TABLE_NAME_RE, NON_MANUAL_FILES)

MANUAL_ROOT = Path("docs/manuals")
# 底線開頭之資料夾中，_shots（待拍清單）與 _images 為內部工作文件，不進交付文件，
# 不予檢查；⚠️ **_tests 例外**——測試項目會產出交付院方之測試報告，同受〈禁止事項〉
# 與〈不使用人稱代詞〉拘束，故納入檢查，其與手冊相異之處由 is_test_file 分流。
INTERNAL_DIRS = ("_shots", "_images")

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
IMAGE_RE = re.compile(r"!\[(?P<alt>.*?)\]\((?P<src>.+?)\)")
TABLE_RE = re.compile(r"^\s*\|(.+)\|\s*$")
QUOTE_RE = re.compile(r"^>\s*(.*)$")

# 規範〈禁止事項〉之機械可判定部分（訊息代碼與資料表名依專案而異，見 manual_config）
ICON_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿⬀-⯿️✅❌❗⚠]")
ISSUE_RE = re.compile(r"(?<![A-Za-z0-9])#\d{3,}|\bPR\s*#\d+")
SOURCE_REF_RE = re.compile(r"\b\w+\.(ts|tsx|py)\b")
TEST_TERM_RE = re.compile(r"首測|複測|回測|陪測")
# 反向表述之典型句型。手冊為產品使用說明，寫「你要做什麼」而非「系統沒做什麼」；
# ⚠️ 僅提示不擋，少數情形確實只能反向陳述，由人判斷（見規範〈一律正向表述〉）
NEGATIVE_VOICE_RE = re.compile(r"系統(?:並|也)?不|不會自動|全系統唯一|唯一看得到|不提供")
# 人稱代詞：交付文件不用「你」「我」，改以本站／該站人員／作業人員表達，或直接省略。
# ⚠️ 「他」不納入——「他院區」「他站」「其他」皆為既有用語，誤報會淹沒真問題
PRONOUN_RE = re.compile(r"你|我(?!方)")
ALLOWED_QUOTE_PREFIX = ("注意：", "重要：")


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, path: Path, line: int, msg: str) -> None:
        self.errors.append(f"  {path}:{line}  {msg}")

    def warn(self, path: Path, line: int, msg: str) -> None:
        self.warnings.append(f"  {path}:{line}  {msg}")


def check_file(path: Path, report: Report) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    is_test_file = path.parent.name == "_tests"

    heading_levels: list[int] = []
    h1_count = 0
    table_block: list[tuple[int, int]] = []   # (行號, 欄數)
    in_quote_block = False

    for no, line in enumerate(lines, 1):
        # 標題層級
        if match := HEADING_RE.match(line):
            level = len(match.group(1))
            if level == 1:
                h1_count += 1
            if heading_levels and level > heading_levels[-1] + 1:
                report.error(path, no,
                             f"標題跳級：由 {'#' * heading_levels[-1]} 直接跳到 {'#' * level}")
            heading_levels.append(level)
            if re.match(r"^[壹貳參肆伍陸柒捌玖拾一二三四五六七八九十（(]", match.group(2)):
                report.error(path, no, "標題不可自行編號，編號由產生器產生")

        # 圖片：路徑與圖說
        for img in IMAGE_RE.finditer(line):
            src = (path.parent / img.group("src")).resolve()
            if not src.exists():
                report.error(path, no, f"圖片不存在：{img.group('src')}")
            if not img.group("alt").strip():
                report.error(path, no, "圖片缺圖說")

        # 表格欄數一致性
        if match := TABLE_RE.match(line):
            cols = len(match.group(1).split("|"))
            table_block.append((no, cols))
        elif table_block:
            counts = {c for _, c in table_block}
            if len(counts) > 1:
                report.error(path, table_block[0][0],
                             f"表格欄數不一致：{sorted(counts)}")
            table_block = []

        # 提醒框前綴：只驗區塊首行，續行不重複要求前綴
        if (match := QUOTE_RE.match(line)) and not is_test_file and not in_quote_block:
            text = match.group(1)
            # 以引號起始者為引用系統訊息原文，非提醒框
            if text and not text.startswith(ALLOWED_QUOTE_PREFIX) and not text.startswith("「"):
                report.warn(path, no, f"提醒框未以「注意：」或「重要：」起始：{text[:20]}")
        in_quote_block = bool(QUOTE_RE.match(line))

        # 禁用字樣
        if ICON_RE.search(line):
            report.error(path, no, "含圖示符號，交付文件不得使用")
        if MSG_CODE_RE.search(line):
            report.error(path, no, "含訊息代碼，應改引訊息原文")
        if ISSUE_RE.search(line):
            report.error(path, no, "含 issue／PR 編號")
        if TABLE_NAME_RE.search(line):
            report.error(path, no, "含資料表名稱")
        if SOURCE_REF_RE.search(line):
            report.error(path, no, "含程式檔名")
        if TEST_TERM_RE.search(line):
            report.error(path, no, "含測試流程用語")
        if not is_test_file and (m := NEGATIVE_VOICE_RE.search(line)):
            report.warn(path, no, f"疑似反向表述「{m.group()}」；手冊寫該功能做什麼、"
                                  f"如何操作，不寫「系統沒做什麼」")
        if m := PRONOUN_RE.search(line):
            report.warn(path, no, f"含人稱代詞「{m.group()}」；改以本站／該站人員／"
                                  f"作業人員表達，或直接省略")

    if h1_count != 1:
        report.error(path, 1, f"應恰有一個一級標題（作業名），實際 {h1_count} 個")

    # 結構檢查
    chapters = [HEADING_RE.match(l).group(2) for l in lines if HEADING_RE.match(l)
                and len(HEADING_RE.match(l).group(1)) == 2]
    if is_test_file:
        # 一個模組一檔：## 為作業、### 為該作業之測試前準備與項目清單
        operations: list[tuple[str, set[str]]] = []
        for line in lines:
            if match := HEADING_RE.match(line):
                level, text = len(match.group(1)), match.group(2)
                if level == 2:
                    operations.append((text, set()))
                elif level == 3 and operations:
                    operations[-1][1].add(text)
        if not operations:
            report.error(path, 1, "測試項目檔無任何作業章節（格式：## 作業碼 作業名）")
        for name, subsections in operations:
            for required in ("測試前準備", "測試項目清單"):
                if required not in subsections:
                    report.error(path, 1, f"作業「{name}」缺少「{required}」")
    elif path.parent.name in MODULE_DIRS:
        if "常見訊息與處置" not in chapters:
            report.warn(path, 1, "手冊無〈常見訊息與處置〉章")


def main() -> int:
    parser = argparse.ArgumentParser(description="操作手冊 md 檢查")
    parser.add_argument("source", type=Path, nargs="?", default=MANUAL_ROOT,
                        help="檔案或目錄（預設 docs/manuals）")
    args = parser.parse_args()

    if args.source.is_dir():
        candidates = [p for p in sorted(args.source.rglob("*.md"))
                      if p.name not in NON_MANUAL_FILES
                      and not any(d in INTERNAL_DIRS for d in p.parent.parts)]
        targets, skipped = [], []
        for path in candidates:
            # 模組目錄下之檔案須符合命名慣例，否則非本流程產出
            if path.parent.name in MODULE_DIRS and not MANUAL_NAME_RE.match(path.stem):
                skipped.append(path)
            else:
                targets.append(path)
    else:
        targets, skipped = [args.source], []

    report = Report()
    for path in targets:
        check_file(path, report)

    print(f"檢查 {len(targets)} 個檔案")
    if skipped:
        print(f"（略過 {len(skipped)} 個非本流程產出之檔案："
              f"{'、'.join(str(p.relative_to(args.source)) for p in skipped)}，"
              f"檔名不符「作業碼-作業名」慣例）")
    if report.errors:
        print(f"\n錯誤 {len(report.errors)} 項（必須修正）：")
        print("\n".join(report.errors))
    if report.warnings:
        print(f"\n提醒 {len(report.warnings)} 項：")
        print("\n".join(report.warnings))
    if not report.errors and not report.warnings:
        print("格式檢查通過。")
    print("\n提醒：本檢查驗不到內容是否與系統一致——按鈕、欄位名稱與實際行為請對截圖核對。")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
