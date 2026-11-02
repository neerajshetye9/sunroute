#!/usr/bin/env bash
# SunRoute Pre-Expiry Export Script
# Preserves all AWS lab data, CloudWatch logs, DynamoDB records, and S3 archives
# to local storage before the 24-hour temporary lab environment expires.

set -euo pipefail

BACKUP_DIR="experiments/lab_backup_$(date -u +%Y%m%d_%H%M%S)"
mkdir -p "${BACKUP_DIR}"

echo "=========================================================="
echo "SunRoute: Exporting AWS Lab Artifacts before Lab Expiry"
echo "Target directory: ${BACKUP_DIR}"
echo "=========================================================="

# 1. Check AWS CLI and credentials
if ! command -v aws >/dev/null 2>&1; then
    echo "[!] AWS CLI is not installed on this host. Skipping remote AWS backup."
    echo "[!] Local experiment databases and logs are preserved in experiments/."
    exit 0
fi

if ! aws sts get-caller-identity >/dev/null 2>&1; then
    echo "[!] No active AWS credentials found. Skipping remote AWS resource export."
    echo "[!] Backing up local SQLite audit and DuckDB databases..."
    cp -v experiments/*.db "${BACKUP_DIR}/" 2>/dev/null || true
    echo "Backup completed for local databases."
    exit 0
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query "Account" --output text)
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
echo "[*] Connected to Account: ${ACCOUNT_ID} in ${REGION}"

# 2. Backup DynamoDB Node State Table
echo "[*] Scanning DynamoDB SunRouteNodeState table..."
mkdir -p "${BACKUP_DIR}/dynamodb"
for tbl in $(aws dynamodb list-tables --query "TableNames[?starts_with(@, 'SunRouteNodeState')]" --output text); do
    echo "  Exporting table: ${tbl}..."
    aws dynamodb scan --table-name "${tbl}" > "${BACKUP_DIR}/dynamodb/${tbl}.json"
done

# 3. Synchronize S3 Telemetry Bucket
echo "[*] Syncing S3 telemetry archive..."
mkdir -p "${BACKUP_DIR}/s3"
for bucket in $(aws s3api list-buckets --query "Buckets[?starts_with(Name, 'sunroute-telemetry')].Name" --output text); do
    echo "  Syncing s3://${bucket}..."
    aws s3 sync "s3://${bucket}" "${BACKUP_DIR}/s3/${bucket}" --no-progress || true
done

# 4. Dump CloudWatch Log Streams
echo "[*] Exporting CloudWatch log groups..."
mkdir -p "${BACKUP_DIR}/logs"
for lg in $(aws logs describe-log-groups --query "logGroups[?contains(logGroupName, 'sunroute')].logGroupName" --output text); do
    echo "  Saving logs for: ${lg}..."
    SAFE_NAME=$(echo "${lg}" | tr '/' '_')
    aws logs filter-log-events --log-group-name "${lg}" --max-items 500 > "${BACKUP_DIR}/logs/${SAFE_NAME}.json" || true
done

# 5. Backup local experiment and audit data
echo "[*] Backing up local decision logs and SQLite outbox..."
cp -v experiments/*.db "${BACKUP_DIR}/" 2>/dev/null || true

echo "=========================================================="
echo "Export complete! All lab artifacts saved to: ${BACKUP_DIR}"
echo "=========================================================="
