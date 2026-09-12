#!/usr/bin/env bash
#
# EC2 인스턴스 여러 대의 AMI를 소스 리전 -> 대상 리전으로 복사하는 스크립트.
#
# 방식: (각 인스턴스별로 소스 리전에서 Create Image를 먼저 완료해둔 뒤) aws ec2 copy-image로
# 대상 리전에 복사한다. 실제 이관 프로젝트에서는 애플리케이션 7종의 AMI를 이 방식으로 복사했다.
#
# 전제조건:
#   - 소스 리전에 각 인스턴스의 AMI가 이미 생성되어 available 상태일 것
#   - AWS_PROFILE 환경변수로 대상 계정 자격 증명을 사용
#
# 주의:
#   - copy-image는 새 AMI(+ 새 스냅샷)를 대상 리전에 생성한다. 원본 AMI/스냅샷은 그대로 유지된다.
#   - 인스턴스 launch 확인이 끝나면 이 복사본 AMI(양쪽 리전)는 정리 대상이다
#     (ec2-ami-cleanup-region.sh 참고).
#   - macOS 기본 bash(3.2)는 연관 배열(declare -A)을 지원하지 않으므로 "name|id" 형태의
#     일반 배열 + 문자열 파싱 방식을 사용한다.
#
# 사용법:
#   AWS_PROFILE=<프로필명> ./ec2-ami-copy-region-to-region.sh --dry-run   # 실행할 명령만 출력
#   AWS_PROFILE=<프로필명> ./ec2-ami-copy-region-to-region.sh              # 실제 복사 실행

set -euo pipefail

PROFILE="${AWS_PROFILE:?AWS_PROFILE 환경변수를 설정하세요 (예: export AWS_PROFILE=<본인 프로필명>)}"
SRC_REGION="${SRC_REGION:?SRC_REGION 환경변수를 설정하세요 (예: export SRC_REGION=<원본 리전 코드>)}"
DST_REGION="${DST_REGION:?DST_REGION 환경변수를 설정하세요 (예: export DST_REGION=<대상 리전 코드>)}"
DRY_RUN="${1:-}"

# name|source_ami_id  (아래 값은 예시이며 실제 AMI ID로 채워 사용한다)
AMIS=(
  "app-a-migration|<source-region-ami-id-1>"
  "app-b-migration|<source-region-ami-id-2>"
  "app-c-migration|<source-region-ami-id-3>"
)

for entry in "${AMIS[@]}"; do
  name="${entry%%|*}"
  src_id="${entry##*|}"

  if [[ "$DRY_RUN" == "--dry-run" ]]; then
    echo "[dry-run] would copy ${name} (${src_id}) from ${SRC_REGION} to ${DST_REGION}"
    echo "[dry-run] aws ec2 copy-image --profile ${PROFILE} --region ${DST_REGION} --source-region ${SRC_REGION} --source-image-id ${src_id} --name ${name} --description \"[Copied ${src_id} from ${SRC_REGION}] ${name}\""
    continue
  fi

  echo "Copying ${name} (${src_id}) -> ${DST_REGION} ..."
  new_id=$(aws ec2 copy-image \
    --profile "$PROFILE" \
    --region "$DST_REGION" \
    --source-region "$SRC_REGION" \
    --source-image-id "$src_id" \
    --name "$name" \
    --description "[Copied ${src_id} from ${SRC_REGION}] ${name}" \
    --query 'ImageId' --output text)
  echo "  -> new image in ${DST_REGION}: ${new_id}"
done
