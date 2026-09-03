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

```bash
# 以下所有指令共用的變數
export PROJECT_ID=blood-system-dev
export PROJECT_NUM=398001699233
export REGION=asia-east1
export VM_SA=398001699233-compute@developer.gserviceaccount.com   # bms-prod-02 的 Service Account
```

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

### 2.4 回報這兩個值

```
GCP_WORKLOAD_IDENTITY_PROVIDER =
  projects/398001699233/locations/global/workloadIdentityPools/github-pool/providers/github-edms

GCP_BUILD_SERVICE_ACCOUNT =
  edms-build@blood-system-dev.iam.gserviceaccount.com
```

由 EDMS 開發者填入 **GitHub repo variables**（Settings → Secrets and variables → Actions → Variables）。這兩個值不是機密，用 variables 而非 secrets 即可。

---

## 3. GCS 備份 bucket

```bash
gcloud storage buckets create gs://edms-db-backup \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --uniform-bucket-level-access
```

### 3.1 VM 的寫入權限

備份由 bms-prod-02 上的腳本執行（migration 前備份、每日備份）：

```bash
gcloud storage buckets add-iam-policy-binding gs://edms-db-backup \
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

gcloud storage buckets update gs://edms-db-backup \
  --lifecycle-file=/tmp/edms-bucket-lifecycle.json
```

### 3.3 Retention 鎖（建議）

30 天內任何權限都無法刪除或覆寫物件，防止 VM 遭入侵時備份被一併銷毀：

```bash
gcloud storage buckets update gs://edms-db-backup --retention-period=30d
```

> ⚠️ `--lock-retention-period` 會讓保留期**永久無法縮短或移除**，屬不可逆操作。TBMS 的 bucket 已採此設定；EDMS 是否比照請自行判斷，未鎖定時保留期仍然生效，只是日後可調整。

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
gcloud storage buckets describe gs://edms-db-backup --format="yaml(lifecycle)"
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
