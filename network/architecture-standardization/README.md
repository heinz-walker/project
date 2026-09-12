<div align="center">
<h1>AWS Network Firewall 표준화 프로젝트</h1>
<i>AWS Network Firewall Standardization</i>
</div>

*2026.06 – 2026.09 · 클라우드 네트워크 보안 담당*

---

## 흐름
여러 AWS 계정(Dev/Stage/Live)에 걸쳐 진행된 네트워크 방화벽 표준화 작업을 시간 순서로 정리한 인덱스다. 각 문서는 독립된 리포트지만, 아래 순서로 읽으면 하나의 프로젝트로서의 진행 맥락이 이어진다.

1. **[Dev 환경 진단 및 재구축](./01-dev-environment-migration.md)** — 워크로드가 없는 Dev 환경에서 표준 아키텍처를 실제로 구축·검증하며 회사 표준을 정립했다.
2. **[Return Path 설계 원칙](./02-return-path-design-principle.md)** — 1번 재구축 과정에서 실제로 겪었던 라우팅 사고를 계기로, 방화벽 경유 구조에서 왕복 경로 설계가 왜 필수인지 정리한 개념 문서다.
3. **[Stage 환경 적용](./03-stage-environment-migration-plan.md)** — 실서비스 트래픽이 흐르는 Stage 환경에 표준을 적용했다. Dev와 달리 방화벽이 사실상 우회되어 있던 상태를 발견하고, 2번에서 정리한 원칙을 실제 마이그레이션 계획에 반영했다.
4. **[Live 환경 적용 계획](./04-live-environment-migration-plan.md)** — Network Firewall 리소스 자체가 없던 Live 환경에 신규로 도입하는 계획. Stage보다 더 많은 외부 연결(VPC Peering)을 고려해야 했다.
5. **[Live 방화벽 인라인 전환 시도와 롤백](./05-live-cutover-attempt-and-rollback.md)** — 4번 계획을 실제 트래픽 위에서 실행한 컷오버 시도. 사전 작업까지는 계획대로 진행했으나 점검 당일 원인 불명 장애가 겹쳐, 안전을 우선해 방화벽 라우팅만 롤백하고 점검을 종료했다.
6. **[Stage 환경 표준 적용 이후 운영 개선](./06-stage-infra-improvement.md)** — 3번에서 표준을 적용한 Stage 환경을 운영하며 드러난 후속 문제 세 가지(배포 경로 정리, 방화벽 규칙 평가 순서 결함, ALB 서브넷 분리)를 다뤘다.

---
*회사명, 계정/리소스 식별자(계정 ID, VPC/Subnet/NAT/Endpoint ID, IP 등), 내부 서비스명 등은 포함하지 않았습니다.*
