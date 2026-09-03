"""文件庫檢索效能守門（T067 / SC-001，真實 DB）。

SC-001：文件庫檢索（多條件 + 標籤 AND + 分頁）回應時間 P95 ≤ 2 秒。

**定位**：smoke 級效能守門，非負載測試——以代表性資料量（數百筆已發布文件 + 標籤）跑數種檢索並斷言
單次 < 2 秒，防「N+1 爆量 / 缺索引」等粗顆粒回歸使檢索遠超門檻。CI runner 效能有變異，故用 SC-001
之 2 秒硬門檻（正常應為毫秒級、裕度極大、不 flaky）；真實 P95 負載量測由部署前壓測環境另行執行。
"""

import time

import pytest
from sqlalchemy import select

from app.core.utils import utcnow
from app.dm.catalog.models import DmTag
from app.dm.deps import DmContext
from app.dm.document.models import DmDocTag, DmDocument, DmDocVersion
from app.dm.library.schemas import DocumentQuery
from app.dm.library.service import LibraryService
from app.dm.roles.authz import DM_EDITOR

pytestmark = pytest.mark.integration

_library = LibraryService()
_N = 300  # 代表性文件量
_SLA_SECONDS = 2.0  # SC-001
_ADMIN_CTX = DmContext(user_id="perf_ed", roles=frozenset({DM_EDITOR}))  # 編輯者不受可見性過濾


async def _seed_bulk(db, nature_tag_id: int, all_aud_id: int):
    """批次種 _N 筆已發布文件（含當前版本 + 全體可見對象 + 一檢索標籤），單次 flush。"""
    now = utcnow()
    docs, versions, tags = [], [], []
    for i in range(_N):
        doc_id = f"DM-SOP-9{i:05d}"
        docs.append(
            DmDocument(
                doc_id=doc_id,
                doc_name=f"效能測試文件{i:05d}",
                category_code="SOP",
                status="PUBLISHED",
                created_user="perf_ed",
                created_date=now,
            )
        )
    db.add_all(docs)
    await db.flush()
    for i in range(_N):
        doc_id = f"DM-SOP-9{i:05d}"
        versions.append(
            DmDocVersion(
                doc_id=doc_id,
                version_no="1.0",
                change_summary="摘要",
                file_name="f.pdf",
                file_path=f"/x/{doc_id}.pdf",
                file_size=100,
                file_mime="application/pdf",
                status="PUBLISHED",
                published_date=now,
                created_user="perf_ed",
                created_date=now,
            )
        )
        tags.append(DmDocTag(doc_id=doc_id, tag_id=all_aud_id, created_user="perf_ed", created_date=now))
        tags.append(DmDocTag(doc_id=doc_id, tag_id=nature_tag_id, created_user="perf_ed", created_date=now))
    db.add_all(versions)
    await db.flush()
    # 指標指向各自當前版本
    rows = (await db.execute(select(DmDocVersion.doc_id, DmDocVersion.version_id))).all()
    ver_by_doc = {d: v for d, v in rows}
    for doc in docs:
        doc.current_version_id = ver_by_doc[doc.doc_id]
    db.add_all(tags)
    await db.flush()


async def _timed_search(db, query: DocumentQuery, *, page=1, limit=20) -> float:
    start = time.perf_counter()
    await _library.search(db, query=query, ctx=_ADMIN_CTX, page=page, limit=limit)
    return time.perf_counter() - start


async def test_library_search_within_sla(db):
    """代表性資料量下，多種檢索（關鍵字 / 分類 / 標籤 AND / 分頁）單次皆 < 2 秒（SC-001）。"""
    all_aud = await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "AUDIENCE", DmTag.tag_name == "全體"))
    nature = DmTag(tag_group_code="NATURE", tag_name="效能標籤", created_user="seed", created_date=utcnow())
    db.add(nature)
    await db.flush()
    await _seed_bulk(db, nature.tag_id, all_aud)

    scenarios = {
        "keyword": DocumentQuery(keyword="效能測試"),
        "category": DocumentQuery(category="SOP"),
        "tag_and": DocumentQuery(tag_ids=[nature.tag_id]),
        "combined": DocumentQuery(keyword="文件", category="SOP", tag_ids=[nature.tag_id]),
    }
    for label, q in scenarios.items():
        elapsed = await _timed_search(db, q)
        assert elapsed < _SLA_SECONDS, f"檢索[{label}] 耗時 {elapsed:.3f}s 超過 SC-001 門檻 {_SLA_SECONDS}s"

    # 分頁末頁亦須在門檻內
    last_page = (_N + 19) // 20
    elapsed = await _timed_search(db, DocumentQuery(category="SOP"), page=last_page, limit=20)
    assert elapsed < _SLA_SECONDS, f"末頁檢索耗時 {elapsed:.3f}s 超過門檻"
