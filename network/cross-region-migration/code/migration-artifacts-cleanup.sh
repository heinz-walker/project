#!/usr/bin/env bash
#
# RDS(Aurora)/ElastiCache Redis 리전 간 이관용으로 만들었던 스냅샷/백업/임시 S3 버킷 정리 스크립트.
#
# 배경: 소스 리전 클러스터 스냅샷을 대상 리전으로 복사해 복원하고, Redis는 소스 리전 수동
# 백업을 S3 경유로 대상 리전에 seed하는 방식으로 이관을 완료한 뒤에도, 이관용 스냅샷/백업/
# 임시 S3 버킷이 지워지지 않고 남아있는 경우가 많다. 이 스크립트는 그 잔여물을 정리한다.
#
# 검증 원칙: 아래 리소스는 전부 "대상 쪽 리소스가 이미 이 스냅샷/백업에서 복원되어 available
# 상태"인 경우에만 지운다. 스크립트가 삭제 직전 대상 RDS 클러스터/인스턴스, 대상 ElastiCache
# replication group 상태를 실시간으로 재확인하고, 하나라도 available이 아니면 즉시 중단한다
# (set -e + 명시적 검증 함수로 이중 안전장치).
#
# 사용법:
#   AWS_PROFILE=<프로필명> ./migration-artifacts-cleanup.sh --dry-run   # 검증만 수행, 삭제 명령은 출력만 하고 실행 안 함
#   AWS_PROFILE=<프로필명> ./migration-artifacts-cleanup.sh              # 검증 통과 시에만 실제 삭제 수행

set -euo pipefail

PROFILE="${AWS_PROFILE:?AWS_PROFILE 환경변수를 설정하세요 (예: export AWS_PROFILE=<본인 프로필명>)}"
DRY_RUN="${1:-}"

# 아래 값은 예시이며 실제 리소스 이름/리전으로 채워 사용한다.
DST_REGION="<dest-region>"
SRC_REGION="<source-region>"
RDS_CLUSTER_IDS=("app-a-db-cluster" "app-b-db-cluster")
RDS_INSTANCE_IDS=("app-a-db" "app-b-db")
REDIS_REPLICATION_GROUP_ID="app-cache-redis"
REDIS_MEMBER_CLUSTER_ID="app-cache-redis-001"

RDS_SNAPSHOT_IDS=("app-a-db-cluster-migration" "app-b-db-cluster-migration")
REDIS_SNAPSHOT_NAME="app-cache-redis-migration"
EXPORT_BUCKET="<redis-export-bucket-source-region>"
SEED_BUCKET="<redis-seed-bucket-dest-region>"

fail() {
  echo "[검증 실패] $1" >&2
  exit 1
}

verify_available() {
  local desc="$1" actual="$2"
  if [[ "$actual" != "available" ]]; then
    fail "${desc} 상태가 available이 아님 (현재: ${actual}) — 삭제 중단"
  fi
  echo "  [검증 OK] ${desc} -> available"
}

echo "=== 검증: 대상 리전 RDS 클러스터/인스턴스 ==="
for cluster_id in "${RDS_CLUSTER_IDS[@]}"; do
  status=$(aws rds describe-db-clusters --profile "$PROFILE" --region "$DST_REGION" \
    --db-cluster-identifier "$cluster_id" --query 'DBClusters[0].Status' --output text)
  verify_available "$cluster_id" "$status"
done

for instance_id in "${RDS_INSTANCE_IDS[@]}"; do
  status=$(aws rds describe-db-instances --profile "$PROFILE" --region "$DST_REGION" \
    --db-instance-identifier "$instance_id" --query 'DBInstances[0].DBInstanceStatus' --output text)
  verify_available "$instance_id (writer instance)" "$status"
done

echo "=== 검증: 대상 리전 ElastiCache replication group ==="
redis_status=$(aws elasticache describe-replication-groups --profile "$PROFILE" --region "$DST_REGION" \
  --replication-group-id "$REDIS_REPLICATION_GROUP_ID" --query 'ReplicationGroups[0].Status' --output text)
verify_available "$REDIS_REPLICATION_GROUP_ID (replication group)" "$redis_status"

redis_member_status=$(aws elasticache describe-cache-clusters --profile "$PROFILE" --region "$DST_REGION" \
  --cache-cluster-id "$REDIS_MEMBER_CLUSTER_ID" --query 'CacheClusters[0].CacheClusterStatus' --output text)
verify_available "$REDIS_MEMBER_CLUSTER_ID (member cluster)" "$redis_member_status"

echo
echo "=== 검증 통과 — 삭제 대상 ==="
for snap_id in "${RDS_SNAPSHOT_IDS[@]}"; do
  echo " - RDS cluster snapshot: ${snap_id} (${SRC_REGION}, ${DST_REGION})"
done
echo " - ElastiCache manual snapshot: ${REDIS_SNAPSHOT_NAME} (${SRC_REGION})"
echo " - S3 bucket: ${EXPORT_BUCKET} (${SRC_REGION})"
echo " - S3 bucket: ${SEED_BUCKET} (${DST_REGION})"

if [[ "$DRY_RUN" == "--dry-run" ]]; then
  echo
  echo "[dry-run] 아래 명령이 실제 실행될 예정:"
  for snap_id in "${RDS_SNAPSHOT_IDS[@]}"; do
    echo "  aws rds delete-db-cluster-snapshot --profile $PROFILE --region $SRC_REGION --db-cluster-snapshot-identifier $snap_id"
    echo "  aws rds delete-db-cluster-snapshot --profile $PROFILE --region $DST_REGION --db-cluster-snapshot-identifier $snap_id"
  done
  echo "  aws elasticache delete-snapshot --profile $PROFILE --region $SRC_REGION --snapshot-name $REDIS_SNAPSHOT_NAME"
  echo "  aws s3 rm s3://$EXPORT_BUCKET --recursive --profile $PROFILE"
  echo "  aws s3api delete-bucket --bucket $EXPORT_BUCKET --region $SRC_REGION --profile $PROFILE"
  echo "  aws s3 rm s3://$SEED_BUCKET --recursive --profile $PROFILE"
  echo "  aws s3api delete-bucket --bucket $SEED_BUCKET --region $DST_REGION --profile $PROFILE"
  exit 0
fi

echo
echo "=== 실제 삭제 진행 ==="

for snap_id in "${RDS_SNAPSHOT_IDS[@]}"; do
  aws rds delete-db-cluster-snapshot --profile "$PROFILE" --region "$SRC_REGION" \
    --db-cluster-snapshot-identifier "$snap_id" >/dev/null
  echo "  -> 삭제 완료: $snap_id ($SRC_REGION)"

  aws rds delete-db-cluster-snapshot --profile "$PROFILE" --region "$DST_REGION" \
    --db-cluster-snapshot-identifier "$snap_id" >/dev/null
  echo "  -> 삭제 완료: $snap_id ($DST_REGION)"
done

aws elasticache delete-snapshot --profile "$PROFILE" --region "$SRC_REGION" \
  --snapshot-name "$REDIS_SNAPSHOT_NAME" >/dev/null
echo "  -> 삭제 완료: $REDIS_SNAPSHOT_NAME (ElastiCache snapshot, $SRC_REGION)"

aws s3 rm "s3://$EXPORT_BUCKET" --recursive --profile "$PROFILE" >/dev/null
aws s3api delete-bucket --bucket "$EXPORT_BUCKET" --region "$SRC_REGION" --profile "$PROFILE"
echo "  -> 삭제 완료: S3 버킷 $EXPORT_BUCKET ($SRC_REGION)"

aws s3 rm "s3://$SEED_BUCKET" --recursive --profile "$PROFILE" >/dev/null
aws s3api delete-bucket --bucket "$SEED_BUCKET" --region "$DST_REGION" --profile "$PROFILE"
echo "  -> 삭제 완료: S3 버킷 $SEED_BUCKET ($DST_REGION)"

echo
echo "=== 완료 ==="
