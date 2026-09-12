#!/usr/bin/env bash
#
# DynamoDB 테이블 여러 개를 소스 리전 -> 대상 리전으로 이관하는 스크립트.
#
# 방식: Export to S3 (export-table-to-point-in-time) -> Import from S3 (import-table).
# 실제 이관 프로젝트에서는 이 방식으로 11개 테이블을 이관했다.
#
# 전제조건:
#   - 소스 원본 테이블에 PITR(Point-in-Time Recovery)이 활성화되어 있어야 export 가능
#   - EXPORT_S3_BUCKET: export 결과를 담을 S3 버킷 (실제 버킷명으로 채울 것).
#     export는 원본과 다른 리전의 S3 버킷도 지원한다.
#   - AWS_PROFILE 환경변수로 대상 계정 자격 증명을 사용
#
# 주의:
#   - import-table은 새 테이블만 생성한다. 실패 시 재시도하려면 먼저 delete-table로 지워야 한다.
#   - S3KeyPrefix는 export 폴더 전체가 아니라 그 아래 data/ 하위 폴더를 가리켜야 한다.
#   - export 데이터 파일은 .json.gz이므로 --input-compression-type GZIP을 반드시 지정해야 한다.
#   - 대상 리전의 신규 테이블은 PITR이 기본 비활성 상태다. 필요하면 이관 후 별도로 활성화한다.

set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:?AWS_PROFILE 환경변수를 설정하세요 (예: export AWS_PROFILE=<본인 프로필명>)}"
SRC_REGION="${SRC_REGION:?SRC_REGION 환경변수를 설정하세요 (예: export SRC_REGION=<원본 리전 코드>)}"
DST_REGION="${DST_REGION:?DST_REGION 환경변수를 설정하세요 (예: export DST_REGION=<대상 리전 코드>)}"

# TODO: export 결과를 담을 S3 버킷 (소스 리전에 미리 만들어 둘 것)
EXPORT_S3_BUCKET="<dynamodb-export-bucket-name>"

TABLES=(
  app.orders
  app.inventory
  app.sessions
)

aws_src() { aws --profile "$AWS_PROFILE" --region "$SRC_REGION" "$@"; }
aws_dst() { aws --profile "$AWS_PROFILE" --region "$DST_REGION" "$@"; }

# 테이블별 키 스키마. 실제 프로젝트에서는 대부분 단일 hash key(user_id, N)였지만,
# range key가 있는 테이블·hash key 타입이 다른 테이블이 섞여 있어 case로 분기했다.
# 이 스크립트를 재사용할 때는 실제 테이블 스키마에 맞게 이 분기를 고쳐써야 한다.
table_creation_params() {
  local table="$1"
  case "$table" in
    app.sessions)
      cat <<JSON
{
  "TableName": "$table",
  "AttributeDefinitions": [
    {"AttributeName": "user_id", "AttributeType": "N"},
    {"AttributeName": "key", "AttributeType": "S"}
  ],
  "KeySchema": [
    {"AttributeName": "user_id", "KeyType": "HASH"},
    {"AttributeName": "key", "KeyType": "RANGE"}
  ],
  "BillingMode": "PROVISIONED",
  "ProvisionedThroughput": {"ReadCapacityUnits": 1, "WriteCapacityUnits": 1}
}
JSON
      ;;
    *)
      cat <<JSON
{
  "TableName": "$table",
  "AttributeDefinitions": [
    {"AttributeName": "user_id", "AttributeType": "N"}
  ],
  "KeySchema": [
    {"AttributeName": "user_id", "KeyType": "HASH"}
  ],
  "BillingMode": "PROVISIONED",
  "ProvisionedThroughput": {"ReadCapacityUnits": 1, "WriteCapacityUnits": 1}
}
JSON
      ;;
  esac
}

check_pitr() {
  local table="$1"
  local status
  status=$(aws_src dynamodb describe-continuous-backups \
    --table-name "$table" \
    --query 'ContinuousBackupsDescription.PointInTimeRecoveryDescription.PointInTimeRecoveryStatus' \
    --output text)
  if [[ "$status" != "ENABLED" ]]; then
    echo "[$table] PITR이 비활성 상태입니다. export-table-to-point-in-time을 쓰려면 먼저 PITR을 켜야 합니다." >&2
    exit 1
  fi
}

export_table() {
  local table="$1"
  local table_arn
  table_arn=$(aws_src dynamodb describe-table --table-name "$table" --query 'Table.TableArn' --output text)

  echo "[$table] export 시작..."
  local export_arn
  export_arn=$(aws_src dynamodb export-table-to-point-in-time \
    --table-arn "$table_arn" \
    --s3-bucket "$EXPORT_S3_BUCKET" \
    --s3-prefix "dynamodb-export/${table}" \
    --export-format DYNAMODB_JSON \
    --query 'ExportDescription.ExportArn' \
    --output text)

  echo "[$table] export 완료 대기 (ExportArn: $export_arn)"
  while true; do
    local export_status
    export_status=$(aws_src dynamodb describe-export --export-arn "$export_arn" \
      --query 'ExportDescription.ExportStatus' --output text)
    case "$export_status" in
      COMPLETED) break ;;
      FAILED) echo "[$table] export 실패" >&2; exit 1 ;;
      *) sleep 15 ;;
    esac
  done

  # export id는 ExportArn 마지막 "export/<exportId>" 부분에 들어있다.
  local export_id="${export_arn##*/export/}"
  echo "dynamodb-export/${table}/AWSDynamoDB/${export_id}/data/"
}

import_table() {
  local table="$1"
  local s3_key_prefix="$2"

  # 기존에 실패한 동일 이름 테이블이 있으면 import-table이 재사용할 수 없으므로 먼저 지운다.
  if aws_dst dynamodb describe-table --table-name "$table" >/dev/null 2>&1; then
    echo "[$table] 대상 리전에 동일 이름 테이블이 이미 있어 먼저 삭제합니다."
    aws_dst dynamodb delete-table --table-name "$table" >/dev/null
    aws_dst dynamodb wait table-not-exists --table-name "$table"
  fi

  echo "[$table] import 시작 (S3KeyPrefix: $s3_key_prefix)"
  local import_arn
  import_arn=$(aws_dst dynamodb import-table \
    --s3-bucket-source "S3Bucket=${EXPORT_S3_BUCKET},S3KeyPrefix=${s3_key_prefix}" \
    --input-format DYNAMODB_JSON \
    --input-compression-type GZIP \
    --table-creation-parameters "$(table_creation_params "$table")" \
    --query 'ImportTableDescription.ImportArn' \
    --output text)

  echo "[$table] import 완료 대기 (ImportArn: $import_arn)"
  while true; do
    local import_status
    import_status=$(aws_dst dynamodb describe-import --import-arn "$import_arn" \
      --query 'ImportTableDescription.ImportStatus' --output text)
    case "$import_status" in
      COMPLETED) break ;;
      FAILED|CANCELLED) echo "[$table] import 실패 ($import_status)" >&2; exit 1 ;;
      *) sleep 15 ;;
    esac
  done
}

verify_item_count() {
  local table="$1"
  local src_count dst_count
  src_count=$(aws_src dynamodb describe-table --table-name "$table" --query 'Table.ItemCount' --output text)
  dst_count=$(aws_dst dynamodb describe-table --table-name "$table" --query 'Table.ItemCount' --output text)
  echo "[$table] item count - source: $src_count, dest: $dst_count (describe-table 값은 최대 6시간 지연될 수 있어 참고용. 정확한 검증은 item 단위 비교 필요)"
}

main() {
  for table in "${TABLES[@]}"; do
    check_pitr "$table"
  done

  for table in "${TABLES[@]}"; do
    s3_key_prefix=$(export_table "$table")
    import_table "$table" "$s3_key_prefix"
    verify_item_count "$table"
  done

  echo "모든 테이블 export/import 완료. item 단위 데이터 일치 검증을 별도로 수행할 것."
}

main "$@"
