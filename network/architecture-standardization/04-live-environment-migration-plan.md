<div align="center">
<h1>Live 환경 표준 가이드 적용 비교 및 계획</h1>
<i>Live Environment Standard Migration Plan</i>
</div>

*2026.07 · 클라우드 네트워크 보안 담당*

---

## 1. 요약
Live VPC에 사내 클라우드 보안 가이드의 네트워크 보안 아키텍처 기준과 Security Group 기준을 적용하기 위한 현황 비교 및 계획이다.
Live는 Dev·Stage와도 시작점이 다르다 — **Network Firewall 관련 리소스가 계정에 아예 존재하지 않아 "0에서 새로 만드는" 작업**이면서, 동시에 실서비스 트래픽이 흐르고 있어 리스크는 Stage에 준한다.
최초 작성 시에는 네트워크 아키텍처 항목만 다뤘으나, 다른 보안 가이드 항목이 빠져 있다는 지적을 받아 Security Group 등 추가 항목의 현황도 함께 조사해 보강했다.
Security Group은 총 33개 중 신규 SG-to-SG 구조 17개가 이미 만들어져 있었지만 실제 ENI가 붙은 것은 1개뿐이었고, 나머지 트래픽은 legacy SG 12개와 계정 `default` SG(ENI 73개 부착)로 흐르고 있어 "컷오버만 남은" 상태로 확인됐다.

---

## 2. 문서 정보
| 항목 | 내용 |
| --- | --- |
| 작성일 | 2026-07-14 |
| 목적 | 사내 클라우드 보안 가이드(§네트워크 보안 아키텍처)와 Live VPC의 실제 구성을 비교하고, 표준 적용을 위한 계획을 수립. 최초 작성 시 네트워크 아키텍처 항목만 다뤘으나, Security Group 등 다른 항목도 빠져 있다는 지적을 받아 8–10절에 추가 조사 결과를 보강함 |
| 확인 방식 | AWS CLI 직접 조회(읽기 전용). 이 세션에서 AWS 리소스는 조회만 했고 생성·수정·삭제는 전혀 하지 않았음 |
| 대상 VPC | Live VPC (`<live-vpc-cidr>`) |
| 실행 주체 | 실제 변경은 담당자가 직접 수행. 본 문서는 비교·계획만 제공 |
| 참고 문서 | 사내 클라우드 보안 가이드(표준 원문), [03. Stage 환경 적용](./03-stage-environment-migration-plan.md)(같은 형식의 stage 사례, 절차 상당 부분 재사용 가능), [01. Dev 환경 진단 및 재구축](./01-dev-environment-migration.md) |

---

## 3. 담당 역할
- Live VPC 네트워크·Security Group 전수 조회 및 표준 대비 Gap 분석
- 워크로드 없이 시작한 Dev, 고아 상태였던 Stage와 또 다른 "0에서 신규 구축" 시나리오의 계획 수립
- 추가 지적사항(Security Group 등)에 대한 후속 조사 및 보강

---

## 4. 결론 — Dev·Stage와도 시작점이 다르다
Live는 Dev(빈 환경에서 표준대로 신축)나 Stage(4-tier로 지어졌다가 라우팅이 끊겨 방치된 상태)와 또 다르다.
**Live는 Network Firewall 관련 리소스가 계정에 아예 존재하지 않는다 — firewall subnet도, Live Firewall도, 정책도, 룰 그룹도 전혀 없다.**
지금은 순수한 2-tier(Public/Private) 구조이고, 그 상태로 실서비스 트래픽(ALB 12개, NLB 3개, RDS 6개, 배포용 EC2 등)이 흐르고 있다.

- Public(`public1`/`public2`)이 route table 하나를 공유하고 있어, AZ별로 다른 firewall endpoint를 지정하는 표준 구조를 적용하려면 stage와 동일하게 분리가 선행되어야 한다.
- Private(`private1`/`private2`)도 NAT Gateway를 하나만 두고 두 AZ가 공유하고 있다 — AZ 장애 격리가 깨진 상태이며, stage의 문제와 동일하다.
- Public tier에는 이미 ALB(12개)와 NLB(3개), NAT Gateway가 공존하고 있어 표준의 "Protected Subnet" 개념에 구조적으로는 가깝다. 다만 route table이 `0.0.0.0/0 → IGW` 직결이라 Firewall을 거치지 않는다(신설해야 거치게 됨).
- Firewall subnet, Firewall 리소스, 정책, 룰 그룹이 모두 존재하지 않는다 — stage처럼 "고아 리소스를 되살리는" 작업이 아니라, dev처럼 "새로 만드는" 작업이다. 다만 dev와 달리 **실서비스 트래픽이 걸려 있어 리스크는 stage에 준한다.**
- VPC Flow Logs 미설정(dev/stage와 동일한 미비점).
- VPC Peering이 5개로 stage(3개)보다 많고, 그중 2개는 이 계정 소유가 아니라 타 계정 리소스라 이름/용도를 이 세션에서는 확인할 수 없었다.

**추가 조사(8절) 요약 — Security Group은 오히려 stage보다 뒤처져 있다.**
Security Group 기준으로 live의 SG 33개를 전수 조회한 결과, stage와 동일한 SG-to-SG 신규 구조(17개)가 **이미 만들어져 있지만 ENI가 1개(CI/CD 러너 인스턴스)만 붙어 있고 나머지는 전부 미사용 상태**였다.
실제 트래픽은 여전히 legacy SG(포트 80/443/8102/33333/33344가 `0.0.0.0/0`에 그대로 열린 상태)와 **계정 `default` SG(무려 ENI 73개에 부착)**로 흐르고 있다.
Network Firewall은 "0에서 새로 만드는" 작업이지만, SG는 "이미 만들어둔 목표 구조로 갈아타기만 하면 되는" 작업이라 우선순위와 리스크 성격이 다르다 — 자세한 내용은 8–9절 참고.

---

## 5. 현재 상태 상세 (AWS CLI 재조회 결과)
### 5.1. Subnet
| Subnet | AZ | CIDR |
| --- | --- | --- |
| public1 | 2a | `<live-public1-cidr>` |
| public2 | 2b | `<live-public2-cidr>` |
| private1 | 2a | `<live-private1-cidr>` |
| private2 | 2b | `<live-private2-cidr>` |

firewall subnet은 존재하지 않는다.
VPC CIDR 중 `<live-firewall1-cidr>`–`<live-firewall2-cidr>` 대역이 비어 있어, stage와 동일한 블록 배치 규칙(public 바로 다음 블록)을 그대로 적용하면 신규 firewall subnet용으로 쓸 수 있다(6절 참고).
subnet 이름은 이미 표준 네이밍 패턴과 정확히 일치하므로 기존 4개는 이름을 바꿀 필요가 없다.

### 5.2. 라우팅 — 실제로 사용 중인 경로
| Route Table | 연결 Subnet | 핵심 라우트 | 실질 의미 |
| --- | --- | --- | --- |
| Live-rtb-public | public1 + public2 둘 다 | `0.0.0.0/0 → IGW` | Public tier 전체가 Firewall 미경유, IGW 직결. AZ별 분리도 안 되어 있음 |
| Live-rtb-private1 | private1 | `0.0.0.0/0 → NAT-A` (public1 소재) + S3 Gateway Endpoint | 같은 AZ(2a)의 NAT을 쓰고 있어 이 부분은 이미 표준과 일치 |
| Live-rtb-private2 | private2 | `0.0.0.0/0 → NAT-A` (public1/AZ-A 소재) + 동일 S3 Endpoint | AZ-B인데 AZ-A(public1)의 NAT을 그대로 참조 — cross-AZ, 표준 위반 |
| (이름 없음, 미연결) | 없음 | `local`만 존재 | 어떤 subnet에도 연결되어 있지 않은 고아 route table. 언제 왜 만들어졌는지는 이 조회만으로 알 수 없음(8.1에서 원인 확인 후 정리 여부 결정 권장) |

모든 route table(고아 table 제외)에 아래 **VPC Peering 라우트 5개**가 걸려 있다(구성은 route table마다 다름 — public은 5개 전부, private1/private2는 이 중 일부만).
마이그레이션 시 실수로 삭제하지 않도록 주의.

| 대상 CIDR | 상대 VPC | 비고 |
| --- | --- | --- |
| `<peered-vpc-a-cidr>` | (외부) | 타 계정 소유 — 이 계정에서 이름/용도 조회 불가 |
| `<peered-office-vpc-cidr>` | 오피스/워크스페이스 VPC | |
| `<peered-vpc-b-cidr>` | (외부) | 타 계정 소유 — 이 계정에서 이름/용도 조회 불가 |
| `<peered-bastion-vpc-cidr>` | Bastion 전용 VPC | |
| `<peered-stage-vpc-cidr>` | Stage VPC | live↔stage 직접 피어링 |

### 5.3. NAT Gateway 실제 배치
| NAT Gateway | 소재 Subnet | 실제 참조하는 곳 |
| --- | --- | --- |
| NAT-A | public1(AZ-A) | private1-rtb, private2-rtb 둘 다 참조(AZ 공유) |

AZ-B 전용 NAT이 없다.
stage와 동일하게 신규 생성이 필요하다.

### 5.4. Public tier 실제 리소스 (ENI 조회 결과)
`public1`/`public2`에 이미 배치되어 있음: ALB(app형) 12개(서비스 A/B/C × 용도별 4종 조합), 각 2개 ENI(AZ별); NLB(net형) 3개(서비스 A/B/C의 실시간 메시징용), 각 2개 ENI; NAT Gateway 1개; RDS 관리형 ENI 3개(Public IP가 없어 실제로는 인터넷에 노출되지 않음.
RDS는 라이브 DB 6종 모두 `PubliclyAccessible: false`로 확인됨.
subnet group이 public+private 4개를 전부 포함하고 있어 ENI가 우연히 public 서브넷 대역에 배치된 것뿐, 실질적 노출 위험은 없음).

Public tier가 이미 "ALB+NAT 공존"이라는 표준의 Protected Subnet 형태에 구조적으로 가깝다는 점은 stage와 동일하다.

### 5.5. Firewall/정책/로깅
| 항목 | 값 |
| --- | --- |
| Firewall | 존재하지 않음(Dev/Stage/오피스 환경 Firewall만 있고 Live에는 없음) |
| 정책 | 존재하지 않음 |
| 룰 그룹 | 존재하지 않음 |
| VPC Flow Logs | 미설정(빈 배열) |

---

## 6. 표준 대비 Gap 분석 (네트워크 아키텍처)
| 가이드 기준 | live 현재 | 상태 |
| --- | --- | --- |
| Firewall endpoint AZ당 1개(primary) | 전혀 없음 | ❌ |
| Public subnet: ALB+NAT 공존 | 이미 충족 | ✅ |
| Public subnet route table: AZ별 독립, `0.0.0.0/0 → firewall vpce` | AZ별 독립 안 됨(public1/2 공유), target도 IGW 직결 | ❌ 이중으로 어긋남 |
| Private subnet route table: `0.0.0.0/0 → 같은 AZ NAT` | NAT 자체는 있으나 AZ-A NAT을 두 AZ가 공유 | ❌ |
| Firewall subnet(3-tier 자체) | 존재하지 않음, 신규 생성 필요 | ❌ |
| IGW ingress routing | 없음 | ❌ |
| Stateful default action: drop | N/A(정책 자체가 없음) | ❌ |
| 로깅: FLOW+ALERT, 환경별 로그 그룹, 대시보드 | 전부 미설정 | ❌ |
| VPC Flow Logs | 미설정 | ❌ |
| 정책/Firewall 리소스 환경별 독립 | 아직 없음 — 신규 생성 시 처음부터 독립적으로 만들면 원칙 자동 충족 | ⚠️ (신규 생성 예정이라 오히려 유리) |
| 네이밍 규칙 | subnet/private-rtb는 이미 패턴 일치. public-rtb는 AZ 미분리라 번호 없음 | ⚠️ 부분 일치 |

---

## 7. 위험 요소
Live는 dev보다 훨씬 리스크가 크고, stage와도 결이 다르다 — **stage는 "이미 있던 정책을 재활용"할 수 있었지만, live는 정책을 처음부터 새로 작성해야 한다.**

1. **Public tier route table 분리가 선행 작업이다.** 지금 하나의 route table을 ALB 12개+NLB 3개가 공유하는 채로 쓰고 있어, 표준(AZ별로 다른 firewall endpoint를 가리켜야 함)을 적용하려면 반드시 먼저 두 개로 쪼개야 한다.
2. **private2의 NAT을 AZ-B 전용으로 새로 만들어야 한다.** 지금 AZ-A의 NAT을 공유 중이라 전환 시 실 트래픽의 순간적인 연결 끊김 가능성이 있다.
3. **Allow-list를 처음부터 작성해야 한다는 점이 stage보다 큰 리스크다.** stage/dev는 기존 정책을 참고할 수 있었지만 live는 참고할 기존 정책이 없다. Public tier route table을 firewall로 전환하는 순간, ALB 12개·NLB 3개·EC2가 사용하는 모든 외부 도메인이 갑자기 검사 대상이 된다. **전환 전에 각 서비스(A/B/C)가 실제로 호출하는 외부 도메인 목록을 애플리케이션단에서 먼저 확보해야 한다** — 이 조사는 AWS 리소스 조회만으로는 안 되고 각 서비스 담당자 확인이 필요하다.
4. **VPC Peering 5개 중 2개는 타 계정 소유라 이 계정에서 어떤 트래픽인지 확인할 수 없다.** route table 작업 시 그 2개 라우트를 실수로 건드리지 않도록 각별히 주의하고, 가능하면 사전에 담당자에게 이 두 피어링의 용도를 확인해 둔다.
5. **이름 없는 고아 route table의 생성 이력을 먼저 확인한다.** 어떤 subnet과도 연결되어 있지 않아 당장 위험하지는 않지만, 정리 대상인지 실수로 남겨진 작업 흔적인지 CloudTrail로 확인 후 판단하는 편이 안전하다(stage 0단계와 동일한 접근).
6. 신규 firewall subnet 2개를 위한 CIDR 확보 자체는 여유 공간이 있어 문제없지만, 실제 생성 시점에 다른 담당자가 같은 대역을 이미 예약해두지 않았는지 재확인 필요.

---

## 8. 진행 계획 (초안 — 실제 수행은 담당자가 직접)
Stage 절차([03](./03-stage-environment-migration-plan.md) 9절)와 뼈대는 같지만, live는 firewall subnet 자체가 없어 "새로 만드는" 단계가 하나 더 필요하다.
아래는 콘솔 조작 순서의 초안이며, 본 세션에서는 실행하지 않았다.

**주의**: public1/public2에 이미 실서비스 트래픽(ALB 12개, NLB 3개)이 흐르고 있으므로, 아래 8.4–8.6단계는 트래픽이 적은 시간대(새벽 등)에 진행하는 것을 권장.

### 8.1. 원인 확인 및 사전 조사
1. 고아 route table의 CloudTrail 생성 이력을 확인해, 정리 대상인지 판단 재료를 확보한다.
2. 타 계정 소유 피어링 2건(`<peered-vpc-a-cidr>`, `<peered-vpc-b-cidr>`)의 실제 용도를 담당자에게 확인한다(타 계정 소유라 이 계정에서는 조회 불가).
3. 서비스 A/B/C 각 담당자에게 **실제로 외부로 호출하는 도메인 목록**(결제, 푸시, 로그 수집, 3rd-party API 등)을 받아 향후 만들 Live Policy allow-list 초안에 반영할 준비를 한다 — 8.4 진행 전 필수 선행 작업.

### 8.2. Firewall Subnet 2개 신규 생성
1. VPC 콘솔 → Subnets → Create subnet
2. Live VPC 선택 → subnet 2개 추가: firewall1(AZ-A, `<live-firewall1-cidr>`), firewall2(AZ-B, `<live-firewall2-cidr>`)
3. 각 subnet용 route table 생성(일단 라우트는 비워둠 — 8.7에서 채움)

### 8.3. Network Firewall 리소스 신규 생성
1. Network Firewall 콘솔 → Firewall policies → Create firewall policy
   - Stateless default actions: forward to stateful
   - Stateful engine options: Strict evaluation order
   - Stateful default actions: 최초엔 `aws:alert_established`로 시작(dev/stage와 동일한 안전한 전개 순서 — 8.11에서 drop으로 전환)
2. Rule groups → domain allow-list 룰 그룹 신규 생성(`RulesSourceList`/`TargetTypes: [HTTP_HOST, TLS_SNI]`/`GeneratedRulesType: ALLOWLIST`) — 8.1에서 받은 도메인 목록으로 초안 작성
3. 위 룰 그룹을 정책에 연결(Priority 1)
4. Create firewall → VPC: Live VPC, 정책 연결, 서브넷 매핑: firewall1(AZ-A)/firewall2(AZ-B) 각각 선택 → READY/IN_SYNC 될 때까지 대기

### 8.4. Public tier route table 분리
Stage 절차와 동일한 절차.
public2용 신규 route table을 만들어 기존 route table과 동일한 라우트(피어링 5개 포함)를 복제하고, public2 subnet association만 옮긴다.
기존 route table은 public1 전용임을 명확히 하도록 이름 변경.
**이 단계는 라우트를 그대로 복제하는 것이라 트래픽 영향이 없어야 정상.**

### 8.5. AZ-B 전용 NAT 신규 생성
Stage 절차와 동일한 절차.
public2 subnet에 신규 NAT 생성 후, private2 route table의 `0.0.0.0/0` target을 새 NAT으로 교체.
**이 순간 private2의 실 서비스 트래픽이 전환되며 순간 끊김 가능 — 전환 직후 즉시 정상 동작 확인.**

### 8.6. Public tier route table을 firewall primary endpoint로 전환
**가장 리스크가 큰 단계.**
public1 route table의 `0.0.0.0/0` target을 IGW → firewall1 endpoint로, 이어서 public2 route table도 동일하게 firewall2 endpoint로 전환.
각 단계마다 ALB 12개/NLB 3개의 정상 동작을 즉시 확인하고, 문제가 있으면 즉시 IGW로 롤백.

### 8.7. Firewall subnet route table 구성
firewall1/firewall2 route table의 `0.0.0.0/0`을 각각 IGW로 설정(검사 완료된 트래픽을 인터넷으로 내보내는 마지막 hop).

### 8.8. IGW Ingress Route Table 신규 생성
Stage 절차와 동일한 절차.
신규 route table 생성 → Edge associations에 IGW 연결 → public1 CIDR → firewall1 endpoint, public2 CIDR → firewall2 endpoint 라우트 추가.
**저장 직후 반드시 CLI로 재확인**([02. Return Path 설계 원칙](./02-return-path-design-principle.md), [03](./03-stage-environment-migration-plan.md) 9.4에서 실제로 저장 누락 사고가 있었던 단계 — 콘솔 화면만 믿지 말 것):
```bash
aws ec2 describe-route-tables --route-table-ids <igw-ingress-rtb-id> \
  --query 'RouteTables[0].Associations'
```

### 8.9. 로깅 구축
1. CloudWatch 콘솔 → Log groups → `/aws/network-firewall/live/flow`(retention 30일), `/aws/network-firewall/live/alert`(retention 180일) 생성
2. Network Firewall 콘솔 → Live Firewall → Logging → Flow/Alert 로그 둘 다 위 로그 그룹으로 연결
3. Monitoring dashboard 활성화
4. (별도) VPC Flow Logs도 Live VPC에 신규 활성화 — Private tier 트래픽 가시성 확보용

### 8.10. 검증
1. ALB/NLB 콘솔에서 전체 Target group health 확인
2. 서비스 A/B/C 각 로그에서 외부 API 호출 실패 여부 확인
3. alert 로그 그룹 Insights 조회로 allow-list 미등록 도메인(ALERT) 존재 여부 확인 → 정상 트래픽이면 allow-list에 추가, 비정상이면 원인 조사

### 8.11. (향후) Stateful default action을 drop으로 전환
8.10에서 최소 수일간 문제 없음을 확인한 뒤에만 진행.

---

## 9. Live·Dev·Stage 비교 요약
| | Dev | Stage | Live |
| --- | --- | --- | --- |
| 시작 시점 워크로드 | 0건 | ALB 15개+, NLB 3개, EC2 다수 | ALB 12개, NLB 3개, RDS 6개(public IP 없음), 배포용 EC2 등 |
| Firewall subnet/리소스 | 신축(원래 모델) | 4-tier로 지어졌으나 고아 상태 | 아예 존재하지 않음(0부터 생성) |
| Firewall 정책/allow-list | 신규 작성 | 기존 정책 재활용 가능 | 재활용할 기존 정책 없음 — 완전 신규 작성 필요 |
| Public tier route table | AZ별 독립 | AZ 공유(선분리 필요) | AZ 공유(선분리 필요) |
| Private tier NAT | AZ별 독립 | AZ 공유, firewall 완전 미경유 | AZ 공유, firewall 완전 미경유 |
| VPC Peering | 없음 | 3개(live/bastion/오피스) | 5개(stage/bastion/오피스 + 타 계정 2개, 그중 2개는 이 계정에서 조회 불가) |
| VPC Flow Logs | - | 미설정 | 미설정 |
| 마이그레이션 리스크 | 낮음 | 높음(실서비스) | 높음(실서비스) + allow-list 사전조사 부담까지 추가 |

---

## 10. Security Group 대비 현재 상태 및 Gap 분석
### 10.1. SG 인벤토리 — legacy·신규·공용 3계열이 공존
Live VPC에 SG가 총 33개 있다.
이름 패턴으로 나누면 3계열이다.

| 계열 | 개수 | ENI 부착 현황 |
| --- | ---: | --- |
| A. 신규 SG-to-SG 구조 | 17개 | 거의 전부 0개(유일하게 CI/CD 러너 인스턴스 전용 SG만 1개) — Stage의 동일 계열 17개와 이름·규칙 구조가 정확히 동일 |
| B. legacy 구조(접미사 없음) | 12개 | 전부 실사용 중(SG별로 4–45개, 합산 시 최대 45개) — 실제 프로덕션 트래픽은 지금 이 계열로 흐르고 있다 |
| C. 계정 기본/공용 | 4개 | `default`(73개!), 미사용 SG 1개, 공용 배포용 SG 2개 |

즉 **누군가 이미 stage와 동일한 SG-to-SG 목표 구조(A계열)를 live에도 만들어 뒀지만, 실제 인스턴스/ALB/NLB는 여전히 legacy(B계열)와 계정 `default`(C계열)에 붙어 있는 "절반만 진행된 마이그레이션" 상태다.**

### 10.2. 주요 리스크 상세
| SG | 규칙 | 부착 ENI | 문제 |
| --- | --- | ---: | --- |
| `default` | 인바운드: 전체 프로토콜 <- 자기 자신 | 73개 | Default Security Group 미사용 권고 정면 위반. 규칙 자체는 "같은 SG를 가진 대상끼리 전체 허용"이라 당장 인터넷에 열린 건 아니지만, `default`를 공유하는 73개 리소스 중 서로 통신할 이유가 없는 것들끼리도 전체 포트가 뚫려 있다는 뜻 |
| 미사용 SG(launch wizard 자동생성) | 인바운드: TCP 22 <- 0.0.0.0/0 | 0개(미사용) | EC2 콘솔에서 인스턴스를 띄울 때 자동 생성되는 SG. 기본 포트 22 사용 금지 기준 위반이지만 현재 아무 ENI에도 안 붙어 있어 실질 위험은 없음 — 즉시 삭제해도 안전한 대상 |
| legacy HTTP SG | 인바운드: TCP 80/443/8102 <- 0.0.0.0/0 | 45개 | 여러 서비스의 퍼블릭 HTTP(S) 진입점이 SG 하나에 뭉쳐 있음 — 용도별 구분 기준 위반. Stage는 서비스·용도별로 쪼개져 있는 것과 대비됨 |
| legacy GW HTTP/UDP SG | TCP 33333/33344, UDP 33334 <- 0.0.0.0/0 | 15개씩 | 신규 SG가 이미 동일한 인바운드 규칙으로 만들어져 있음 — 그대로 대체 가능한 상태인데 아직 컷오버되지 않음 |
| legacy Office SG | TCP 80/443 <- 고정 IP 2개 | 4개 | 오피스 고정 IP 2곳에서 직접 접근 — ALB/Bastion을 거치지 않는 예외 경로. 용도(어떤 서비스의 관리 콘솔인지) 확인 필요 |
| legacy Admin SG | 인바운드 규칙 없음(빈 SG) | 34개 | 34개 ENI에 붙어 있지만 그 자체로는 아무 것도 허용하지 않음 — 다른 SG와 같이 붙어 실질 접근은 다른 SG가 담당하는 것으로 보이나, 빈 SG를 34개나 붙여두는 것 자체가 관리 부담. 정리 대상 후보 |

참고로 Bastion↔배포 전용 SG 2종은 고정 IP 기반으로 타이트하게 관리되고 있어 문제로 보지 않았다 — Stage에서 확인했던 것과 동일한 IP 기준이라, Live와 Stage가 같은 Bastion을 공유하는 것으로 보인다.

### 10.3. Gap 분석 표
| 가이드 기준 | live 현재 | 상태 |
| --- | --- | --- |
| Default SG 미사용(삭제 권고) | ENI 73개 부착, 실사용 중 | ❌ (stage는 미사용이었던 것과 대비 — live가 더 심각) |
| SG-to-SG 기반 접근제어 표준화 | 목표 구조(A계열 17개)는 이미 존재하나 미적용, 실트래픽은 legacy(B계열)로 흐름 | ❌ (구조는 준비됐고 컷오버만 남음) |
| SSH 특정 포트만 사용, 기본 포트 미사용 | 신규 A계열은 전부 준수. 다만 미사용 SG 1개가 기본 포트를 세계에 개방(미사용) | ⚠️ 사용 중인 리소스는 준수, 잔존 SG 정리 필요 |
| 용도별 SG 구분 | legacy B계열이 여러 서비스를 한 SG에 뭉쳐놓음 | ❌ |
| 사용자 접근 프로토콜 통제 | Office SG처럼 고정 IP 기반 접근은 있으나, 나머지 legacy SG는 전면 개방(ALB 성격상 불가피한 면 있음) | ⚠️ |

---

## 11. Security Group 정리 계획(초안)
Network Firewall(6–8절)은 "0에서 새로 만드는" 작업이었지만, SG는 **목표 구조가 이미 존재하므로 "컷오버 + 정리"가 핵심**이다.
아래는 절차 초안이며 이번 세션에서는 실행하지 않았다.

1. **매핑표 작성**: legacy SG 12개 각각이 어떤 신규 SG로 대체되는지 1:1 대응표를 먼저 만든다. ENI 조회 결과와 규칙 내용을 대조해 이미 상당 부분 유추 가능하지만, 여러 서비스가 뭉쳐 있는 legacy SG는 신규 쪽에서 몇 개로 쪼개지는지 정확히 확인해야 한다.
2. **점진적 cut-over(교체 아닌 추가부터)**: 각 ENI에 신규 SG를 **추가로** 붙이고(기존 legacy SG는 유지한 채 다중 SG 상태로 둠) 정상 동작을 확인한 뒤, 문제없을 때만 legacy SG를 제거한다. 한 번에 legacy → 신규로 바꿔치기하지 않는다 — SG는 EC2/ALB/NLB 콘솔 또는 API에서 대상별로 개별 작업해야 하므로 대상이 많을수록(특히 45개 붙은 legacy HTTP SG) 실수 여지가 크다.
3. **이미 준수 중인 공용 SG(Bastion↔배포 전용 2종)는 그대로 유지**한다 — 신규 구조로 별도 전환할 필요 없음.
4. **정리(cleanup)**: 모든 ENI가 신규 SG로 전환된 것을 확인한 뒤 legacy SG 12개, 빈 Admin SG, 미사용 SG 삭제. `default` SG는 삭제할 수 없으므로 **모든 ENI에서 명시적으로 detach**(대신 신규 SG 부착)하는 방식으로 정리한다.
5. **검증**: 전환 각 단계마다 대상 서비스(A/B/C)의 정상 동작을 확인하고, ALB/NLB는 Target group health로 확인한다.

**우선순위 제안**: 미사용 SG(0단계, 즉시 삭제 가능·무위험) → GW HTTP/UDP SG(신규 쪽이 이미 동일 규칙이라 가장 간단) → 나머지 legacy 순.
`default`는 부착 범위가 가장 넓어(73개) 마지막에 가장 신중하게 진행 권장.

---

## 12. 그 외 가이드 항목 확인 결과
Network Firewall·SG 작업과 직접 관련된 항목만 추가로 확인했다.
EC2 네이밍/IAM/패스워드/접근통제/사용자 인증 항목은 AWS 네트워크 리소스 조회만으로는 검증할 수 없는 항목이라 이번 조사 범위에서 제외했다.

| 가이드 기준 | live 현재 | 상태 |
| --- | --- | --- |
| VPC 네이밍 | 기존에 이미 보고된 문서-현실 불일치 이슈, live 고유 이슈 아님 | ⚠️ |
| Subnet 네이밍 | 4개 전부 패턴과 정확히 일치 | ✅ |
| Bastion Host 사용 원칙 | live도 stage와 동일하게 계정 자체 bastion(오피스 VPC 소재)을 사용 — 공용 bastion 아님 | ⚠️ (stage 검토 때와 동일한 기존 이슈, live 신규 이슈 아님) |
| 자산 식별 체계(SG 네이밍) | 신규 A계열 SG 17개는 패턴 일치. legacy B계열과 미사용 SG는 불일치 | ❌ (10절과 동일 사안) |

---

## 13. 성과 및 배운 점
- Network Firewall 관련 리소스가 0개(firewall subnet·정책·룰 그룹 전무)인 환경에 대해 신규 구축 계획을 처음부터 수립했고, 참고할 기존 정책이 없다는 제약을 allow-list 사전조사 절차로 보완했다.
- 요청받은 항목(네트워크 아키텍처)만 조사하고 끝내지 않고 관련 가이드 전체를 다시 훑어, SG 33개 중 신규 구조 17개는 이미 만들어졌으나 ENI가 1개만 붙어 있고 실제 트래픽은 legacy SG 12개와 계정 `default` SG(ENI 73개 부착)로 흐르고 있다는 Security Group 영역의 Gap을 스스로 찾아냈다.
- Dev/Stage에서 정립한 절차와 교훈([01](./01-dev-environment-migration.md), [02](./02-return-path-design-principle.md), [03](./03-stage-environment-migration-plan.md))을 재사용해, 환경마다 다른 시작 조건에도 일관된 방법론으로 접근할 수 있었다.

---
*회사명, 계정/리소스 식별자(계정 ID, VPC/Subnet/NAT/Endpoint/Peering/SG ID, 공인 IP 등), 내부 서비스명 등은 포함하지 않았습니다.*
