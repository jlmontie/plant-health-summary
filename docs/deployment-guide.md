# Deployment Guide

Complete guide for deploying the Plant Health Demo from scratch.

## How It Works

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         terraform apply                                  │
├─────────────────────────────────────────────────────────────────────────┤
│  Creates (in order):                                                     │
│  1. APIs (Cloud Run, Artifact Registry, etc.)                           │
│  2. Artifact Registry repository                                         │
│  3. Service accounts + IAM                                               │
│  4. Pub/Sub, BigQuery                                                    │
│  5. Cloud Run service (with PLACEHOLDER image)  ◀── gcr.io/cloudrun/hello│
│  6. Cloud Build trigger                                                  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                            git push                                      │
├─────────────────────────────────────────────────────────────────────────┤
│  Cloud Build:                                                            │
│  1. Builds YOUR image                                                    │
│  2. Pushes to Artifact Registry (exists!)                               │
│  3. Deploys to Cloud Run (updates placeholder → real image)             │
└─────────────────────────────────────────────────────────────────────────┘
```

**Key insight:** Terraform deploys a placeholder image (`gcr.io/cloudrun/hello`) initially.
Cloud Build then replaces it with your actual app. The `lifecycle { ignore_changes }` block
prevents Terraform from reverting back to the placeholder on subsequent applies.

---

## Prerequisites

1. **GCP Project** with billing enabled
2. **gcloud CLI** authenticated: `gcloud auth login`
3. **Terraform** installed (v1.0+)
4. **GitHub repo** connected to Cloud Build

---

## Step 1: Connect GitHub to Cloud Build (One-Time)

This must be done manually in the GCP Console before Terraform runs.

1. Go to [Cloud Build > Repositories](https://console.cloud.google.com/cloud-build/repositories)
2. Click **"Create Host Connection"** → GitHub
3. Authenticate with GitHub
4. Name the connection: `github-connection`
5. Click **"Link Repository"** → Select your repo
6. Note: The repo will appear as `projects/PROJECT_ID/locations/REGION/connections/github-connection/repositories/REPO_NAME`

---

## Step 2: Configure Terraform Variables

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:
```hcl
project_id    = "your-project-id"
region        = "us-central1"
app_name      = "plant-health-summary"
github_owner  = "your-github-username"
github_repo   = "plant-health-summary"
use_vertex_ai = true  # Recommended for production
```

---

## Step 3: Deploy Infrastructure

```bash
cd terraform

# Initialize Terraform
terraform init

# Preview changes
terraform plan

# Apply (creates all resources in correct order)
terraform apply
```

**What gets created (in dependency order):**
1. Required APIs (Cloud Run, Artifact Registry, etc.)
2. Service accounts with IAM roles
3. Artifact Registry repository ← Must exist before builds
4. Pub/Sub topics and subscriptions
5. BigQuery dataset and table
6. Cloud Run service ← Uses `gcr.io/cloudrun/hello` placeholder (always available)
7. Cloud Build trigger ← Depends on Artifact Registry

**Note:** The Cloud Run service initially runs Google's "hello" placeholder. 
Your first `git push` will replace it with the real app.

---

## Step 4: Trigger First Deployment

After Terraform completes, push a commit to trigger the build:

```bash
git add .
git commit -m "trigger deployment"
git push origin main
```

Or manually trigger:
```bash
gcloud builds triggers run deploy-main \
  --region=us-central1 \
  --branch=main
```

---

## Step 5: Verify Deployment

```bash
# Check build status
gcloud builds list --region=us-central1 --limit=1

# Get the app URL
gcloud run services describe plant-health-summary-app \
  --region=us-central1 \
  --format="value(status.url)"
```

---

## Tear Down & Rebuild

### Full Teardown
```bash
cd terraform
terraform destroy
```

### Rebuild
```bash
terraform apply
# Then push a commit to trigger the build
```

---

## Troubleshooting

### "Repository not found" during build
**Cause:** Artifact Registry repo doesn't exist.  
**Fix:** Run `terraform apply` FIRST - it creates the repo before the trigger.

**Why this happens:** If you manually created the Cloud Build trigger (or ran incomplete Terraform),
the trigger exists but has nowhere to push images. Always use `terraform apply` to ensure
proper dependency ordering.

### Cloud Run shows "hello" instead of your app
**Cause:** You ran `terraform apply` but haven't pushed code yet.  
**Fix:** Push to main branch to trigger the first real build:
```bash
git push origin main
```

### "Container failed to start on PORT"
**Cause:** Port mismatch between Dockerfile and Cloud Run config.  
**Fix:** Both should use `8080` (Cloud Run default).

### "Permission denied" errors
**Cause:** Service account missing roles.  
**Fix:** Check `terraform/iam.tf` - run `terraform apply` to fix IAM.

### Build succeeds but app crashes
**Check logs:**
```bash
gcloud logging read "resource.type=cloud_run_revision" --limit=50
```

---

## Resource Dependencies (Critical)

```
                    ┌──────────────────────┐
                    │   Required APIs      │
                    └──────────┬───────────┘
                               │
            ┌──────────────────┼──────────────────┐
            │                  │                  │
            ▼                  ▼                  ▼
   ┌────────────────┐  ┌──────────────┐  ┌──────────────┐
   │ Artifact       │  │ Pub/Sub      │  │ BigQuery     │
   │ Registry       │  │ Topics       │  │ Dataset      │
   └───────┬────────┘  └──────────────┘  └──────────────┘
           │
           │ depends_on
           ▼
   ┌────────────────┐
   │ Cloud Build    │──────────▶ Pushes images
   │ Trigger        │
   └───────┬────────┘
           │
           │ triggers
           ▼
   ┌────────────────┐
   │ Cloud Run      │──────────▶ Pulls images
   │ Service        │
   └────────────────┘
```

The key insight: **Cloud Build Trigger must wait for Artifact Registry to exist**, otherwise the first build will fail trying to push images to a non-existent repository.

---

## Cost Estimates

| Resource | Free Tier | Estimated Monthly |
|----------|-----------|-------------------|
| Cloud Build | 120 min/day | $0 |
| Artifact Registry | 500MB | $0 |
| Cloud Run | 2M requests | $0 |
| Pub/Sub | 10GB | $0 |
| BigQuery | 10GB storage | $0 |
| **Total** | | **~$0-5/month** |

---

## Quick Reference Commands

```bash
# Check all resources
terraform state list

# Rebuild single resource
terraform apply -target=google_artifact_registry_repository.app

# View trigger
gcloud builds triggers describe plant-health-summary-deploy --region=us-central1

# Manual build (bypasses trigger)
gcloud builds submit --config=cloudbuild.yaml \
  --substitutions=_REGION=us-central1,_REPO_NAME=plant-health-summary,_SERVICE_NAME=plant-health-summary-app

# View Cloud Run logs
gcloud run services logs read plant-health-summary-app --region=us-central1
```
