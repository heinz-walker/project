<div align="center">
<h1>OpenTofu 기반 리전 간 인프라 이관</h1>
<i>Cross-Region Infrastructure Migration with OpenTofu</i>
</div>

*2026.07 · 정보보안 담당*

---

## 흐름
원본 리전의 Dev 환경을 대상 리전으로 옮긴 리전 간 인프라 이관 작업을 순서대로 정리한 인덱스다.
IaC 구조 검토 → 이관 계획 수립 → 네트워크·데이터·컴퓨트 Import 실행 → 재검증으로 드러난 누락 발견·수정 → 애플리케이션 헬스체크 근본원인 조사 → 그 과정에서 파생된 보안 후속조치(패치 자동화) 순으로 진행됐다.

1. **[OpenTofu 프로젝트 구조 검토](./01-opentofu-project-structure-review.md)** — 이관에 앞서 기존 코드의 state 구조를 대안들과 비교 검토하고 현재 구조 유지를 결정했다.
2. **[이관 계획과 보안 기준](./02-migration-plan-and-security-baseline.md)** — 기존 대상 리전 VPC를 재사용하는 방침, 준수해야 할 사내 보안 운영 원칙, 원본 리전 현황 조사와 이전 우선순위를 정리했다.
3. **[네트워크 Import 실행](./03-network-import-execution.md)** — 대상 리전 VPC 기반 리소스를 state로 편입하고 데이터/컴퓨트를 이관한 뒤, 공유 Bastion VPC까지 같은 방식으로 코드화했다.
4. **[이관 후 발견된 누락과 재검증](./04-post-migration-gap-and-recheck.md)** — "완료"됐던 EC2 이관이 실제로는 Auto Scaling Group 구성을 반영하지 못했다는 지적을 계기로 재조사하고 바로잡았다.
5. **[애플리케이션 헬스체크 근본원인 조사](./05-application-healthcheck-root-cause.md)** — Auto Scaling Group 전환 이후 발생한 헬스체크 실패를 인스턴스 직접 접속으로 조사해 두 가지 근본 원인을 규명했다.
6. **[패치 자동화 후속조치](./06-patch-automation-followup.md)** — 이관 과정에서 발견한 Bastion 인스턴스의 장기 미패치 문제를, 아웃바운드를 다시 열지 않고 Patch Manager로 해결한 과정을 다뤘다.

---
*회사명, 계정/리소스 식별자(계정 ID, VPC/Subnet/AMI/Instance ID 등), 내부 문서 코드/버전, IP 대역, 애플리케이션/게임 코드명 등은 포함하지 않았습니다.*
