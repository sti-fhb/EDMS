"""DOC_ID 格式產生單元測試（純函式，不需 DB）。"""

from app.dm.document.docid import format_doc_id


def test_format_doc_id_zero_padded():
    assert format_doc_id("SOP", 1) == "DM-SOP-000001"
    assert format_doc_id("MANUAL", 123) == "DM-MANUAL-000123"
    assert format_doc_id("TRAINING", 999999) == "DM-TRAINING-999999"


def test_format_doc_id_category_independent_prefix():
    # 不同分類各自命名空間（流水號獨立由 next_doc_id 保證，格式僅嵌分類碼）
    assert format_doc_id("SOP", 5).startswith("DM-SOP-")
    assert format_doc_id("OTHER", 5).startswith("DM-OTHER-")
