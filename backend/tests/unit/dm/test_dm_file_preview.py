"""檔案預覽判定單元測試（純函式）。"""

from app.dm.document.file_store import is_previewable


def test_pdf_and_images_previewable():
    assert is_previewable("application/pdf") is True
    assert is_previewable("image/png") is True
    assert is_previewable("image/jpeg") is True


def test_office_not_previewable():
    assert is_previewable("application/vnd.openxmlformats-officedocument.wordprocessingml.document") is False
    assert is_previewable("application/vnd.ms-excel") is False


def test_case_insensitive():
    assert is_previewable("APPLICATION/PDF") is True
