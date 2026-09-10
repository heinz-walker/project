# Project Reports

실무에서 진행한 보안/인프라 프로젝트 경험을 정리한 저장소입니다.
회사 고유 정보(내부 시스템명, 계정, 인프라 세부 정보 등)는 제거하거나 일반화하여 작성합니다.

## Index

### [network-firewall](./network-firewall/) — AWS Network Firewall 표준화
Dev 환경 진단·재구축으로 표준 정립 → Stage/Live 적용 → Live 컷오버 시도·롤백 → Stage 운영 개선

1. [Dev 환경 진단 및 재구축](./network-firewall/01-dev-environment-migration.md) — 워크로드가 없는 Dev 환경에서 표준 아키텍처를 실제로 구축·검증하며 회사 표준을 정립했다.
2. [Return Path 설계 원칙](./network-firewall/02-return-path-design-principle.md) — Dev 재구축 과정에서 겪은 라우팅 사고를 계기로, 방화벽 경유 구조에서 왕복 경로 설계가 왜 필수인지 정리한 개념 문서다.
3. [Stage 환경 적용](./network-firewall/03-stage-environment-migration-plan.md) — 실서비스 트래픽이 흐르는 Stage 환경에 표준을 적용했다. 방화벽이 사실상 우회되어 있던 상태를 발견하고, Return Path 원칙을 마이그레이션 계획에 반영했다.
4. [Live 환경 적용 계획](./network-firewall/04-live-environment-migration-plan.md) — Network Firewall 리소스 자체가 없던 Live 환경에 신규로 도입하는 계획. Stage보다 더 많은 외부 연결(VPC Peering)을 고려해야 했다.
5. [Live 방화벽 인라인 전환 시도와 롤백](./network-firewall/05-live-cutover-attempt-and-rollback.md) — Live 적용 계획을 실제 트래픽 위에서 실행한 컷오버 시도. 점검 당일 원인 불명 장애가 겹쳐, 안전을 우선해 방화벽 라우팅만 롤백하고 점검을 종료했다.
6. [Stage 환경 표준 적용 이후 운영 개선](./network-firewall/06-stage-infra-improvement.md) — 표준 적용 후 Stage를 운영하며 드러난 후속 문제 세 가지(배포 경로 정리, 방화벽 규칙 평가 순서 결함, ALB 서브넷 분리)를 다뤘다.

### [poc/security-review/2407-dlp-adoption](./poc/security-review/2407-dlp-adoption/) — DLP 솔루션 도입 평가
후보 조사 → 1차 정량 평가 → 평가 방법론 자체 검증·개정 → 상위 후보 재검증(PoC) → 가격 대비 종합 판단으로 최종 선정

### [security-policy/2606-network-separation-relaxation](./security-policy/2606-network-separation-relaxation/) — 망분리 완화 및 대체 보호조치 체계 구축
법령 개정을 계기로 망분리 의무 대상 여부를 법적으로 재검토 → 표준 기반 대체 보호조치 통제영역 도출 → 현황 점검·취약점 식별 → 보완 계획 수립 및 잔여위험 판단

### [automation/2606-cloud-risk-assessment](./automation/2606-cloud-risk-assessment/) — 클라우드 위험평가 자동화
위험평가 산식(R=A×T×V)의 자산가치 근거인 클라우드 자산대장 정비 → 취약성 평가를 boto3 읽기 전용 자동화 도구로 자체 개발 → 자동 산정 결과와 정식 위험평가 보고서 체계의 정합성 점검
