"""教育訓練簡報產生器（EDMS；同步自 TBMS）

自 `_training/` 下之 md 產出 PowerPoint 教材。與操作手冊同一套來源原則：
md 是唯一來源，pptx 一律重新產生、不得手改。

投影片對應：
    #     文件標題（僅供封面）
    ##    課程段落 → 章節分隔頁
    ###   一張投影片
    - / 1.  條列（投影片本體，一張 3～5 條）
    ![]() 截圖（置於條列下方，投影用需大而清楚）
    | |   表格
    > 講稿：…  完整版備忘稿（種子教官照著講）
    > 提示：…  重點版備忘稿（自己講時的提醒）

備忘稿兩版並存於同一份 md，產出時擇一——**一個模組只出一份簡報**：
    python gen_training_deck.py <md>                → 用完整講稿（預設）
    python gen_training_deck.py <md> --notes brief  → 改用重點提示

⚠️ 投影片是**投在牆上看的**，不是拿在手上讀的：每張只放要點，
完整說明一律寫進備忘稿（見〈教育訓練教材規範〉）。
"""

from __future__ import annotations

import argparse
import re
import sys
from math import ceil
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Cm, Emu, Pt

sys.path.insert(0, str(Path(__file__).parent))
from manual_config import (   # noqa: E402  專案專屬設定一律自本檔讀取
    PROJECT_NAME, PROJECT_CASE_NO, SYSTEM_NAME, VENDOR,
    TRAINING_DOC_NAME, DECK_FONT, DECK_FONT_EN, DECK_COLORS)

# ---- 版面 ----------------------------------------------------------------
# 16:9。⛔ 不用 4:3——現行投影機與螢幕皆為寬螢幕，4:3 會在兩側留下黑邊。
SLIDE_W, SLIDE_H = Cm(33.87), Cm(19.05)

MARGIN = Cm(2.3)           # 左右邊界，全篇一致
EYEBROW_TOP = Cm(1.3)      # 英文小標
TITLE_TOP = Cm(2.3)        # 中文主標
RULE_TOP = Cm(4.2)         # 標題下之細分隔線
BODY_TOP = Cm(4.9)
FOOTER_TOP = Cm(17.8)
BODY_H = FOOTER_TOP - BODY_TOP - Cm(0.5)

EYEBROW_SIZE = Pt(18)      # 英文小標：襯線體
TITLE_SIZE = Pt(28)        # 中文主標
BULLET_SIZE = Pt(20)       # 條列：投影用，⛔ 不小於 18pt
SECTION_SIZE = Pt(36)      # 章節分隔頁
COVER_TITLE = Pt(36)
TABLE_SIZE = Pt(16)
MAX_BULLETS = 6            # 超過即應拆頁（檢查工具據此提醒）

HEADING_RE = re.compile(r"^(?P<level>#{1,3})\s+(?P<text>.+)$")
IMAGE_RE = re.compile(r"^!\[(?P<alt>.*?)\]\((?P<src>[^\s)]+)(?:\s+\"(?P<title>[^\"]*)\")?\)$")
LIST_RE = re.compile(r"^\s*(?P<bullet>[-*]|\d+\.)\s+(?P<text>.+)$")
TABLE_RE = re.compile(r"^\s*\|(.+)\|\s*$")
NOTE_RE = re.compile(r"^>\s*(?P<kind>講稿|提示)：\s*(?P<text>.+)$")
CALLOUT_RE = re.compile(r"^>\s*重點：\s*(?P<text>.+)$")
# 隱藏投影片：放映時跳過、列印與備忘稿仍在（附件、備查資料用）
HIDE_RE = re.compile(r"^>\s*隱藏投影片\s*$")
# 結語頁：沿用封面版式（大字、左側色條、無頁首頁尾），用於「謝謝聆聽」收尾
CLOSING_RE = re.compile(r"^>\s*結語頁\s*$")
# 封面與大綱頁之備忘稿：此二頁由產生器自動產出，md 無對應之 `###`，
# 故其講稿寫於檔首（`#` 之後、第一個 `##` 之前）
FRONT_RE = re.compile(r"^>\s*(?P<kind>封面|大綱)：\s*(?P<text>.+)$")
# 封面欄位：英文名、課程日期、講師，寫於檔首；⚠️ 日期未定時留空，產出即不印該列
META_RE = re.compile(r"^>\s*(?P<key>英文名|課程日期|講師)：\s*(?P<value>.*)$")
INLINE_RE = re.compile(r"(\*\*.+?\*\*)")
FENCE_RE = re.compile(r"^```\s*(?P<kind>flow|cards-block|cards|steps)?\s*$")
# 流程圖：`節點 -標籤-> 節點 -標籤-> 節點`，箭頭上之標籤可省略
# 箭頭：`->` 或 `-標籤->`。⚠️ 標籤段須整段可選，否則無標籤之 `->` 匹配不到，
# 整行會被當成單一節點（症狀：流程圖只畫出一個方塊，內含整行文字）
ARROW_RE = re.compile(r"\s*-(?:(?P<label>[^>-]*)-)?>\s*")


def _rgb(name: str) -> RGBColor:
    return RGBColor.from_string(DECK_COLORS[name])


def _textbox(slide, left, top, width, height):
    box = slide.shapes.add_textbox(left, top, width, height)
    frame = box.text_frame
    frame.word_wrap = True
    return frame


def _add_runs(para, text: str, size, color: str = "text", bold: bool = False,
              strong_color: bool = True):
    """**粗體**以強調色標出——投影片上的重點要一眼看見。

    ⚠️ 表格內須關閉 strong_color：整欄轉紅會過度搶眼，只加粗即可。
    """
    for part in INLINE_RE.split(text):
        if not part:
            continue
        strong = part.startswith("**") and part.endswith("**")
        run = para.add_run()
        run.text = part[2:-2] if strong else part
        run.font.size = size
        run.font.name = DECK_FONT
        run.font.bold = bold or strong
        run.font.color.rgb = _rgb("accent" if (strong and strong_color) else color)


# ---- 版面元件 ------------------------------------------------------------

def _brand_bar(slide) -> None:
    """底部裝飾帶：貫穿全篇的視覺識別，左段以亮色分段。

    ⚠️ 全篇每一張都要有（含封面與章節頁），少了任何一張都會顯得像另一份文件。
    """
    bar = slide.shapes.add_shape(1, 0, SLIDE_H - Cm(0.45), SLIDE_W, Cm(0.45))
    bar.fill.solid()
    bar.fill.fore_color.rgb = _rgb("primary")
    bar.line.fill.background()
    bar.shadow.inherit = False

    seg = slide.shapes.add_shape(1, 0, SLIDE_H - Cm(0.45), Cm(7.5), Cm(0.45))
    seg.fill.solid()
    seg.fill.fore_color.rgb = _rgb("brand")
    seg.line.fill.background()
    seg.shadow.inherit = False


def _rule(slide, top, width=None) -> None:
    """細分隔線。⛔ 不用深色或粗線——它的作用是分隔，不是吸引目光。"""
    line = slide.shapes.add_shape(1, MARGIN, top, width or (SLIDE_W - MARGIN * 2), Pt(1))
    line.fill.solid()
    line.fill.fore_color.rgb = _rgb("rule")
    line.line.fill.background()
    line.shadow.inherit = False


def _heading(slide, eyebrow: str, title: str) -> None:
    """頁首：英文小標 + 中文主標 + 細線。⛔ 不鋪色塊（留白式版面）。"""
    if eyebrow:
        frame = _textbox(slide, MARGIN, EYEBROW_TOP, SLIDE_W - MARGIN * 2, Cm(1.0))
        para = frame.paragraphs[0]
        run = para.add_run()
        run.text = eyebrow
        run.font.size = EYEBROW_SIZE
        run.font.name = DECK_FONT_EN
        run.font.color.rgb = _rgb("primary")

    frame = _textbox(slide, MARGIN, TITLE_TOP, SLIDE_W - MARGIN * 2, Cm(1.7))
    _add_runs(frame.paragraphs[0], title, TITLE_SIZE, bold=True)
    _rule(slide, RULE_TOP)


def _footer(slide, module: str, page: int, total: int) -> None:
    frame = _textbox(slide, MARGIN, FOOTER_TOP, Cm(16), Cm(0.8))
    _add_runs(frame.paragraphs[0], f"{VENDOR[:4]} ｜ {SYSTEM_NAME} ｜ {module}",
              Pt(10), color="muted")

    num = _textbox(slide, SLIDE_W - MARGIN - Cm(10), FOOTER_TOP, Cm(10), Cm(0.8))
    para = num.paragraphs[0]
    para.alignment = PP_ALIGN.RIGHT
    _add_runs(para, f"第 {page} 頁，共 {total} 頁", Pt(10), color="muted")


def _notes(slide, text: str) -> None:
    if text:
        slide.notes_slide.notes_text_frame.text = text


def _callout(slide, text: str, top, width) -> int:
    """重點框：整張最關鍵的一句話，以淺色塊承載。

    ⚠️ 一張至多一個——每句都強調等於都不強調。
    """
    height = Cm(2.4)
    box = slide.shapes.add_shape(5, MARGIN, int(top), width, height)
    box.fill.solid()
    box.fill.fore_color.rgb = _rgb("surface")
    box.line.color.rgb = _rgb("brand")
    box.line.width = Pt(2)
    box.shadow.inherit = False

    frame = box.text_frame
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = Cm(0.8)
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    para = frame.paragraphs[0]
    para.alignment = PP_ALIGN.CENTER
    _add_runs(para, text, Pt(22), bold=True)
    return height


CARD_GAP = Cm(0.8)


def _text_width(text: str) -> float:
    """以中文字寬為 1 估算字串寬度；ASCII（BS01 這類編號）約佔半格多。"""
    return sum(0.55 if c.isascii() else 1.0 for c in text)


HEAD_CHAR_W = 0.80      # 標題 20pt 粗體之單字寬（公分，連同字距）
BODY_CHAR_W = 0.60      # 說明 15pt 之單字寬
CARD_PADDING = 1.4      # 卡片左右內距合計


def _card_cols(count: int) -> int:
    """方塊分幾欄——三項以上排兩欄，單欄會把卡片拉得又長又窄。"""
    return 2 if count >= 3 else 1


def _card_lines(body: str) -> list[str]:
    return [s.strip() for s in body.split("；") if s.strip()]


def _cell_lines(text: str) -> list[str]:
    """表格儲存格以「；」分行（與卡片同語法）——勾記與註記分行才排得下窄欄。"""
    return [s.strip() for s in text.split("；")] if "；" in text else [text]


def card_widths(items: list[tuple[str, str]], *, boxed: bool = False) -> list[int]:
    """依內容分配並列卡片寬度。

    ⚠️ ⛔ 不一律等寬——各卡片項目長短差很多，等寬會讓長的那張折行、短的那張留
    一大片白。作法同操作手冊表格欄寬：先取各張「放得下所需」之寬度，剩餘寬度
    再按比例分回。
    """
    total = SLIDE_W - MARGIN * 2 - CARD_GAP * (len(items) - 1)
    need = []
    for head, body in items:
        lines = _card_lines(body)
        if boxed:
            # 方塊內分兩行：主標 14pt（約 0.50）、副標 11pt（約 0.40）
            inner = max([_text_width(x.partition("：")[0]) * 0.50 for x in lines]
                        + [_text_width(x.partition("：")[2]) * 0.43 for x in lines] + [0])
            cols = _card_cols(len(lines))
            w = max(_text_width(head) * HEAD_CHAR_W,
                    (inner + 0.6) * cols + 0.3 * (cols - 1))
        else:
            w = max([_text_width(head) * HEAD_CHAR_W]
                    + [_text_width(x) * BODY_CHAR_W for x in lines] + [0])
        need.append(Cm(w + CARD_PADDING))
    if (spare := total - sum(need)) < 0:
        return [int(n * total / sum(need)) for n in need]
    return [int(n + spare * n / sum(need)) for n in need]


def card_height(items: list[tuple[str, str]], widths: list[int], *, boxed: bool = False) -> int:
    """估算並列卡片所需高度（各張取所需最大者，卡片一律等高）。

    ⚠️ **標題與說明都會折行**，兩者都要算。⛔ 不可只數項目數——框會開得太矮，
    文字撐破框線（實際踩過兩次）。
    """
    need = 0
    for (head, body), width in zip(items, widths):
        inner = max(1.0, Emu(width).cm - CARD_PADDING)
        head_rows = max(1, ceil(_text_width(head) / (inner / HEAD_CHAR_W)))
        lines = _card_lines(body)
        if boxed:   # 方塊：兩行高＋間隙，依列數計
            body_rows = ceil(len(lines) / _card_cols(len(lines))) if lines else 0
            row_h = Cm(2.8)
        else:
            body_rows = sum(max(1, ceil(_text_width(x) / (inner / BODY_CHAR_W)))
                            for x in lines)
            row_h = Cm(0.68)
        need = max(need, Cm(0.5)                      # 上內距
                   + head_rows * Cm(0.72) + Cm(0.35)  # 標題與其後間距
                   + body_rows * row_h + Cm(0.4))     # 說明與下留白
    return max(Cm(4.6), int(need))


def _cards(slide, items: list[tuple[str, str]], top, height, *, boxed: bool = False) -> None:
    """並列卡片：2～4 項並陳，每張一個標題與一段說明。

    說明以「；」分項。`boxed`（md 圍籬寫 ```cards-block）時各項改畫成深色方塊、
    三項以上排兩欄，項目內以「：」分主標與副標——項目本身是作業或選項時，方塊
    比文字行更像「一個東西」；⛔ 說明性文字不用此式，整段話框起來反而難讀。
    """
    widths = card_widths(items, boxed=boxed)
    lefts, cursor = [], MARGIN
    for w in widths:
        lefts.append(int(cursor))
        cursor += w + CARD_GAP

    for i, (head, body) in enumerate(items):
        left, card_w = lefts[i], widths[i]
        card = slide.shapes.add_shape(5, left, int(top), card_w, int(height))
        card.fill.solid()
        card.fill.fore_color.rgb = _rgb("surface")
        card.line.color.rgb = _rgb("brand")
        card.line.width = Pt(1)
        card.shadow.inherit = False

        frame = card.text_frame
        frame.word_wrap = True
        frame.margin_left = frame.margin_right = Cm(0.6)
        frame.margin_top = Cm(0.5)
        frame.vertical_anchor = MSO_ANCHOR.TOP   # 卡片等高、內容多寡不一，一律頂端起排
        para = frame.paragraphs[0]
        para.alignment = PP_ALIGN.CENTER
        para.space_after = Pt(10)
        _add_runs(para, head, Pt(20), color="primary", bold=True)

        lines = _card_lines(body)
        if boxed:
            cols = _card_cols(len(lines))
            gap_x, gap_y = Cm(0.3), Cm(0.4)
            bw = int((card_w - Cm(1.2) - gap_x * (cols - 1)) / cols)
            bh = Cm(2.4)
            for n, text in enumerate(lines):
                r, c = divmod(n, cols)
                item = slide.shapes.add_shape(
                    5, int(left + Cm(0.6) + c * (bw + gap_x)),
                    int(top + Cm(1.75) + r * (bh + gap_y)), bw, int(bh))
                item.fill.solid()
                item.fill.fore_color.rgb = _rgb("primary")
                item.line.fill.background()
                item.shadow.inherit = False
                f2 = item.text_frame
                f2.word_wrap = True
                f2.margin_left = f2.margin_right = Cm(0.25)
                f2.margin_top = f2.margin_bottom = 0
                f2.vertical_anchor = MSO_ANCHOR.MIDDLE
                name, _, desc = text.partition("：")
                p2 = f2.paragraphs[0]
                p2.alignment = PP_ALIGN.CENTER
                _add_runs(p2, name.strip(), Pt(14), color="on_primary", bold=True)
                if desc.strip():
                    p3 = f2.add_paragraph()
                    p3.alignment = PP_ALIGN.CENTER
                    _add_runs(p3, desc.strip(), Pt(12), color="on_primary")
            continue
        # ⚠️ 靠左對齊：項目長短不一時置中會讓每行起點參差，掃讀不到編號那一欄
        for line in lines:
            p2 = frame.add_paragraph()
            p2.alignment = PP_ALIGN.LEFT
            p2.space_after = Pt(2)
            _add_runs(p2, line, Pt(15), color="body")


def _steps(slide, items: list[str], top, height) -> None:
    """編號步驟：大號碼配一行說明，直向排列。

    適合有先後但不涉狀態轉換的操作，與流程圖區隔——流程圖畫的是「東西的流動」。
    """
    row_h = int(height / len(items))
    for i, text in enumerate(items):
        y = int(top + i * row_h)
        dot = slide.shapes.add_shape(9, MARGIN, y, Cm(1.5), Cm(1.5))   # 9 = 橢圓
        dot.fill.solid()
        dot.fill.fore_color.rgb = _rgb("primary")
        dot.line.fill.background()
        dot.shadow.inherit = False
        frame = dot.text_frame
        frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        para = frame.paragraphs[0]
        para.alignment = PP_ALIGN.CENTER
        _add_runs(para, str(i + 1), Pt(18), color="on_primary", bold=True)

        box = _textbox(slide, MARGIN + Cm(2.1), y + Cm(0.1),
                       SLIDE_W - MARGIN * 2 - Cm(2.1), Cm(1.4))
        box.vertical_anchor = MSO_ANCHOR.MIDDLE
        _add_runs(box.paragraphs[0], text, Pt(19))


def _flow(slide, nodes: list[str], labels: list[str], top, height) -> None:
    """橫向流程圖：節點方塊與箭頭，以原生圖形繪製。

    ⛔ 不以外部繪圖工具產圖後貼入——圖片在投影機上會糊，且字型與全篇不一致；
    原生圖形可於 PowerPoint 內直接微調。

    節點以 `**節點名**` 標示者填深色，用於流程中段才是本模組的情形；未標示時
    循預設——首尾填深色，適合起點與終點即重點之流程。

    節點可寫成 `節點名｜副標`，副標以小一級字排在方塊內主標下方，用於名詞本身
    看不出意思、需一句話說明的情形（如狀態名配一句白話說明）。
    """
    heads, subs = [], []
    for raw in nodes:
        head, _, sub = raw.partition("｜")
        heads.append(head.strip())
        subs.append(sub.strip())

    # 節點間距：箭頭需伸展空間才看得出方向；⚠️ 並須容得下最長的箭頭標籤——
    # 標籤貼齊箭頭上緣（見下方），間距太窄時標籤會左右溢出、壓在節點方塊上
    gap = max(Cm(1.8), int(Cm(max((_text_width(x) for x in labels if x), default=0)
                              * 0.50 + 0.5)))
    total = SLIDE_W - MARGIN * 2
    box_w = int((total - gap * (len(nodes) - 1)) / len(nodes))
    box_h = min(height, Cm(3.4) if any(subs) else Cm(2.6))
    box_top = int(top + (height - box_h) / 2)

    marked = {i for i, t in enumerate(heads) if t.startswith("**") and t.endswith("**")}
    dark = marked or {0, len(nodes) - 1}

    for i, text in enumerate(heads):
        left = int(MARGIN + i * (box_w + gap))
        box = slide.shapes.add_shape(5, left, box_top, box_w, box_h)   # 5 = 圓角矩形
        box.fill.solid()
        box.fill.fore_color.rgb = _rgb("primary" if i in dark else "surface")
        box.line.color.rgb = _rgb("primary")
        box.line.width = Pt(1)
        box.shadow.inherit = False
        frame = box.text_frame
        frame.word_wrap = True
        frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        para = frame.paragraphs[0]
        para.alignment = PP_ALIGN.CENTER
        _add_runs(para, text.strip("*"), Pt(18),
                  color="on_primary" if i in dark else "text", bold=True)
        if subs[i]:
            para.space_after = Pt(6)
            p2 = frame.add_paragraph()
            p2.alignment = PP_ALIGN.CENTER
            _add_runs(p2, subs[i], Pt(14),
                      color="on_primary" if i in dark else "body")

        if i < len(nodes) - 1:
            # ⛔ 不用方塊箭頭：節點間距窄時會糊成一個橢圓，改以細線加三角端點
            y_mid = box_top + int(box_h / 2)
            conn = slide.shapes.add_connector(
                1, int(left + box_w + Cm(0.2)), int(y_mid),
                int(left + box_w + gap - Cm(0.2)), int(y_mid))
            conn.line.color.rgb = _rgb("primary")
            conn.line.width = Pt(2)
            tail = etree.SubElement(conn.line._get_or_add_ln(), qn("a:tailEnd"))
            tail.set("type", "triangle")
            if i < len(labels) and labels[i]:
                # 標籤貼齊箭頭上緣：離得遠會讀不出它在說明哪一段
                cap = _textbox(slide, left + box_w - Cm(1.2), int(y_mid - Cm(0.9)),
                               gap + Cm(2.4), Cm(0.8))
                cap.vertical_anchor = MSO_ANCHOR.BOTTOM
                p2 = cap.paragraphs[0]
                p2.alignment = PP_ALIGN.CENTER
                _add_runs(p2, labels[i], Pt(14), color="muted")


# ---- 各類投影片 ----------------------------------------------------------

def _cover(prs, module: str, subtitle: str, eyebrow_en: str, note: str = "",
           extra: dict | None = None) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    # 左側短色條：封面之視覺錨點，⛔ 不用插畫——各模組須各自備圖，且風格難以一致
    tick = slide.shapes.add_shape(1, MARGIN, Cm(5.3), Cm(0.5), Cm(4.4))
    tick.fill.solid()
    tick.fill.fore_color.rgb = _rgb("brand")
    tick.line.fill.background()
    tick.shadow.inherit = False

    _brand_bar(slide)

    text_w = SLIDE_W - MARGIN * 2

    frame = _textbox(slide, MARGIN + Cm(1.2), Cm(5.3), text_w - Cm(1.2), Cm(1.4))
    run = frame.paragraphs[0].add_run()
    run.text = eyebrow_en
    run.font.size = Pt(24)
    run.font.name = DECK_FONT_EN
    run.font.color.rgb = _rgb("primary")

    frame = _textbox(slide, MARGIN + Cm(1.2), Cm(6.6), text_w - Cm(1.2), Cm(3.0))
    _add_runs(frame.paragraphs[0], f"{module}｜{subtitle}", COVER_TITLE, bold=True)

    _rule(slide, Cm(11.0))

    # 案件資訊：欄位名以全形空格對齊，與院方既有簡報一致
    frame = _textbox(slide, MARGIN, Cm(11.7), text_w, Cm(5.1))
    extra = extra or {}
    rows = [f"案　　號　{PROJECT_CASE_NO}　{PROJECT_NAME}",
            f"系　　統　{SYSTEM_NAME}",
            f"主辦單位　{VENDOR}"]
    if extra.get("課程日期"):
        rows.append(f"課程日期　{extra['課程日期']}")
    if extra.get("講師"):
        rows.append(f"講　　師　{extra['講師']}")
    for i, text in enumerate(rows):
        para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        para.space_after = Pt(10)
        _add_runs(para, text, Pt(16), color="body")
    _notes(slide, note)


def _closing(prs, title: str, eyebrow_en: str, subtitle: str = "", note: str = "") -> None:
    """結語頁：沿用封面版式（左側色條、大字、底部色帶），⛔ 不加頁碼頁尾——
    與封面成對，是整份的開頭與結尾，不屬於內文編號。"""
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    tick = slide.shapes.add_shape(1, MARGIN, Cm(6.6), Cm(0.5), Cm(3.4))
    tick.fill.solid()
    tick.fill.fore_color.rgb = _rgb("brand")
    tick.line.fill.background()
    tick.shadow.inherit = False

    _brand_bar(slide)
    text_w = SLIDE_W - MARGIN * 2

    frame = _textbox(slide, MARGIN + Cm(1.2), Cm(6.6), text_w - Cm(1.2), Cm(1.4))
    run = frame.paragraphs[0].add_run()
    run.text = eyebrow_en
    run.font.size = Pt(24)
    run.font.name = DECK_FONT_EN
    run.font.color.rgb = _rgb("primary")

    frame = _textbox(slide, MARGIN + Cm(1.2), Cm(7.9), text_w - Cm(1.2), Cm(2.4))
    _add_runs(frame.paragraphs[0], title, COVER_TITLE, bold=True)

    if subtitle:
        _rule(slide, Cm(10.9))
        frame = _textbox(slide, MARGIN + Cm(1.2), Cm(11.4), text_w - Cm(1.2), Cm(1.4))
        _add_runs(frame.paragraphs[0], subtitle, Pt(18), color="body")
    _notes(slide, note)


def _section(prs, title: str, eyebrow: str, page: int, module: str, total: int,
             note: str = "") -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _brand_bar(slide)
    top = SLIDE_H * 0.36

    if eyebrow:
        frame = _textbox(slide, MARGIN, top - Cm(1.5), SLIDE_W - MARGIN * 2, Cm(1.2))
        run = frame.paragraphs[0].add_run()
        run.text = eyebrow
        run.font.size = Pt(20)
        run.font.name = DECK_FONT_EN
        run.font.color.rgb = _rgb("primary")

    frame = _textbox(slide, MARGIN, top, SLIDE_W - MARGIN * 2, Cm(2.4))
    _add_runs(frame.paragraphs[0], title, SECTION_SIZE, bold=True)
    _rule(slide, top + Cm(2.6), Cm(6))
    _footer(slide, module, page, total)
    _notes(slide, note)


def _agenda(prs, sections: list[str], module: str, page: int, total: int,
            note: str = "") -> None:
    """課程大綱：封面之後第一張，讓學員先知道今天走哪些段落。"""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _brand_bar(slide)
    _heading(slide, "Agenda", "課程大綱")
    frame = _textbox(slide, MARGIN, BODY_TOP + Cm(0.6),
                     SLIDE_W - MARGIN * 2, BODY_H - Cm(1.2))
    for i, name in enumerate(sections):
        para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        para.space_after = Pt(20)
        _add_runs(para, name, Pt(22))
    _footer(slide, module, page, total)
    _notes(slide, note)


def _content(prs, title: str, blocks: list, note: str, page: int, module: str,
             md_dir: Path, eyebrow: str, total: int) -> None:
    """內容頁：依各元素**實際所需高度**排版，一律自版面上緣起排。

    ⛔ 不以固定比例分配版面——條列只有一行時會留下大片空白，最末元素則被擠到
    頁尾之外。⛔ 亦不垂直置中——元素少時內容會飄在版面中央。
    """
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _brand_bar(slide)
    _heading(slide, eyebrow, title)

    ordered = [b for b in blocks if b[0] in ("bullet", "ordered", "flow", "callout",
                                             "table", "image", "cards", "steps")]
    bullets = [b for b in ordered if b[0] in ("bullet", "ordered")]
    cards = [(b[1], b[2]) for b in ordered if b[0] == "cards"]
    cards_boxed = any(b[0] == "cards" and len(b) > 3 and b[3] for b in ordered)
    steps = [b[1] for b in ordered if b[0] == "steps"]

    GAP = Cm(0.8)
    heights: list[int] = []
    for kind, *rest in ordered:
        if kind in ("bullet", "ordered"):
            heights.append(0 if bullets and (kind, *rest) != bullets[0]
                           else int(len(bullets) * Cm(1.35)))
        elif kind == "flow":
            # 節點帶副標時方塊較高（見 _flow），高度隨之加碼，否則副標會被壓掉
            heights.append(Cm(4.6) if any("｜" in n for n in rest[0]) else Cm(3.8))
        elif kind == "callout":
            heights.append(Cm(2.4))
        elif kind == "table":
            # ⚠️ 依各列實際行數計高——儲存格用「；」分行後，固定列高會被撐開而壓到頁尾
            heights.append(sum(int(max(len(_cell_lines(x)) for x in row) * Cm(0.68) + Cm(0.35))
                               for row in rest[0]))
        elif kind == "cards":
            # 卡片高度取最多行者，⛔ 不用固定值——清單型卡片行數差很多，固定值會截字
            heights.append(card_height(cards, card_widths(cards, boxed=cards_boxed), boxed=cards_boxed)
                           if (kind, *rest)[:3] == ("cards", *cards[0]) else 0)
        elif kind == "steps":
            heights.append(int(len(steps) * Cm(1.9))
                           if (kind, *rest) == ("steps", steps[0]) else 0)
        else:                                        # image
            heights.append(Cm(8.0))

    top = BODY_TOP
    # 整張只有並列卡片時：給一個下限高度並略微下移——⛔ 不置中（離標題太遠），
    # 下移量取置中之半，空白留在下方；其他頁一律靠上排，不適用本段
    if cards and all(k == "cards" for k, *_ in ordered):
        heights[0] = max(heights[0], Cm(8.0))
        top = BODY_TOP + max(0, int((FOOTER_TOP - BODY_TOP - heights[0]) / 4))

    width = SLIDE_W - MARGIN * 2
    done_bullets = False

    for (kind, *rest), height in zip(ordered, heights):
        if kind in ("bullet", "ordered"):
            if done_bullets:
                continue
            done_bullets = True
            frame = _textbox(slide, MARGIN, top, width, height)
            for i, (bkind, text) in enumerate(bullets):
                para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
                para.space_after = Pt(12)
                marker = f"{i + 1}. " if bkind == "ordered" else "●  "
                _add_runs(para, marker + text, BULLET_SIZE)
        elif kind == "flow":
            _flow(slide, rest[0], rest[1], top + Cm(0.5), height - Cm(0.5))
        elif kind == "callout":
            _callout(slide, rest[0], top, width)
        elif kind == "cards":
            if height:
                _cards(slide, cards, top, height, boxed=cards_boxed)
        elif kind == "steps":
            if height:
                _steps(slide, steps, top, height)
        elif kind == "table":
            rows = rest[0]
            shape = slide.shapes.add_table(len(rows), len(rows[0]), MARGIN, top,
                                           width, height)
            # 對齊規則：表頭一律置中；資料列之第一欄（列標籤）一律靠左，其餘欄
            # 內容都短（勾記、代碼、單詞）時置中——長句置中會使每行起點參差難讀
            centred = {c for c in range(1, len(rows[0]))
                       if all(max((_text_width(x) for x in _cell_lines(row[c])), default=0) <= 8.5
                              for row in rows)}
            for r, row in enumerate(rows):
                for c, cell_text in enumerate(row):
                    cell = shape.table.cell(r, c)
                    cell.text = ""
                    # ⚠️ 縮上下內距：列高卡在 PowerPoint 的最低值時，只調高度設定無效，
                    # 真正撐開列高的是儲存格內距（預設 0.13 公分，每列多佔 0.26）
                    cell.margin_top = cell.margin_bottom = Cm(0.04)
                    frame = cell.text_frame
                    for i, line in enumerate(_cell_lines(cell_text) or [""]):
                        para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
                        if r == 0 or c in centred:
                            para.alignment = PP_ALIGN.CENTER
                        _add_runs(para, line, TABLE_SIZE,
                                  color="on_primary" if r == 0 else "text", bold=(r == 0),
                                  strong_color=False)
        else:
            path = (md_dir / rest[1]).resolve()
            if not path.exists():
                raise SystemExit(f"截圖不存在：{rest[1]}（投影片「{title}」）")
            pic = slide.shapes.add_picture(str(path), MARGIN, top, height=height)
            if pic.width > width:
                slide.shapes._spTree.remove(pic._element)
                pic = slide.shapes.add_picture(str(path), MARGIN, top, width=width)
            pic.left = int((SLIDE_W - pic.width) / 2)
        top += height + (GAP if height else 0)

    _footer(slide, module, page, total)
    _notes(slide, note)


# ---- md 解析 -------------------------------------------------------------

def parse(md_path: Path) -> tuple[str, list, dict]:
    """回傳 (模組名, [("section", 章名) | ("slide", 標題, blocks, notes)])。"""
    lines = md_path.read_text(encoding="utf-8").splitlines()
    module, items = md_path.stem, []
    blocks, notes, title = [], {}, None
    table: list[list[str]] = []
    fence: str | None = None
    section: list | None = None          # 章節頁之備忘稿寄存處
    last_note: str | None = None         # 備忘稿續行之接續對象
    front: dict[str, str] = {}           # 封面與大綱頁之備忘稿

    def close_table():
        """表格一結束即收進 blocks，⛔ 不可留到 flush——留著會讓表格排到整張最後，
        與 md 上的先後對不起來（例如寫在流程圖之前的表格會被擠到圖下方）。"""
        nonlocal table
        if table:
            blocks.append(("table", [r for i, r in enumerate(table) if i != 1]))
            table = []

    def flush():
        nonlocal blocks, notes, title
        close_table()
        if title is not None:
            items.append(("slide", title, blocks, notes))
        blocks, notes, title = [], {}, None

    for line in lines:
        if table and fence is None and not TABLE_RE.match(line):
            close_table()
        if match := FENCE_RE.match(line.rstrip()):
            fence = match.group("kind") if fence is None else None
            continue
        if fence in ("cards", "cards-block", "steps") and line.strip() and title is not None:
            if fence in ("cards", "cards-block"):
                head, _, body = line.strip().partition("｜")
                # cards-block：說明各項改以深色方塊呈現（見 _cards 之 boxed）
                blocks.append(("cards", head.strip(), body.strip(), fence == "cards-block"))
            else:
                blocks.append(("steps", line.strip()))
            continue
        if fence == "flow" and line.strip() and title is not None:
            parts = ARROW_RE.split(line.strip())
            nodes = [x.strip() for x in parts[::2]]
            labels = [(x or "").strip() for x in parts[1::2]]   # 無標籤之箭頭回傳 None
            blocks.append(("flow", nodes, labels))
            continue
        if fence:
            continue
        if match := HEADING_RE.match(line):
            level, text = len(match.group("level")), match.group("text").strip()
            if level == 1:
                module = text.split("｜")[0].strip()
            elif level == 2:
                flush()
                section = ["section", text, {}]
                items.append(section)
            else:
                flush()
                title = text
                section = None
            last_note = None
            continue
        if title is None and section is None:
            if match := META_RE.match(line):
                front[match.group("key")] = match.group("value").strip()
                last_note = None
                continue
            if match := FRONT_RE.match(line):
                last_note = match.group("kind")
                front[last_note] = match.group("text").strip()
                continue
            if last_note in ("封面", "大綱") and line.startswith(">"):
                front[last_note] += "\n" + line.lstrip("> ").strip()
                continue
        if title is None:
            # 章節頁之備忘稿（同樣支援續行）
            if section is not None:
                if match := NOTE_RE.match(line):
                    last_note = match.group("kind")
                    section[2][last_note] = match.group("text").strip()
                elif last_note and line.startswith(">"):
                    section[2][last_note] += "\n" + line.lstrip("> ").strip()
                elif not line.strip():
                    pass                          # 空行不中斷續行
                else:
                    last_note = None
            continue
        if HIDE_RE.match(line):
            notes["隱藏"] = "1"
            last_note = None
        elif CLOSING_RE.match(line):
            notes["結語"] = "1"
            last_note = None
        elif match := CALLOUT_RE.match(line):
            blocks.append(("callout", match.group("text").strip()))
            last_note = None
        elif match := NOTE_RE.match(line):
            last_note = match.group("kind")
            notes[last_note] = match.group("text").strip()
        elif last_note and line.startswith(">"):
            # ⚠️ 備忘稿之續行：逐字稿常分段，少了這段只會吃進第一行
            notes[last_note] += "\n" + line.lstrip("> ").strip()
        elif match := IMAGE_RE.match(line.strip()):
            blocks.append(("image", match.group("alt"), match.group("src")))
        elif match := TABLE_RE.match(line):
            table.append([c.strip() for c in match.group(1).split("|")])
        elif match := LIST_RE.match(line):
            kind = "ordered" if match.group("bullet")[0].isdigit() else "bullet"
            blocks.append((kind, match.group("text").strip()))
    flush()
    return module, items, front


def _split(heading: str) -> tuple[str, str]:
    """章標題可寫成「中文章名｜English Eyebrow」，回傳 (章名, 英文小標)。"""
    if "｜" in heading:
        name, _, eyebrow = heading.partition("｜")
        return name.strip(), eyebrow.strip()
    return heading.strip(), ""


def build(md_path: Path, out_path: Path, notes_kind: str) -> None:
    module, items, front = parse(md_path)
    prs = Presentation()
    prs.slide_width, prs.slide_height = SLIDE_W, SLIDE_H

    total = len(items) + 2                       # 封面與大綱頁

    _cover(prs, module, TRAINING_DOC_NAME, front.get("英文名", "Training Course"),
           "" if notes_kind == "none" else front.get("封面", ""), front)
    sections = [_split(i[1])[0] for i in items if i[0] == "section"]
    _agenda(prs, sections, module, 2, total,
            "" if notes_kind == "none" else front.get("大綱", ""))

    page, slides, eyebrow = 2, 0, ""
    for item in items:
        page += 1
        if item[0] == "section":
            # 章標題之「｜」後為英文小標，該章各投影片共用
            name, eyebrow = _split(item[1])
            snote = "" if notes_kind == "none" else item[2].get(
                "講稿" if notes_kind == "full" else "提示", "")
            _section(prs, name, eyebrow, page, module, total, snote)
        else:
            _, title, blocks, notes = item
            note = "" if notes_kind == "none" else notes.get(
                "講稿" if notes_kind == "full" else "提示", "")
            if notes.get("結語"):
                sub = next((b[1] for b in blocks if b[0] == "callout"), "")
                _closing(prs, title, "Thank You", sub, note)
                page -= 1          # 結語頁不佔頁碼（與封面成對）
                continue
            _content(prs, title, blocks, note, page, module, md_path.parent,
                     eyebrow, total)
            if notes.get("隱藏"):
                prs.slides[-1]._element.set("show", "0")
            slides += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out_path))
    print(f"已產出：{out_path}（{len(prs.slides)} 張，其中內容 {slides} 張）")


def main() -> int:
    parser = argparse.ArgumentParser(description="教育訓練簡報產生器")
    parser.add_argument("source", type=Path, help="_training/ 下之教材 md")
    parser.add_argument("--notes", choices=("full", "brief", "none"), default="full",
                        help="備忘稿取哪一版：full 完整講稿（預設）、brief 重點提示、none 不帶備忘稿")
    parser.add_argument("-o", "--output", type=Path,
                        default=Path("docs/manuals/教育訓練"))
    args = parser.parse_args()

    # 一個模組一份簡報；備忘稿於 md 內兩版並存，產出時擇一，⛔ 不另出第二個檔
    build(args.source, args.output / f"{args.source.stem}.pptx", args.notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
