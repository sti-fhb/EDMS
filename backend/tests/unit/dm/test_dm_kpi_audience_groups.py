"""DM06 逐可見對象組之閱讀完成度（#567 A）。

KPI 原本只給一份文件的彙總應看／已看，管理者看到「25%」無從得知是哪一組沒看。本模組測
`_audience_breakdown`：單趟掃出「去重後的應看集」與「逐組統計」。

## 為什麼逐組加總會大於文件總計

一位閱覽者可能同時符合同一份文件的多組可見對象（例如身兼護理師與醫檢師，而文件兩組都掛）。
裁示（2026-10-07）為**各組獨立計算完成度、文件總計去重**——「這一組的完成度」對兩組而言該員
都確實是應讀者。代價是兩個數字對不起來，畫面必須標註。

本檔的 `test_一人符合兩組_各組分母都含他而總計去重` 就是釘住這條裁示；它若被改成「加總等於
總計」，代表有人把裁示翻過來了，請回頭確認而不是改測試。

## `_pair_visible` 的重構守門

為了讓「總計」與「逐組」共用一次掃描，`_pair_visible` 被拆成 `_single_pair_visible` +
`any(...)`。該函式的 docstring 明訂其語意須與 SQL 版 `visibility.audience_pair_match`
**完全一致**，故此處另有一組測試逐案釘住拆分前後的等價性。
"""

import pytest

from app.dm.kpi.service import _audience_breakdown, _pair_visible, _single_pair_visible

pytestmark = pytest.mark.unit

# 職位（AUDIENCE）與單位（UNIT）標籤 id；None 代表通用值（文件側「全體」/「全單位」已由
# repository.doc_audience 正規化為 None）
_NURSE = 1
_TECH = 2
_SONGSHAN = 10
_NEIHU = 11

_L_NURSE = "國防醫學院三軍總醫院松山分院．護理師"
_L_TECH = "國防醫學院三軍總醫院松山分院．醫檢師"


# ── 拆分等價性（重構守門）────────────────────────────────


@pytest.mark.parametrize(
    ("du", "dp", "user_pairs", "expected"),
    [
        # 文件全系統可見：不需任何授權
        (None, None, set(), True),
        (None, None, {(None, _NURSE)}, True),
        # 文件只限職位（全單位）：比對職位
        (None, _NURSE, {(None, _NURSE)}, True),
        (None, _NURSE, {(_SONGSHAN, _NURSE)}, True),
        (None, _NURSE, {(None, _TECH)}, False),
        (None, _NURSE, set(), False),
        # 文件指定單位 + 職位：兩邊都要中
        (_SONGSHAN, _NURSE, {(_SONGSHAN, _NURSE)}, True),
        (_SONGSHAN, _NURSE, {(_NEIHU, _NURSE)}, False),
        (_SONGSHAN, _NURSE, {(_SONGSHAN, _TECH)}, False),
        # 人側單位未指定（#437 之前的舊授權）：`du == uu` 恆 False，只能中 du is None
        (_SONGSHAN, _NURSE, {(None, _NURSE)}, False),
        # 文件指定單位但職位通用
        (_SONGSHAN, None, {(_SONGSHAN, _TECH)}, True),
        (_SONGSHAN, None, {(_NEIHU, _TECH)}, False),
    ],
)
def test_單一配對判定逐案(du, dp, user_pairs, expected):
    assert _single_pair_visible(du, dp, user_pairs) is expected


def test_pair_visible_等於任一配對命中():
    """拆分後 `_pair_visible` 必須仍是「任一組命中即可見」。"""
    user = {(None, _TECH)}
    # 單看第一組不可見、第二組可見 → 整體可見
    assert _single_pair_visible(None, _NURSE, user) is False
    assert _single_pair_visible(None, _TECH, user) is True
    assert _pair_visible({(None, _NURSE): _L_NURSE, (None, _TECH): _L_TECH}, user) is True
    # 兩組都不中 → 不可見
    assert _pair_visible({(None, _NURSE): _L_NURSE}, user) is False


def test_pair_visible_無可見對象之文件對任何人都不可見():
    """文件沒掛任何配對 → 迴圈不執行 → False（AC3a 應看=0 的來源）。"""
    assert _pair_visible({}, {(None, _NURSE)}) is False


# ── 逐組統計 ──────────────────────────────────────────


def test_一人符合兩組_各組分母都含他而總計去重():
    """⚠️ 本條釘住 2026-10-07 裁示，改動前請回讀本檔 docstring。"""
    doc_pairs = {(None, _NURSE): _L_NURSE, (None, _TECH): _L_TECH}
    viewer_tags = {
        "both": {(None, _NURSE), (None, _TECH)},  # 身兼兩職
        "nurse_only": {(None, _NURSE)},
        "tech_only": {(None, _TECH)},
    }
    members, groups = _audience_breakdown(
        doc_pairs, viewer_ids=set(viewer_tags), viewer_tags=viewer_tags, readers=set()
    )

    assert members == {"both", "nurse_only", "tech_only"}  # 去重後 3 人
    by_label = {g.label: g for g in groups}
    assert by_label[_L_NURSE].should_see == 2  # both + nurse_only
    assert by_label[_L_TECH].should_see == 2  # both + tech_only
    # 逐組加總 4 > 去重總計 3 —— 這是刻意的，不是錯誤
    assert sum(g.should_see for g in groups) > len(members)


def test_已看只計該組成員():
    doc_pairs = {(None, _NURSE): _L_NURSE, (None, _TECH): _L_TECH}
    viewer_tags = {"n1": {(None, _NURSE)}, "n2": {(None, _NURSE)}, "t1": {(None, _TECH)}}
    # t1 讀了，但他不是護理師組的人 → 護理師組已看應為 0
    members, groups = _audience_breakdown(
        doc_pairs, viewer_ids=set(viewer_tags), viewer_tags=viewer_tags, readers={"t1"}
    )
    by_label = {g.label: g for g in groups}
    assert (by_label[_L_NURSE].seen, by_label[_L_NURSE].unseen) == (0, 2)
    assert (by_label[_L_TECH].seen, by_label[_L_TECH].unseen) == (1, 0)
    assert by_label[_L_NURSE].rate == 0.0
    assert by_label[_L_TECH].rate == 1.0
    assert members == {"n1", "n2", "t1"}


def test_某組無對應閱覽者_該組閱讀率為_None():
    """單組版的 AC3a：文件掛了某組但沒人被授予 → 該組 rate None，不是 0。"""
    doc_pairs = {(None, _NURSE): _L_NURSE, (None, _TECH): _L_TECH}
    viewer_tags = {"n1": {(None, _NURSE)}}
    _, groups = _audience_breakdown(doc_pairs, viewer_ids={"n1"}, viewer_tags=viewer_tags, readers=set())
    by_label = {g.label: g for g in groups}
    assert by_label[_L_TECH].should_see == 0
    assert by_label[_L_TECH].rate is None  # 0 人不是 0%
    assert by_label[_L_NURSE].rate == 0.0  # 有人但沒看才是 0%


def test_全體文件_所有閱覽者入同一組():
    doc_pairs = {(None, None): "全體"}
    viewer_tags = {"a": {(None, _NURSE)}, "b": set()}  # b 完全沒授權也算
    members, groups = _audience_breakdown(doc_pairs, viewer_ids={"a", "b"}, viewer_tags=viewer_tags, readers={"a"})
    assert members == {"a", "b"}
    assert len(groups) == 1
    assert (groups[0].label, groups[0].should_see, groups[0].seen) == ("全體", 2, 1)


def test_無可見對象之文件_無組且無應看():
    """TRAINING 之外，AC3a 的另一種 0：文件沒掛配對。"""
    members, groups = _audience_breakdown({}, viewer_ids={"a"}, viewer_tags={"a": {(None, _NURSE)}}, readers=set())
    assert members == set()
    assert groups == []


def test_組別依名稱排序_輸出穩定():
    """避免同一份資料兩次請求給出不同順序（分頁與畫面對照會錯亂）。"""
    doc_pairs = {(None, _TECH): _L_TECH, (None, _NURSE): _L_NURSE, (None, None): "全體"}
    _, groups = _audience_breakdown(doc_pairs, viewer_ids=set(), viewer_tags={}, readers=set())
    labels = [g.label for g in groups]
    assert labels == sorted(labels)
