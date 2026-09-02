# Phase 3.7 — S3 Storage Cutover + MongoDB Retirement

## Final architecture

```
┌──────────────────────────────┐
│  FastAPI backend (uvicorn)   │
└─────────────┬────────────────┘
              │
      ┌───────┴────────┬──────────────────┐
      ▼                ▼                  ▼
┌───────────┐  ┌────────────────┐  ┌────────────────────┐
│ PostgreSQL │  │  S3 (blobs)    │  │ (dev) local FS     │
│ + Alembic  │  │  SSE-KMS       │  │ /app/backend/data/ │
└───────────┘  └────────────────┘  └────────────────────┘
```

* **PostgreSQL** — authoritative for **all** structured data + file metadata.
* **S3** — object storage for file blobs in production. Private bucket,
  SSE-KMS with a customer-managed key, TLS-only bucket policy, Block
  Public Access enabled.
* **Filesystem** — the dev/sandbox equivalent of S3. Both implement the
  same async `Storage` interface.

**MongoDB is completely retired.** `MONGO_URL` is optional (only the
backfill script and legacy backup tools use it).

## S3 bucket / IAM assumptions

The playbook expects:

* A **private** bucket, region matches `AWS_REGION`.
* **Block Public Access** enabled at both account + bucket level.
* **Default encryption** = `SSE-KMS` with the customer-managed key ARN in
  `S3_KMS_KEY_ARN`.
* Bucket policy denies non-TLS access and non-KMS uploads (see the
  playbook returned by `integration_playbook_expert_v2`).
* Object keys are opaque (`clients/<client_id>/<hash-prefix>/<uuid>`,
  `visits/<appt_id>/<uuid>.webm`, `gridfs-backfill/<..>`) — no PHI ever
  in keys.
* AWS HIPAA BAA is signed for the account.

Minimum IAM permissions (see playbook for JSON):

* `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`,
  `s3:AbortMultipartUpload`, `s3:ListMultipartUploadParts`,
  `s3:ListBucketMultipartUploads`
* `kms:GenerateDataKey`, `kms:Decrypt`, `kms:DescribeKey` for
  `S3_KMS_KEY_ARN`

## Environment variables

| Variable                        | Required? | Notes                          |
|--------------------------------|-----------|-------------------------------|
| `STORAGE_BACKEND`               | yes       | `filesystem` (dev) or `s3`     |
| `STORAGE_FS_ROOT`               | fs only   | e.g. `/var/lib/emr/blobs`      |
| `AWS_REGION`                    | s3        |                               |
| `S3_BUCKET_NAME`                | s3        |                               |
| `S3_KMS_KEY_ARN`                | s3        | customer-managed KMS key ARN   |
| `S3_PRESIGN_EXPIRES_SECONDS`    | optional  | default 900                    |
| `AWS_ACCESS_KEY_ID` / `SECRET`  | dev only  | prod uses EC2 instance profile |
| `MONGO_URL`                     | **NO**    | now only used by scripts/backup|
| `DB_NAME`                       | **NO**    | now only used by scripts/backup|

## EC2 deployment commands

```bash
# 1. Instance role attached to EC2 must include the IAM policy above.
# 2. On the box:
sudo -u emrapp bash <<'EOF'
cd /opt/natmedsol/backend
source .venv/bin/activate
pip install -r requirements.txt

# Storage backend
export STORAGE_BACKEND=s3
export AWS_REGION=us-east-1
export S3_BUCKET_NAME=natmedsol-emr-prod
export S3_KMS_KEY_ARN=arn:aws:kms:us-east-1:111122223333:key/xxxx

# Run schema up to head
alembic upgrade head

# One-time GridFS -> S3 backfill (safe to re-run; resumable)
python -m scripts.backfill_gridfs_to_storage --dry-run
python -m scripts.backfill_gridfs_to_storage --resume

# Restart the service
sudo systemctl restart emr-backend
EOF

# 3. Verify
curl -s https://api.natmedsol.local/api/health | jq
# The response must return {"ok": true, ...} even if MongoDB is stopped.
```

## Rollback procedure

Rollback within 24 hours (post-cutover) — GridFS data still present:

```bash
# 1. Re-enable MongoDB access on the EC2 host + restore GridFS blobs.
# 2. Roll the app back to the previous commit (before this phase):
cd /opt/natmedsol && git checkout ca5051e && ./bin/deploy

# 3. Alembic — do NOT downgrade unless you have to; the payload+storage
#    columns are additive and harmless. If a downgrade is required:
alembic downgrade b2c3d4e5f6a7

# 4. Restart
sudo systemctl restart emr-backend
```

Rollback after data has diverged (>24h):

* Snapshot PostgreSQL first (`pg_dump -Fc`).
* Restore Mongo from the last backup (`mongorestore`).
* Roll the app back to the pre-Phase-3.7 commit **only for read paths**;
  writes have already been going to PG-only, so the Mongo replica is
  behind.
* Reconcile using the `/tmp/gridfs_pre_drop_snapshot.json` file that was
  written just before the collections were dropped.
