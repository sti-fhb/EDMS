---
description: Zod 表單驗證規範，開發前端時載入
paths:
  - "frontend/**/*.ts"
  - "frontend/**/*.tsx"
---

# Zod 表單驗證規範

## 核心原則

- 所有前端表單驗證**一律使用 Zod**，禁止手寫 `validate()` 函式
- Zod schema 命名與結構**對齊後端 Pydantic Model**
- 驗證錯誤訊息一律使用**繁體中文**

## 檔案位置

```
frontend/src/
├── {module}/
│   └── schemas/
│       └── {resource}Schema.ts    ← Zod schema 定義
├── utils/
│   └── zodUtils.ts                ← 共用工具（getFieldErrors）
└── types/
    └── {resource}.ts              ← API 回應型別（保留手寫 interface）
```

## 命名對齊規則

| 後端 Pydantic | 前端 Zod Schema | 推導型別 |
|---------------|----------------|---------|
| `RefCodeCreate` | `RefCodeCreateSchema` | `RefCodeCreateValues` |
| `RefCodeUpdate` | `RefCodeUpdateSchema` | `RefCodeUpdateValues` |
| `LoginRequest` | `LoginRequestSchema` | `LoginRequestValues` |

## Do & Don't

### Schema 定義

```typescript
// ✅ Do — 使用 Zod schema + z.infer 推導型別
// 注意：以下為精簡範例，完整實作見 dp/ref_codes/schemas/refCodeSchema.ts
import { z } from "zod"

export const RefCodeCreateSchema = z.object({
  category: z
    .string()
    .min(1, { message: "請輸入分類" })
    .max(100, { message: "分類長度不可超過 100 字元" })
    .regex(/^[a-zA-Z][a-zA-Z0-9_]*$/, {
      message: "僅允許英文、數字及底線，且須以英文開頭",
    }),
  label: z.string().min(1, { message: "請輸入顯示名稱" }),
  sort_order: z.number().int().min(0).default(0),
})

export type RefCodeCreateValues = z.infer<typeof RefCodeCreateSchema>

// ❌ Don't — 手寫 validate 函式
const validate = (): boolean => {
  const errors = {}
  if (!form.category.trim()) errors.category = "請輸入分類"
  // ...手動驗證每個欄位
  return Object.keys(errors).length === 0
}

// ❌ Don't — 手寫 interface 來定義表單值型別（應用 z.infer 推導）
interface RefCodeFormValues {
  category: string
  label: string
  sort_order: number
}

// ✅ 例外：若表單型別已被多個使用端共用，可暫時保留手寫 interface，
// 但應加 TODO 標記未來遷移至 z.infer 推導。
// TODO: 待所有使用端遷移後，改用 z.infer<typeof RefCodeCreateSchema>
interface RefCodeFormValues { ... }
```

### 表單中使用

```typescript
// ✅ Do — 使用 safeParse + getFieldErrors
import { getFieldErrors } from "@/utils/zodUtils"
import { RefCodeCreateSchema } from "./schemas/refCodeSchema"

const handleSubmit = () => {
  const result = RefCodeCreateSchema.safeParse({
    category: form.category.trim(),
    code: form.code.trim(),
    label: form.label.trim(),
    sort_order: parsedSortOrder,
  })
  const fieldErrors = getFieldErrors(result)
  setErrors(fieldErrors)
  if (!result.success) return

  onSave(result.data)
}

// ❌ Don't — 使用 parse（會拋例外）
try {
  const data = RefCodeCreateSchema.parse(formData)
} catch (e) { ... }
```

### Create vs Update Schema

```typescript
// ✅ Do — 當 Update 與 Create 欄位有差異時，分開定義
// RefCodeUpdate 不含 category/code（建立後不可變更），多了 is_active
export const RefCodeUpdateSchema = z.object({
  label: z.string().min(1, { message: "請輸入顯示名稱" }).optional(),
  sort_order: z.number().int().min(0).optional(),
  is_active: z.boolean().optional(),
})

// ✅ Do — 當 Update 只是全部變選填時，可用 .partial()
export const SimpleUpdateSchema = SimpleCreateSchema.partial()

// ⚠️ 注意：全選填 schema 會接受空物件 {}
// 若業務上「至少需要一個欄位」，加上 .refine() 檢查：
export const AtLeastOneFieldSchema = SimpleCreateSchema.partial().refine(
  (data) => Object.values(data).some((v) => v !== undefined),
  { message: "至少需要填寫一個欄位" },
)
```

### 錯誤訊息

```typescript
// ✅ Do — 每個驗證規則帶繁體中文訊息
z.string().min(1, { message: "請輸入分類" })
z.string().email({ message: "Email 格式不正確" })

// ❌ Don't — 使用英文或省略訊息
z.string().min(1)  // 會顯示英文預設訊息
z.string().email()
```

## 型別使用原則

| 用途 | 型別來源 | 說明 |
|------|---------|------|
| 表單值（送出前） | `z.infer<typeof Schema>` | 由 Zod 推導 |
| API 回應 | 手寫 `interface` | 保留在 `types/*.ts`，因為回應型別含 `id`、`created_at` 等 |
| API 請求 payload | `z.infer<typeof Schema>` 或手寫 | 視是否與表單值相同而定 |

## 共用工具

### `getFieldErrors(result)`

將 Zod `safeParse` 結果轉為 `Record<string, string>`，對應 MUI TextField 的 `error` + `helperText`：

```typescript
import { getFieldErrors } from "@/utils/zodUtils"

const result = schema.safeParse(data)
const errors = getFieldErrors(result)
// { category: "請輸入分類", code: "僅允許英文..." }
```

## 未來方向：自動生成

目前 Zod schema 手動對齊後端 Pydantic Model。未來可考慮：

1. **`openapi-zod-client`**：從 FastAPI 的 OpenAPI spec 自動生成 Zod schema
2. **`react-hook-form` + `@hookform/resolvers/zod`**：當表單複雜度提升時，導入表單狀態管理庫，搭配 Zod resolver 自動處理驗證與錯誤顯示

這些方向在專案規模擴大、表單數量增多時再評估導入時機。
