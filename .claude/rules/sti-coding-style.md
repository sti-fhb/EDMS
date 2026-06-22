---
description: 程式碼風格規範，開發前後端時載入
paths:
  - "backend/**/*.py"
  - "frontend/**/*.ts"
  - "frontend/**/*.tsx"
---

# 程式碼風格

## 通用規則

- 一律建立新物件，絕不直接修改（Immutability）
- 函式簡短（< 50 行）、檔案職責單一（< 800 行）
- 依功能/領域組織，不依型別組織
- 無深層巢狀（不超過 4 層）
- 無 `console.log`
- 一律完整處理錯誤（catch 內提取訊息後拋出或通知使用者）

## 輸入驗證

- 前端表單一律使用 Zod，詳見 `sti-zod-conventions.md`
- 後端一律用 Pydantic Schema 驗證，不在 route handler 手動驗證

## 註解規範

- 所有註解、docstring 一律使用**繁體中文**
- **必須寫**：複雜業務邏輯、非直覺演算法、繞過框架預設、模組邊界限制、`TODO(#issue)`
- **不必寫**：命名已清楚的標準 CRUD、型別本身已說明用途的欄位
- 後端 Service / Repository 公開方法必須加 docstring（含 Args / Returns / Raises）
- 前端行內說明非直覺行為即可，不需 JSDoc

## 程式碼品質 Checklist

標記任務完成前逐項確認：
- [ ] 命名清楚、函式簡短（< 50 行）、無深層巢狀
- [ ] 有適當錯誤處理
- [ ] 複雜邏輯已加繁體中文註解
- [ ] 後端公開方法已加 docstring
- [ ] 無 `console.log`、無硬編碼機密、無直接修改物件

## 安全

### 禁硬編碼機密

API 金鑰、密碼、JWT secret、DB 連線字串一律透過設定讀取：

- 後端：`app/core/config.py`
- 前端：`import.meta.env.VITE_*`

### SQL 一律參數化

- 優先走 SQLAlchemy ORM
- 必要的 raw SQL 用 `sa.text("... :param ...").bindparams(...)`
- 禁 f-string / 字串拼接組 SQL
- Alembic seed 另見 `sti-alembic-rules.md`

### 前端 XSS

- 禁 `dangerouslySetInnerHTML`
- 注入 HTML 須先 `DOMPurify.sanitize()`
