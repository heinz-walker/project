#!/usr/bin/env bash
#
# 이관용으로 만들었던 AMI(소스 리전 원본 + 대상 리전 복사본)를 정리하는 스크립트.
#
# 배경: ec2-ami-copy-region-to-region.sh로 복사한 AMI로 대상 리전에 인스턴스를 launch하고
# 접속까지 확인한 뒤에는, 더 이상 이 AMI들이 필요 없어 정리한다.
#
# 주의:
#   - AMI deregister는 이미 launch된 인스턴스에 영향 없음(인스턴스는 이미 자체 EBS 볼륨으로 동작 중).
#   - deregister-image는 AMI 자체만 지우고, 백업 스냅샷은 별도로 남는다. 그래서 각 AMI의
#     스냅샷 ID를 먼저 조회해서 deregister 후 delete-snapshot까지 같이 처리한다.
#   - 되돌릴 수 없는 작업이므로 반드시 --dry-run으로 먼저 스냅샷 ID/삭제 대상을 확인한 뒤 실행할 것.
#
# 사용법:
#   AWS_PROFILE=<프로필명> ./ec2-ami-cleanup-region.sh --dry-run   # 조회만, 실제 삭제 없음
#   AWS_PROFILE=<프로필명> ./ec2-ami-cleanup-region.sh              # 실제 deregister + snapshot 삭제

set -euo pipefail

PROFILE="${AWS_PROFILE:?AWS_PROFILE 환경변수를 설정하세요 (예: export AWS_PROFILE=<본인 프로필명>)}"
DRY_RUN="${1:-}"

# name|region|ami_id  (아래 값은 예시이며 실제 AMI ID로 채워 사용한다)
AMIS=(
  "app-a-migration(source)|<source-region>|<source-region-ami-id-1>"
  "app-b-migration(source)|<source-region>|<source-region-ami-id-2>"
  "app-c-migration(source)|<source-region>|<source-region-ami-id-3>"
  "app-a-migration(dest)|<dest-region>|<dest-region-ami-id-1>"
  "app-b-migration(dest)|<dest-region>|<dest-region-ami-id-2>"
  "app-c-migration(dest)|<dest-region>|<dest-region-ami-id-3>"
)

for entry in "${AMIS[@]}"; do
  name="${entry%%|*}"
  rest="${entry#*|}"
  region="${rest%%|*}"
  ami_id="${rest##*|}"

  snapshot_ids=$(aws ec2 describe-images \
    --profile "$PROFILE" \
    --region "$region" \
    --image-ids "$ami_id" \
    --query 'Images[].BlockDeviceMappings[].Ebs.SnapshotId' \
    --output text)

  echo "${name} (${region}, ${ami_id}) -> snapshots: ${snapshot_ids}"

  if [[ "$DRY_RUN" == "--dry-run" ]]; then
    echo "  [dry-run] aws ec2 deregister-image --profile ${PROFILE} --region ${region} --image-id ${ami_id}"
    for snap in $snapshot_ids; do
      echo "  [dry-run] aws ec2 delete-snapshot --profile ${PROFILE} --region ${region} --snapshot-id ${snap}"
    done
    continue
  fi

  aws ec2 deregister-image --profile "$PROFILE" --region "$region" --image-id "$ami_id"
  echo "  -> deregistered ${ami_id}"

  for snap in $snapshot_ids; do
    aws ec2 delete-snapshot --profile "$PROFILE" --region "$region" --snapshot-id "$snap"
    echo "  -> deleted snapshot ${snap}"
  done
done
