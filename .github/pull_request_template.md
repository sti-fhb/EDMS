## 對應 Issue

<!-- 填入對應的 Issue 編號，例如 Closes #123 -->
<!-- 若無對應 Issue 可刪除此段 -->
Closes #

## 變更說明

<!-- 簡述這個 PR 做了什麼 -->

## 變更類型

- [ ] feat（新功能）
- [ ] fix（Bug 修復）
- [ ] refactor（重構）
- [ ] docs（文件）
- [ ] test（測試）
- [ ] chore（雜項）
- [ ] perf（效能優化）
- [ ] ci（CI/CD）

## PR Checklist

- [ ] 未直接 import 其他模組的 Repository 或 Model（跨模組只走 `services/__init__.py`）
- [ ] 未在 SQL 中跨模組 JOIN 其他模組的 table
- [ ] 若新增對外 Service，已更新 `services/__init__.py` 與 `__all__`
- [ ] 錯誤處理使用 `AppError` + `error_code`（查 `docs/ref/error-codes.md`），不是自訂例外
- [ ] 刪除操作使用軟刪除（`DELETED = 1`），非硬刪除
- [ ] API Response 格式符合規範（列表 `data` + `meta`；錯誤 `error_code` + `error_message`）
- [ ] 若新增 Table/Model，欄位遵守共用欄位規範（見 `sti-backend-modules.md`；EDMS 單一組織、無 SITE 欄位）
- [ ] 有對應的 Unit Test（`tests/unit/`，標記 `pytest.mark.unit`）
- [ ] 已通過 TypeScript type-check（`pnpm type-check`；前端 task 適用）
- [ ] Ruff / ESLint 無錯誤
- [ ] 無 `console.log` / `print` 殘留
- [ ] 已執行 Code Review（Claude Code reviewer 或人工審查）

## Alembic Migration（若有改 `backend/alembic/versions/` 才適用）

<!-- 沒動 backend/alembic/versions/ 可刪除此區塊 -->

- [ ] 只有單一 Alembic head（`uv run alembic heads`）
- [ ] 若含 NOT NULL / UNIQUE / rename，已依 `sti-alembic-rules.md` 分步驟處理
- [ ] 大表 DDL 已評估鎖表風險
