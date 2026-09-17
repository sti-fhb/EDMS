"""測試報告產生器（TBMS 操作手冊配套）

從 docs/manuals/_tests/ 之測試項目來源檔，產出院方格式（附表 7）之測試報告 Word 檔，
供操作人員逐項測試並勾選合格／不合格。

**一個模組一個來源檔、一份 Word**：封面、修訂履歷與目錄同操作手冊（共用樣式範本），
其後各作業獨立一節、各成一張測試報告表，項次於各表內自 1 起算。

用法：
    python gen_acceptance_form.py            # 產出 _tests/ 下全部模組
    python gen_acceptance_form.py <檔案.md>  # 單一模組

⚠️ 測試項目與操作手冊分開維護：手冊供操作人員照做，本表供驗收勾選，讀者與用途皆不同。
⚠️ 測試內容唯一來源為 _tests/ 下之 md，⛔ 不在本檔另寫一份——兩份必然漂移。
⚠️ 表格格式依院方提供之附表 7 圖樣重刻（無原始範本檔）；取得範本後應改以範本套版。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, Cm

sys.path.insert(0, str(Path(__file__).parent))
from gen_manual import build_front_matter, open_template   # noqa: E402
from manual_config import (   # noqa: E402  專案專屬設定一律自本檔讀取
    PROJECT_NAME, REPORT_DOC_NAME as DOC_NAME, FORM_TITLE)

FORM_FONT = "標楷體"

# 兩張表各自的欄寬：基本資料表與項目表欄位意義不同，不共用寬度
INFO_WIDTHS = (Cm(2.6), Cm(6.4), Cm(3.4), Cm(4.6))
ITEM_WIDTHS = (Cm(1.6), Cm(11.0), Cm(2.2), Cm(2.2))

OPERATION_RE = re.compile(r"^##\s+(?P<name>\S+\s+.+?)\s*$")   # 「## BS01 血品入庫」
ITEM_SECTION = re.compile(r"^###\s+測試項目清單\s*$")
TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _spacing_element(twips: int):
    el = OxmlElement("w:spacing")
    el.set(qn("w:val"), str(twips))
    return el


def _style_run(run, *, size: int = 12, bold: bool = False, spacing: bool = False):
    run.font.name = FORM_FONT
    run._element.rPr.rFonts.set(qn("w:eastAsia"), FORM_FONT)
    run.font.size = Pt(size)
    run.bold = bold
    if spacing:  # 標題字距加寬，貼近院方表頭樣式
        run.font.element.rPr.append(_spacing_element(80))
    return run


def _set_cell(cell, text: str, *, size: int = 12, bold: bool = False,
              align=WD_ALIGN_PARAGRAPH.CENTER, spacing: bool = False):
    cell.text = ""
    para = cell.paragraphs[0]
    para.alignment = align
    para.paragraph_format.space_before = Pt(2)
    para.paragraph_format.space_after = Pt(2)
    _style_run(para.add_run(text), size=size, bold=bold, spacing=spacing)
    return cell


def _apply_widths(row, widths) -> None:
    for cell, width in zip(row.cells, widths):
        cell.width = width


def _repeat_as_header(row) -> None:
    """標記為標題列，跨頁時於每頁頂端重複。

    ⚠️ Word 僅重複「表格最前面連續」之標題列，故基本資料與項目清單 MUST 拆為兩張
    表格——否則欲重複項目表頭，連購案名稱與用印欄都會跟著印在每一頁。
    """
    trPr = row._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    trPr.append(header)


def parse_module(md_path: Path) -> tuple[str, list[tuple[str, list[tuple[str, str]]]]]:
    """回傳 (模組名稱, [(作業名稱, [(項次, 測試內容), ...]), ...])。"""
    lines = md_path.read_text(encoding="utf-8").splitlines()

    module = md_path.stem
    for line in lines:
        if line.startswith("# "):
            module = line[2:].strip()
            break

    operations: list[tuple[str, list[tuple[str, str]]]] = []
    in_items = False

    for line in lines:
        if match := OPERATION_RE.match(line):
            operations.append((match.group("name"), []))
            in_items = False
            continue
        if ITEM_SECTION.match(line):
            in_items = True
            continue
        if line.startswith("#"):            # 其他標題即結束項目區
            in_items = False
            continue
        if not in_items or not operations:
            continue
        if match := TABLE_ROW.match(line):
            cells = [c.strip() for c in match.group(1).split("|")]
            if len(cells) < 2:
                continue
            no, content = cells[0], cells[1]
            if no == "項次" or set(no) <= set("-: "):   # 表頭與分隔列
                continue
            operations[-1][1].append((no, BOLD_RE.sub(lambda m: m.group(1), content)))

    operations = [(name, items) for name, items in operations if items]
    if not operations:
        raise ValueError(f"{md_path.name} 無任何作業之「### 測試項目清單」，不產出測試報告")
    return module, operations


def _add_info_table(doc) -> None:
    """表一：表頭與受測資訊（不跨頁重複）。"""
    table = doc.add_table(rows=0, cols=4)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    row = table.add_row()
    _apply_widths(row, INFO_WIDTHS)
    _set_cell(row.cells[0].merge(row.cells[3]), FORM_TITLE, size=16, bold=True, spacing=True)

    for left_label, left_value, right_label in (
        ("購案名稱", PROJECT_NAME, "單位主管用印"),
        ("測試單位", "", "測試人員"),
        ("測試日期", "", "測試完畢日期"),
    ):
        row = table.add_row()
        _apply_widths(row, INFO_WIDTHS)
        _set_cell(row.cells[0], left_label)
        _set_cell(row.cells[1], left_value)
        _set_cell(row.cells[2], right_label)
        _set_cell(row.cells[3], "")


def _add_item_table(doc, items: list[tuple[str, str]]) -> None:
    """表二：測試項目，表頭兩列跨頁重複。"""
    table = doc.add_table(rows=0, cols=4)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    head_top = table.add_row()
    head_bottom = table.add_row()
    _apply_widths(head_top, ITEM_WIDTHS)
    _apply_widths(head_bottom, ITEM_WIDTHS)

    _set_cell(head_top.cells[0].merge(head_bottom.cells[0]), "項次")
    _set_cell(head_top.cells[1].merge(head_bottom.cells[1]), "測試內容")
    _set_cell(head_top.cells[2].merge(head_top.cells[3]), "測試人員勾選")
    _set_cell(head_bottom.cells[2], "合格")
    _set_cell(head_bottom.cells[3], "不合格")
    _repeat_as_header(head_top)
    _repeat_as_header(head_bottom)

    for no, content in items:
        row = table.add_row()
        _apply_widths(row, ITEM_WIDTHS)
        _set_cell(row.cells[0], no, size=11)
        _set_cell(row.cells[1], content, size=11, align=WD_ALIGN_PARAGRAPH.LEFT)
        _set_cell(row.cells[2], "")
        _set_cell(row.cells[3], "")


def _add_operation(doc, operation: str, items: list[tuple[str, str]], first: bool) -> None:
    heading = doc.add_paragraph(operation, style="Heading 1")
    if not first:
        heading.paragraph_format.page_break_before = True
    _add_info_table(doc)
    doc.add_paragraph()          # 兩表之間留一行，避免框線相黏
    _add_item_table(doc, items)


def build_report(module: str, operations: list[tuple[str, list[tuple[str, str]]]],
                 out_path: Path, source: Path) -> None:
    doc, break_p = open_template()
    for index, (operation, items) in enumerate(operations):
        _add_operation(doc, operation, items, first=(index == 0))
    build_front_matter(doc, break_p, module, None, doc_name=DOC_NAME, source=source)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    detail = "、".join(f"{name} {len(items)} 項" for name, items in operations)
    print(f"已產出：{out_path}（{len(operations)} 支作業：{detail}）")


def main() -> None:
    parser = argparse.ArgumentParser(description="測試項目 → 測試報告")
    parser.add_argument("source", type=Path, nargs="?", default=Path("docs/manuals/_tests"),
                        help="測試項目 .md 檔或目錄（預設 docs/manuals/_tests）")
    parser.add_argument("-o", "--output", type=Path, default=Path("docs/manuals/測試報告"),
                        help="輸出目錄（預設 docs/manuals/測試報告）")
    args = parser.parse_args()

    sources = sorted(args.source.rglob("*.md")) if args.source.is_dir() else [args.source]
    for md in sources:
        try:
            module, operations = parse_module(md)
        except ValueError as exc:
            print(f"略過：{exc}")
            continue
        build_report(module, operations, args.output / f"{md.stem}.docx", md)


if __name__ == "__main__":
    main()
