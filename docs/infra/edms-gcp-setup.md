# EDMS 的 GCP 前置設定

> **給誰看**：具 `blood-system-dev` 專案管理權限的維運人員。EDMS 的開發者沒有該專案的權限，故此文件供代為執行。
>
> **做完之後**：把 §2 最後產出的兩個值回報給 EDMS 開發者，由其填入 GitHub repo variables。
>
> 整體部署架構見 [deployment.md](deployment.md)。

---

## 0. 為什麼需要這些

EDMS 是 **public repository**，因此 CI/CD 全在 GitHub-hosted runner 執行，**不使用 self-hosted runner**（fork PR 會在 runner 上執行任意程式碼，而該 runner 所在的 bms-prod-02 同時跑著 TBMS 血庫系統）。

部署採 **pull-based**：GitHub 只 build 與 push 映像，bms-prod-02 上的 systemd timer 主動拉取。GitHub 側**不取得該 VM 的任何存取權**——部署必需的 docker 權限等同 root，讓 public repo 的 CD 身分持有它並不妥當。

所以需要三樣東西：**放映像的地方**、**GitHub 推映像用的身分**、**放備份的地方**。

> ✅ **本文件的操作全部是「新建資源」，不會動到 TBMS 或任何現有服務，不需要停機窗口。**
> 唯二觸及既有事物的是 §1.2 與 §3.1——替 bms-prod-02 既有的 Service Account 新增兩項讀寫權限（只增不減）。

---

## 0.1 執行環境與權限

| 項目 | 說明 |
|------|------|
| **在哪執行** | 你自己的機器，或 GCP Cloud Shell。**不是** bms-prod-02 |
| **要不要 `sudo`** | **不用**。本文件所有指令都是 `gcloud`／`cat`，用的是 GCP 身分而非 Linux 權限 |
| **需要的權限** | GCP IAM 角色：Artifact Registry Admin、IAM Workload Identity Pool Admin、Service Account Admin、Storage Admin |

> ⚠️ **不要 SSH 進 bms-prod-02 執行這些指令。** 那台機器上的 gcloud 是以 VM 的 Service Account 認證，該帳號**沒有**上述 admin 角色——指令會失敗，而錯誤訊息容易被誤讀成「權限給得不夠」而去替 VM 多開權限。VM 只需要 §1.2 與 §3.1 授予它的兩項讀寫權，不需要任何 admin 角色。
>
> bms-prod-02 上要做的事是另一份文件的 §2.4（clone repo、`.env.prod`、systemd units），**那些才需要 `sudo`**。

執行前先確認身分與專案：

```bash
gcloud auth list                      # 應為具上述角色的個人帳號，非 compute service account
gcloud config get-value project       # 應為 blood-system-dev；不是的話用下方 --project 覆寫即可
```

---

## 0.2 共用變數

**這是 shell 變數，只在「同一個終端機 session」內有效，不需要也不會存成檔案。**

```bash
# 以下所有指令共用的變數
export PROJECT_ID=blood-system-dev
export PROJECT_NUM=398001699233
export REGION=asia-east1
export VM_SA=398001699233-compute@developer.gserviceaccount.com   # bms-prod-02 的 Service Account

# ⚠️ GCS bucket 名稱是**全球唯一**的，可能已被其他組織註冊。
#    若 §3 建立時回報 409／already exists，改用帶專案前綴的名稱再重跑一次，
#    並記得把最終名稱回報給開發者（見 §2.4）。
export BUCKET=gs://edms-db-backup
```

⚠️ **換分頁、重開終端機、或 Cloud Shell 閒置斷線後，這些變數就沒了。** 屆時後續指令會帶著空值執行，錯誤訊息不會直說「變數沒設」（例如 `--member="serviceAccount:"` 只會回一個看不出原因的格式錯誤）。**每次重新開始前先回來重跑這一段。**

每個章節開跑前先驗一次，缺任何一個就會直接停下：

```bash
: "${PROJECT_ID:?未設定}" "${PROJECT_NUM:?未設定}" "${REGION:?未設定}" "${VM_SA:?未設定}" "${BUCKET:?未設定}" && echo "✅ 變數齊備：${PROJECT_ID} / ${REGION} / ${BUCKET}"
```

若要分多次執行，可存成檔案再 `source`（這四個值都不是機密，但**請放在 repo 之外**）：

```bash
cat > ~/edms-setup.env << 'EOF'
export PROJECT_ID=blood-system-dev
export PROJECT_NUM=398001699233
export REGION=asia-east1
export VM_SA=398001699233-compute@developer.gserviceaccount.com
export BUCKET=gs://edms-db-backup
EOF

source ~/edms-setup.env    # 每個新 session 執行一次
```

---

## 0.3 啟用所需 API

專案已在用 Artifact Registry（TBMS），但 WIF 相關 API 未必啟用過。先跑一次，已啟用者不會有副作用：

```bash
gcloud services enable artifactregistry.googleapis.com iamcredentials.googleapis.com sts.googleapis.com --project="${PROJECT_ID}"
```

> **資源已存在時的處理**：本文件的 `create` 指令若回報 `ALREADY_EXISTS`，代表該資源已在（例如專案內已有給其他 repo 用的 `github-pool`）。**這不是錯誤**——跳過該步、沿用既有資源即可，但要記得後續指令與 §2.4 的回報值要改用實際名稱。

---

## 1. Artifact Registry

```bash
gcloud artifacts repositories create edms-image \
  --repository-format=docker \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --description="EDMS container images"
```

### 1.1 Cleanup policy（**建立當天就設**）

TBMS 曾因未設而累積 1,456 個無 tag 映像、約 8.8 GB。

```bash
cat > /tmp/edms-cleanup-policy.json << 'EOF'
[
  {
    "name": "delete-untagged-older-than-30d",
    "action": { "type": "Delete" },
    "condition": {
      "tagState": "UNTAGGED",
      "olderThan": "2592000s"
    }
  }
]
EOF

gcloud artifacts repositories set-cleanup-policies edms-image \
  --location="${REGION}" --project="${PROJECT_ID}" \
  --policy=/tmp/edms-cleanup-policy.json --no-dry-run
```

只刪「無 tag 且超過 30 天」的映像；有 tag 者永不刪，等於保留 30 天歷史版本供回滾。

### 1.2 VM 的讀取權限（容易漏）

部署是 VM 主動 pull，所以 **bms-prod-02 的 Service Account 需要讀取權**，且部署腳本會用 `gcloud artifacts docker images describe` 確認映像是否就緒——同樣需要這個角色。

```bash
gcloud artifacts repositories add-iam-policy-binding edms-image \
  --location="${REGION}" --project="${PROJECT_ID}" \
  --member="serviceAccount:${VM_SA}" \
  --role=roles/artifactregistry.reader
```

---

## 2. Workload Identity Federation

**不建立 service account 金鑰**——public repo 內不得存放任何長期憑證。

### 2.1 專用 Service Account

```bash
gcloud iam service-accounts create edms-build \
  --project="${PROJECT_ID}" \
  --display-name="EDMS CI build & push"
```

權限**只給 `edms-image` 這一個 repository 的 writer**，不是整個專案，也不得涉及 compute、storage 或任何 TBMS 資源：

```bash
gcloud artifacts repositories add-iam-policy-binding edms-image \
  --location="${REGION}" --project="${PROJECT_ID}" \
  --member="serviceAccount:edms-build@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role=roles/artifactregistry.writer
```

### 2.2 Workload Identity Pool 與 Provider

```bash
gcloud iam workload-identity-pools create github-pool \
  --project="${PROJECT_ID}" --location=global \
  --display-name="GitHub Actions"
```

> 若專案內已有給其他 repo 用的 pool，沿用即可，只需新增下方的 provider。

```bash
gcloud iam workload-identity-pools providers create-oidc github-edms \
  --project="${PROJECT_ID}" --location=global \
  --workload-identity-pool=github-pool \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --attribute-condition="assertion.repository=='sti-fhb/EDMS' && assertion.ref=='refs/heads/main'"
```

> 🔴 **`--attribute-condition` 是這整份設定最關鍵的一行。**
> 它把可換取憑證的範圍鎖到「`sti-fhb/EDMS` 的 `refs/heads/main`」。
> **只綁 repository 而不綁 ref 是不夠的**——那會讓任何分支、包含外部 fork 送 PR 時產生的 ref，都能取得這個身分。EDMS 是 public repo，任何人都能開 fork PR。

### 2.3 允許該身分冒充 SA

```bash
gcloud iam service-accounts add-iam-policy-binding \
  "edms-build@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project="${PROJECT_ID}" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUM}/locations/global/workloadIdentityPools/github-pool/attribute.repository/sti-fhb/EDMS"
```

ref 的限制已由 §2.2 的 attribute condition 把關，故此處以 repository 為範圍即可。

### 2.4 回報這三個值

**全部做完後**（含 §3 的 bucket）執行以下指令，把輸出整段回報給 EDMS 開發者。用指令產生而非照抄，可避免沿用既有 pool／改用替代 bucket 名稱時抄錯：

```bash
echo "GCP_WORKLOAD_IDENTITY_PROVIDER = $(gcloud iam workload-identity-pools providers describe github-edms --project="${PROJECT_ID}" --location=global --workload-identity-pool=github-pool --format='value(name)')"
echo "GCP_BUILD_SERVICE_ACCOUNT      = edms-build@${PROJECT_ID}.iam.gserviceaccount.com"
echo "EDMS_BACKUP_BUCKET             = ${BUCKET}"
```

| 值 | 去向 |
|---|---|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | GitHub repo variables |
| `GCP_BUILD_SERVICE_ACCOUNT` | GitHub repo variables |
| `EDMS_BACKUP_BUCKET` | bms-prod-02 的 `/opt/edms/.env.prod` |

前兩者填入 **GitHub repo variables**（Settings → Secrets and variables → Actions → **Variables**，不是 Secrets）——它們不是機密。

---

## 3. GCS 備份 bucket

> ⚠️ **bucket 名稱是全球唯一的**，`edms-db-backup` 可能已被其他組織註冊。建立失敗（409 / already exists 且不屬於本專案）時，改用帶專案前綴的名稱：
>
> ```bash
> export BUCKET=gs://blood-system-dev-edms-db-backup
> ```
>
> **最終採用的名稱務必回報給開發者**（見 §2.4）——它要填進 VM 的 `/opt/edms/.env.prod` 的 `EDMS_BACKUP_BUCKET`，填錯部署會直接失敗。

```bash
gcloud storage buckets create "${BUCKET}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --uniform-bucket-level-access
```

### 3.1 VM 的寫入權限

備份由 bms-prod-02 上的腳本執行（migration 前備份、每日備份）：

```bash
gcloud storage buckets add-iam-policy-binding "${BUCKET}" \
  --member="serviceAccount:${VM_SA}" \
  --role=roles/storage.objectAdmin
```

### 3.2 Lifecycle

```bash
cat > /tmp/edms-bucket-lifecycle.json << 'EOF'
{
  "lifecycle": {
    "rule": [
      { "action": {"type": "Delete"},
        "condition": {"age": 31, "matchesPrefix": ["daily/"]} },
      { "action": {"type": "Delete"},
        "condition": {"age": 31, "matchesPrefix": ["pre-migrate/"]} },
      { "action": {"type": "Delete"},
        "condition": {"age": 365, "matchesPrefix": ["monthly/"]} }
    ]
  }
}
EOF

gcloud storage buckets update "${BUCKET}" --lifecycle-file=/tmp/edms-bucket-lifecycle.json
```

### 3.3 Retention（選用）

設定保留期後，期限內任何權限都無法刪除或覆寫物件，可防止 VM 遭入侵時備份被一併銷毀：

```bash
gcloud storage buckets update "${BUCKET}" --retention-period=30d
```

> ⚠️ 另有 `--lock-retention-period`，會讓保留期**永久無法縮短或移除**，屬**不可逆**操作。
> TBMS 的備份 bucket 依其 `scripts/db-backup.sh` 註解記載為「已設 30 天 retention 鎖」，但本文件未實地查證其為 `retention-period` 或已 `lock`。**EDMS 是否比照、是否鎖定，請依貴方政策自行判斷**——未鎖定時保留期一樣生效，只是日後可調整。

保留期 30 天與 §3.2 的 31 天刪除規則相容——物件滿 31 天才被 lifecycle 刪除，此時保留期已過。

---

## 4. 驗收

```bash
# 映像庫存在且 cleanup policy 已套用
gcloud artifacts repositories describe edms-image --location="${REGION}" \
  --project="${PROJECT_ID}" --format="yaml(cleanupPolicies, cleanupPolicyDryRun)"

# WIF provider 的條件正確
gcloud iam workload-identity-pools providers describe github-edms \
  --project="${PROJECT_ID}" --location=global \
  --workload-identity-pool=github-pool \
  --format="value(attributeCondition)"
# 預期輸出：assertion.repository=='sti-fhb/EDMS' && assertion.ref=='refs/heads/main'

# bucket 的 lifecycle
gcloud storage buckets describe "${BUCKET}" --format="yaml(lifecycle)"
```

第二項務必實際確認——條件寫錯不會有任何錯誤訊息，但會讓任何分支都能取得推送映像的權限。

---

## 5. 這些設定**不涉及**的東西

為避免誤解，明確列出：

- **不需要 self-hosted runner 的任何設定**——EDMS 不使用
- **不需要開放 SSH、IAP 或任何進入 bms-prod-02 的通道**——GitHub 側不部署
- **不需要授予 EDMS 的 SA 任何 compute 權限**——它只推映像
- **不得與 TBMS 共用** service account、bucket 或映像庫

VM 端的安裝（clone repo、`.env.prod`、systemd units）見 [deployment.md](deployment.md) §2.4，那部分由具 bms-prod-02 sudo 權限者執行，與本文件的 GCP 設定互相獨立。
