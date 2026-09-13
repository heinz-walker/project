# Project Reports

실무에서 진행한 보안/인프라 프로젝트 경험을 정리한 저장소입니다.
회사 고유 정보(내부 시스템명, 계정, 인프라 세부 정보 등)는 제거하거나 일반화하여 작성합니다.

## Index

### [network](./network/) — 네트워크
AWS 환경 네트워크 아키텍처 설계·운영

- [SG-to-SG 체이닝 기반 최소권한 네트워크 통제 설계](./network/sg-to-sg-access-control/) — CIDR/전체허용 기반이던 보안그룹 정책을 SG 간 참조 기반 최소권한 통제로 전환하는 설계를 검토했다. 이 검토가 이후 아래 표준 아키텍처로 발전했다.

- **[아키텍처 표준화](./network/architecture-standardization/)** — AWS Network Firewall 도입을 중심으로 Dev 환경 진단·재구축으로 표준 정립 → Stage/Live 적용 → Live 컷오버 시도·롤백 → Stage 운영 개선

  1. [Dev 환경 진단 및 재구축](./network/architecture-standardization/01-dev-environment-migration.md) — 워크로드가 없는 Dev 환경에서 표준 아키텍처를 실제로 구축·검증하며 회사 표준을 정립했다.
  2. [Return Path 설계 원칙](./network/architecture-standardization/02-return-path-design-principle.md) — Dev 재구축 과정에서 겪은 라우팅 사고를 계기로, 방화벽 경유 구조에서 왕복 경로 설계가 왜 필수인지 정리한 개념 문서다.
  3. [Stage 환경 적용](./network/architecture-standardization/03-stage-environment-migration-plan.md) — 실서비스 트래픽이 흐르는 Stage 환경에 표준을 적용했다. 방화벽이 사실상 우회되어 있던 상태를 발견하고, Return Path 원칙을 마이그레이션 계획에 반영했다.
  4. [Live 환경 적용 계획](./network/architecture-standardization/04-live-environment-migration-plan.md) — Network Firewall 리소스 자체가 없던 Live 환경에 신규로 도입하는 계획. Stage보다 더 많은 외부 연결(VPC Peering)을 고려해야 했다.
  5. [Live 방화벽 인라인 전환 시도와 롤백](./network/architecture-standardization/05-live-cutover-attempt-and-rollback.md) — Live 적용 계획을 실제 트래픽 위에서 실행한 컷오버 시도. 점검 당일 원인 불명 장애가 겹쳐, 안전을 우선해 방화벽 라우팅만 롤백하고 점검을 종료했다.
  6. [Stage 환경 표준 적용 이후 운영 개선](./network/architecture-standardization/06-stage-infra-improvement.md) — 표준 적용 후 Stage를 운영하며 드러난 후속 문제 세 가지(배포 경로 정리, 방화벽 규칙 평가 순서 결함, ALB 서브넷 분리)를 다뤘다.

- **[리전 간 인프라 이관](./network/cross-region-migration/)** — IaC 구조 설계 검토 → 이관 계획 수립 → 네트워크 기반 리소스 Import 실행 → 재검증으로 드러난 누락 발견·수정 → 애플리케이션 헬스체크 근본원인 조사 → 파생된 보안 후속조치(패치 자동화)

  1. [OpenTofu 프로젝트 구조 검토](./network/cross-region-migration/01-opentofu-project-structure-review.md) — 이관에 앞서 기존 코드의 state 구조를 대안들과 비교 검토하고 현재 구조 유지를 결정했다.
  2. [이관 계획과 보안 기준](./network/cross-region-migration/02-migration-plan-and-security-baseline.md) — 기존 대상 리전 VPC를 재사용하는 방침, 준수해야 할 사내 보안 운영 원칙, 원본 리전 현황 조사와 이전 우선순위를 정리했다.
  3. [네트워크 Import 실행](./network/cross-region-migration/03-network-import-execution.md) — 대상 리전 VPC 기반 리소스를 state로 편입하고 데이터/컴퓨트를 이관한 뒤, 공유 Bastion VPC까지 같은 방식으로 코드화했다.
  4. [이관 후 발견된 누락과 재검증](./network/cross-region-migration/04-post-migration-gap-and-recheck.md) — "완료"됐던 EC2 이관이 실제로는 Auto Scaling Group 구성을 반영하지 못했다는 지적을 계기로 재조사하고 바로잡았다.
  5. [애플리케이션 헬스체크 근본원인 조사](./network/cross-region-migration/05-application-healthcheck-root-cause.md) — Auto Scaling Group 전환 이후 발생한 헬스체크 실패를 인스턴스 직접 접속으로 조사해 두 가지 근본 원인을 규명했다.
  6. [패치 자동화 후속조치](./network/cross-region-migration/06-patch-automation-followup.md) — 이관 과정에서 발견한 Bastion 인스턴스의 장기 미패치 문제를, 아웃바운드를 다시 열지 않고 Patch Manager로 해결한 과정을 다뤘다.

### [poc](./poc/) — PoC·벤더 검토
솔루션 도입 전 후보 비교·검증

- [DLP 솔루션 도입 평가](./poc/dlp-adoption/) — 후보 조사 → 1차 정량 평가 → 평가 방법론 자체 검증·개정 → 상위 후보 재검증(PoC) → 가격 대비 종합 판단으로 최종 선정

### [security-assessment](./security-assessment/) — 보안 현황 점검
운영 중인 시스템·서비스의 보안 설정 현황을 점검하고 근본원인을 추적하는 프로젝트

- [Slack 워크스페이스 보안 현황 점검](./security-assessment/slack/) — 관리자 콘솔 점검 중 외부 협업 기능이 승인 없이 확산된 구조적 원인을 설정 화면 교차 확인으로 규명하고, 계정 인증 이중화 공백을 함께 찾았다
- [Google Workspace 보안 현황 점검](./security-assessment/gws/) — 점검 시작과 동시에 확인된 관리 권한 제약의 원인을 조직 구조까지 추적하고, 제한된 권한 안에서도 확인 가능한 범위부터 분석해 우선순위 조치안을 보고했다

### [security-policy](./security-policy/) — 보안 정책·체계
법령 개정이나 조직 변화에 따른 보안 정책·통제 체계 수립

- [망분리 완화 및 대체 보호조치 체계 구축](./security-policy/network-separation-relaxation/) — 법령 개정을 계기로 망분리 의무 대상 여부를 법적으로 재검토 → 표준 기반 대체 보호조치 통제영역 도출 → 현황 점검·취약점 식별 → 보완 계획 수립 및 잔여위험 판단
- [제로트러스트 기반 하이브리드 보안 아키텍처 제안](./security-policy/zerotrust-hybrid-architecture/) — 망분리 완화 이후에도 보안 수준을 유지하기 위해, 실제 접속 통제 취약 사례를 근거로 인증·접근 체계를 신원·단말·정책 기반 상시 검증 모델로 재설계할 것을 제안
- [바이브 코딩 보안 가드레일 표준(안) 수립](./security-policy/vibe-coding-guardrails/) — AI 코드 생성 도구 사용 중 생기는 위험 경로(민감정보 노출, 프롬프트 인젝션, 과도한 에이전트 권한 등)를 먼저 정리하고, 경로마다 대응하는 기술적 가드레일과 보안 프롬프트 표준을 매칭해 제안

### [automation](./automation/) — 자동화
반복 업무나 수동 점검을 스크립트·웹앱으로 자동화한 프로젝트

- [인터랙티브 사내 정보보안 교육 웹앱](./automation/security-awareness-training/) — 문서·슬라이드 배포 대신 실습·퀴즈로 진행하는 인터랙티브 교육을 Google Apps Script + HTML/CSS/JS로 개발했다. [인터랙티브 데모](https://heinz-walker.github.io/project/security-training/)
- [전자결재·보안 이벤트 슬랙 알림 봇](./automation/approval-alert-bot/) — 결재 시스템이 보내는 메일을 입력으로 삼아 JSON 규칙 DSL로 매칭하고, 담당자를 멘션한 슬랙 메시지(승인·반려·문서 열기 버튼 포함)로 라우팅했다. 비개발자용 브라우저 규칙 빌더와 오프라인 테스트 하니스를 함께 만들었다.
- [개인정보처리시스템(PIMS) 접속 이력 감사 자동화](./automation/pims-access-review/) — bastion 접속 로그와 게임 서비스 관리툴 로그를 매월 수집·상관분석해, 반복되는 정상 패턴은 규칙 엔진으로 자동 판정하고 사람은 예외만 검토하게 만들었다.
- [클라우드 위험평가 자동화](./automation/cloud-risk-assessment/) — 위험평가 산식(R=A×T×V)의 자산가치 근거인 클라우드 자산대장을 정비하고, 취약성 평가를 boto3 읽기 전용 도구로 자체 개발해 자동 산정 결과와 정식 위험평가 보고서 체계의 정합성을 점검했다.
