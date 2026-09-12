# 이관 스크립트

[03. 네트워크 Import 실행](../03-network-import-execution.md)에서 다룬 데이터/컴퓨트 이관에 실제로 사용했던 스크립트를 일반화한 버전이다.
실제 리소스 이름·ID·계정 정보는 모두 예시 값(`<placeholder>` 또는 `app-a`류 이름)으로 치환했으므로, 그대로 실행하지 말고 각자의 리소스 이름/ID로 값을 채운 뒤 사용해야 한다.

| 스크립트 | 역할 |
| --- | --- |
| `ec2-ami-copy-region-to-region.sh` | 소스 리전에서 생성한 EC2 AMI 여러 개를 대상 리전으로 일괄 복사한다. |
| `ec2-ami-cleanup-region.sh` | 이관용으로 복사했던 AMI(소스+대상 리전)를 연결된 EBS 스냅샷까지 함께 정리한다. |
| `dynamodb-region-export-import.sh` | DynamoDB 테이블을 Export to S3 → Import from S3 방식으로 리전 간 이관한다. 테이블별로 키 스키마가 다른 경우의 분기 처리도 포함한다. |
| `migration-artifacts-cleanup.sh` | RDS/ElastiCache 이관에 썼던 스냅샷·백업·임시 S3 버킷을, 대상 리소스가 실제로 정상 복원됐는지 재확인한 뒤에만 삭제한다. |

공통 설계 원칙은 다음과 같다.

- 모든 스크립트는 `--dry-run` 옵션을 지원한다 — 실제 실행 전에 어떤 명령이 실행될지 먼저 확인할 수 있다.
- 삭제 계열 스크립트(`ec2-ami-cleanup-region.sh`, `migration-artifacts-cleanup.sh`)는 삭제 대상을 조회하거나, 대상 리소스가 정상 상태인지 먼저 검증한 뒤에만 실제 삭제를 진행한다.
- `set -euo pipefail`과 함께 필수 환경변수(`AWS_PROFILE`, 리전 등)가 없으면 즉시 실패하도록 만들어, 잘못된 대상에 실행되는 것을 방지한다.
