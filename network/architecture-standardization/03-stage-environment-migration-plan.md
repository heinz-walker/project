<div align="center">
<h1>Stage 환경 표준 가이드 적용 비교 및 계획</h1>
<i>Stage Environment Standard Migration Plan</i>
</div>

*2026.07 · 클라우드 네트워크 보안 담당*

---

## 1. 요약
실서비스 트래픽이 흐르는 Stage VPC에 회사 표준 아키텍처를 적용하기 위한 현황 비교 및 실행 계획이다.
Dev와 달리 Stage는 Network Firewall 리소스가 이미 배포되어 있음에도 실제 라우팅상 어떤 트래픽도 이 Firewall을 거치지 않는 "떠 있지만 아무것도 검사하지 않는" 상태였다.
실서비스 트래픽에 대한 리스크를 고려해 단계별 전환 계획을 수립했고, [02. Return Path 설계 원칙](./02-return-path-design-principle.md)에서 정리한 원칙을 점검 항목에 반영했다.

---

## 2. 문서 정보
| 항목 | 내용 |
| --- | --- |
| 작성일 | 2026-07-07 |
| 목적 | 회사 표준 아키텍처와 Stage VPC의 실제 구성을 비교하고, 표준 적용을 위한 계획 수립 |
| 확인 방식 | AWS CLI 직접 조회(읽기 전용). 이 세션에서 AWS 리소스는 조회만 했고 변경하지 않았음 |
| 대상 VPC | Stage VPC (`<stage-vpc-cidr>`) |
| 실행 주체 | 실제 변경은 담당자가 직접 수행. 본 문서는 비교·계획 제공 |

---

## 3. 담당 역할
- Stage VPC 실제 라우팅 전수 조회 및 표준 대비 Gap 분석
- 실서비스 트래픽 리스크를 고려한 단계별 전환 계획 수립
- 과거 장애 사례([02](./02-return-path-design-principle.md))를 반영한 점검 절차 설계

---

## 4. 결론 — Dev와 시작점이 다르다
Dev는 "토폴로지는 맞는데 정책/로깅이 미비"한 상태에서 출발해 표준 모델로 전환했다.
**Stage는 이보다 근본적인 문제가 있다 — Network Firewall 리소스는 정상 배포되어 있고 정책도 IN_SYNC 상태지만, 실제 라우팅상 어떤 트래픽도 이 Firewall을 거치지 않는다.**
즉 지금 Stage에서 Network Firewall은 "떠 있지만 아무것도 검사하지 않는" 상태다.

- `private1`/`private2`의 `0.0.0.0/0`이 firewall endpoint가 아니라 `public1`에 있는 별도 NAT Gateway(NAT-A)로 직결되어 있다.
- 이 NAT Gateway 하나를 AZ-A(private1)와 AZ-B(private2)가 공유하고 있다 — AZ 장애 격리가 깨진 상태(AZ-A 장애 시 private2도 인터넷 접근 불가).
- `firewall1`/`firewall2`(primary endpoint)와 `external1`/`external2`(NAT 전용 tier, 별도 NAT 2개 보유)는 현재 아무 트래픽도 참조하지 않는 것으로 보인다 — 과거 distributed model로 설계된 흔적이지만 지금은 고아 상태.
- `public1`/`public2`는 이미 ALB(다수)·NAT·EC2가 공존하고 있어 구조적으로는 표준의 "Protected Subnet" 개념에 가깝지만, route table이 `0.0.0.0/0 → IGW` 직결이라 Firewall을 거치지 않는다.
- `public1`/`public2`가 하나의 route table을 공유 — 표준(AZ별 독립 route table, AZ마다 다른 firewall endpoint 지정)과 구조적으로 맞지 않음.
- FLOW/ALERT 로깅 미설정, Stateful default action `aws:alert_established`(dev와 동일한 미비점).

---

## 5. 현재 상태 상세 (AWS CLI 재조회 결과)
### 5.1. Subnet
| Subnet | AZ | CIDR |
| --- | --- | --- |
| public1 | 2a | `<stage-public1-cidr>` |
| public2 | 2b | `<stage-public2-cidr>` |
| firewall1 | 2a | `<stage-firewall1-cidr>` |
| firewall2 | 2b | `<stage-firewall2-cidr>` |
| external1 | 2a | `<stage-external1-cidr>` |
| external2 | 2b | `<stage-external2-cidr>` |
| private1 | 2a | `<stage-private1-cidr>` |
| private2 | 2b | `<stage-private2-cidr>` |

Dev의 마이그레이션 이전 구조(4-tier)와 subnet 이름·개수는 동일하다.
문제는 라우팅이다.

### 5.2. 라우팅 — 실제로 사용 중인 경로
| Route Table | 연결 Subnet | 핵심 라우트 | 실질 의미 |
| --- | --- | --- | --- |
| Stage-rtb-public | public1 + public2 둘 다 | `0.0.0.0/0 → IGW` | Public tier 전체가 Firewall 미경유, IGW 직결 |
| Stage-rtb-private1 | private1 | `0.0.0.0/0 → NAT-A` | firewall1을 거치지 않고 public1의 NAT으로 직결 |
| Stage-rtb-private2 | private2 | `0.0.0.0/0 → NAT-A` | AZ-B인데 AZ-A(public1)의 NAT을 그대로 참조 — cross-AZ |
| Stage-rtb-firewall1 | firewall1 | `0.0.0.0/0 → 고아 NAT-A`(external1 소재) | 이 경로로 들어오는 트래픽 자체가 없어 보임(고아) |
| Stage-rtb-firewall2 | firewall2 | `0.0.0.0/0 → 고아 NAT-B`(external2 소재) | 위와 동일, 고아 |
| Stage-rtb-external1 | external1 | `0.0.0.0/0 → IGW` (+ return: `<stage-private1-cidr> → Endpoint-A`) | firewall1 경유 트래픽이 없으므로 이 return path도 미사용 |
| Stage-rtb-external2 | external2 | `0.0.0.0/0 → IGW` (+ return: `<stage-private2-cidr> → Endpoint-B`) | 위와 동일 |

또한 모든 route table에 Live VPC(`<external-vpc-a-cidr>`), Bastion 전용 VPC(`<external-vpc-b-cidr>`), 사내 오피스 VPC(`<external-vpc-c-cidr>`)로 향하는 **VPC Peering 라우트**가 걸려 있다.
dev에는 없던 것으로, 마이그레이션 시 이 라우트들을 건드리지 않도록 주의가 필요하다.

### 5.3. NAT Gateway 실제 배치
| NAT Gateway | 소재 Subnet | 실제 참조하는 곳 |
| --- | --- | --- |
| 고아 NAT-A | external1(AZ-A) | firewall1-rtb만 참조(고아 — 실제 트래픽 없음) |
| 고아 NAT-B | external2(AZ-B) | firewall2-rtb만 참조(고아 — 실제 트래픽 없음) |
| NAT-A | public1(AZ-A) | private1-rtb, private2-rtb 둘 다 참조(AZ 공유, 실사용 중) |

### 5.4. Public tier 실제 리소스 (ENI 조회 결과)
`public1`/`public2`에 이미 배치되어 있음: ALB 약 15개(interface ENI), NLB 3개, 이름 없는 EC2 ENI 다수(서비스 A/B/C의 stage 인스턴스, 공인 IP 보유), NAT Gateway 1개.
즉 **public tier가 이미 "ALB+NAT 공존"이라는 표준의 Protected Subnet 형태에 구조적으로 가깝다** — 다만 Firewall을 안 거칠 뿐이다.

### 5.5. Firewall/정책/로깅
| 항목 | 값 |
| --- | --- |
| Firewall endpoint | AZ당 1개(primary), 둘 다 READY. 하지만 5.2절대로 아무도 참조하지 않음 |
| 정책 | Stage Policy, IN_SYNC |
| Stateful default action | `aws:alert_established`(차단 아님, dev와 동일 미비점) |
| 로깅 | FLOW/ALERT 전부 미설정(`LogDestinationConfigs: []`) |
| IGW ingress routing | 없음 |

---

## 6. 표준 대비 Gap 분석
| 가이드 기준 | stage 현재 | 상태 |
| --- | --- | --- |
| Firewall endpoint AZ당 1개(primary) | 충족(2개 존재) | ✅ |
| Public subnet: ALB+NAT 공존 | 이미 충족 | ✅ |
| Public subnet route table: AZ별 독립, `0.0.0.0/0 → firewall vpce` | AZ별 독립도 안 됨(public1/2 공유), target도 IGW 직결 | ❌ 이중으로 어긋남 |
| Private subnet route table: `0.0.0.0/0 → 같은 AZ NAT` | NAT은 맞는데 "같은 AZ"가 아니라 AZ-A NAT을 공유 | ❌ |
| Firewall subnet route table: `0.0.0.0/0 → igw` | 설정은 있으나 위 문제로 무의미(고아) | ⚠️ |
| IGW ingress routing | 없음 | ❌ |
| Stateful default action: drop | alert(미차단) | ❌ |
| 로깅: FLOW+ALERT, 환경별 로그 그룹, 대시보드 | 전부 미설정 | ❌ |
| 정책/Firewall 리소스 환경별 독립 | Stage Policy를 dev와 공유 중(stage가 소유주) | ⚠️ 원칙에 안 맞으나 stage가 원본이라 dev 쪽에서 정리할 문제 |

---

## 7. 위험 요소 (Dev 마이그레이션과 결정적으로 다른 점)
Dev는 워크로드가 전혀 없는 빈 환경이라 리스크가 낮았다.
Stage는 **이미 실사용 중인 ALB 15개, NLB 3개, EC2 인스턴스가 public tier에 떠 있고**, 서비스 트래픽이 실시간으로 흐르고 있다고 가정해야 한다.

1. **public1/public2 route table 분리가 선행 작업이다.** 지금 하나의 route table을 공유하는데, 표준(AZ별로 다른 firewall endpoint를 가리켜야 함)을 적용하려면 반드시 먼저 두 개로 쪼개야 한다. 이 자체가 이미 트래픽이 흐르는 subnet의 route table을 교체하는 작업이라 신중해야 한다.
2. **private2의 NAT을 AZ-B 전용으로 새로 만들어야 한다.** 지금 AZ-A의 NAT을 공유하고 있어 표준에 맞추려면 새 NAT이 필요하고, 이는 dev와 마찬가지로 EIP 재사용을 검토해야 하지만 이번엔 실제 서비스 트래픽이 이 NAT을 쓰고 있어 전환 시 순간적인 연결 끊김이 발생할 수 있다.
3. **public1/public2의 route table을 IGW 직결에서 firewall vpce로 바꾸면, 지금 검사받지 않던 ALB·EC2의 아웃바운드가 갑자기 도메인 allow-list 검사 대상이 된다.** 정책(Stage Policy)의 allow-list에 이 서비스들이 실제로 쓰는 도메인이 다 등록되어 있는지 사전 검증이 필수다(현재 default action이 alert라 즉시 차단되진 않지만, 12절 향후 과제대로 drop 전환 시 문제가 될 수 있음).
4. **"왜 firewall1/firewall2가 트래픽을 못 받고 있었는지"는 별도로 파악해야 한다.** 단, 이건 external1/external2를 지울지 말지를 결정하는 문제가 아니다 — 새 표준(3-tier, External 개념 없음)에서 external1/external2는 어떤 이유로 고아가 됐든 상관없이 최종적으로 불필요하다(9.5절, 확정). 이 조사가 필요한 진짜 이유는, 누군가 의도적으로 firewall을 우회했던 거라면(예: allow-list가 특정 트래픽을 막아서 임시로 돌아간 것) 9.3(public tier를 firewall로 전환)에서 그 트래픽이 다시 막힐 수 있기 때문이다 — 즉 조사 결과는 "지울지 말지"가 아니라 "9.3 전환 시 뭘 대비해야 하는지"에 쓰인다.
5. VPC Peering 라우트(live/bastion/오피스) 3개는 이번 마이그레이션과 무관하므로 각 route table 작업 시 실수로 삭제하지 않도록 주의.

---

## 8. 관련 리소스 값 정리
| 항목 | 값 |
| --- | --- |
| VPC | Stage VPC |
| IGW | Stage IGW |
| public1(AZ-A) | Stage public1 subnet |
| public2(AZ-B) | Stage public2 subnet |
| 현재 공유 중인 public route table | Stage-rtb-public, public1/public2 둘 다 연결됨 |
| firewall1(AZ-A) endpoint | Endpoint-A, route table Stage-rtb-firewall1 |
| firewall2(AZ-B) endpoint | Endpoint-B, route table Stage-rtb-firewall2 |
| private1(AZ-A) | route table Stage-rtb-private1 |
| private2(AZ-B) | route table Stage-rtb-private2 |
| 기존 공유 NAT(AZ-A, public1 소재) | NAT-A, EIP-A — private1이 계속 쓸 것 |
| 고아 NAT(external1, AZ-A) | 고아 NAT-A, EIP-B |
| 고아 NAT(external2, AZ-B) | 고아 NAT-B, EIP-C — 이 EIP를 재사용해 public2용 신규 NAT을 만든다 |
| Gateway VPC Endpoint 관련 | S3/DynamoDB 추정 Gateway Endpoint 2개, 아래 9.1에서 재associate 필요 |

**주의**: private1/private2에 이미 실서비스 트래픽이 흐르고 있으므로, 9.2·9.3은 트래픽이 적은 시간대(새벽 등)에 진행하는 걸 권장한다.

---

## 9. 진행 계획 (콘솔 조작 상세)
아래 단계를 진행하기 전에 원인 확인이 필수다 — "지울지 말지"가 아니라 "전환 시 뭐가 터질지"를 대비하기 위함이다.
1. CloudTrail 또는 변경 이력에서 firewall1/firewall2/private1/private2 route table의 과거 `ReplaceRoute`/`CreateRoute` 이벤트를 조회해, 언제 private tier가 firewall 경유에서 NAT-A 직결로 바뀌었는지 확인한다.
2. 담당자에게 "이 변경이 의도적 우회였는지"를 확인한다. 의도적이었다면(예: allow-list가 특정 API 도메인을 막아서 급하게 우회) 그 도메인을 9.3 진행 전에 미리 Stage Policy의 allow-list에 추가해둔다.
3. **이 조사 결과와 무관하게 external1/external2는 9.5에서 확정적으로 삭제한다** — 새 표준에 External tier 개념 자체가 없기 때문.

### 9.1. Public tier route table 분리
지금 public1/public2가 route table 하나를 같이 쓰고 있어서, AZ마다 다른 firewall endpoint를 지정하는 게 불가능하다.
public2를 위한 새 route table을 만들어 옮긴다.

1. VPC 콘솔 → Route Tables → Create route table
2. 새 route table 생성, VPC: Stage VPC
3. 새로 만든 route table 선택 → Routes 탭 → Edit routes → 아래 라우트를 기존 공유 route table과 동일하게 추가: `0.0.0.0/0 → IGW`, VPC Peering 라우트 3개(local route는 자동 생성)
4. Subnet associations 탭 → Edit subnet associations → public2 체크 → Save (이 순간 public2가 기존 공유 route table에서 자동으로 분리됨)
5. VPC 콘솔 → Endpoints → Gateway VPC Endpoint 선택 → Route tables 탭 → Manage route tables → 새로 만든 route table 체크 → Modify route tables (Gateway VPC Endpoint는 라우트를 직접 추가하는 게 아니라 이렇게 route table을 endpoint에 연결해야 prefix-list 라우트가 자동 삽입됨)
6. (선택) 기존 route table의 이름을 public1 전용임을 명확히 하도록 변경
7. 이 단계는 라우트 내용을 그대로 복제한 것이라 트래픽 영향이 없어야 정상이다. 완료 후 public1/public2에서 서비스 정상 동작 확인.

### 9.2. AZ-B 전용 NAT 신규 생성 (기존 고아 EIP 재사용)
먼저 고아 NAT-B를 삭제해 EIP-C를 확보한다.
이 NAT은 원인 확인 과정에서 이미 확인했듯 아무 트래픽도 안 받고 있어 즉시 삭제해도 안전하다.

1. VPC 콘솔 → NAT Gateways → 고아 NAT-B 체크 → Actions → Delete NAT gateway → 확인 팝업에 `delete` 입력 → Delete
2. `Deleted` 상태 될 때까지 대기(1–2분). EIP-C는 Elastic IPs 메뉴에서 "Unassociated" 상태로 남아있음(자동 반납 안 됨)
3. VPC 콘솔 → NAT Gateways → Create NAT gateway
4. **Subnet**: public2
5. **Connectivity type**: Public
6. **Availability mode**: Zonal(기본값 유지 — AZ별 독립 NAT을 만드는 것이므로 Regional 선택하지 않음)
7. **Elastic IP allocation ID**: EIP-C 선택 — 새로 할당하지 말 것
8. Create NAT gateway → `Available` 될 때까지 대기(수 분). 생성된 새 NAT을 신규 NAT-B로 표기
9. VPC 콘솔 → Route Tables → private2 route table 선택 → Routes 탭 → Edit routes
10. `0.0.0.0/0` 행의 Target을 NAT-A → 신규 NAT-B로 변경 → Save changes
11. **이 순간 private2의 실제 서비스 트래픽이 새 NAT으로 전환되며 기존 연결이 끊길 수 있다.** 전환 직후 private2의 애플리케이션(서비스 A/B/C 관련 워크로드)이 정상적으로 외부 통신하는지 즉시 확인.

### 9.3. Public tier route table을 firewall primary endpoint로 전환
**가장 리스크가 큰 단계** — 지금까지 Firewall을 전혀 안 거치던 ALB 15개+, NLB 3개, EC2 인스턴스의 아웃바운드가 여기서부터 실제로 검사받기 시작한다.

1. VPC 콘솔 → Route Tables → public1 전용 route table → Routes 탭 → Edit routes
2. `0.0.0.0/0` 행의 Target을 IGW → Network Firewall Endpoint 카테고리에서 Endpoint-A(firewall1) 선택 → Save changes
3. 즉시 public1의 ALB/EC2들이 정상 동작하는지 확인(외부 API 호출, health check 등). 문제 있으면 즉시 target을 원래 IGW로 롤백.
4. 문제없음을 확인한 뒤 public2 전용 route table도 동일하게: `0.0.0.0/0` target을 IGW → Endpoint-B(firewall2)로 변경 → Save changes
5. public2 쪽도 동일하게 즉시 확인.

### 9.4. IGW Ingress Route Table 신규 생성
1. VPC 콘솔 → Route Tables → Create route table
2. 생성된 route table 선택 → Edge associations 탭 → Edit edge associations → Internet Gateway: Stage IGW 체크 → Save
3. 같은 route table → Routes 탭 → Edit routes → Add route 2개:
   - Destination: public1 CIDR → Target: Endpoint-A
   - Destination: public2 CIDR → Target: Endpoint-B
4. Save changes

**⚠️ 실제로 발생했던 장애 — 3번의 Edge association 저장이 반영 안 될 수 있음**

실제 stage 적용 중, route table과 4번의 라우트 2개는 정상 생성됐지만 **3번의 IGW Edge association 저장이 누락된 채로 넘어간 사고가 있었다.**
겉보기엔 절차를 다 따른 것 같아도 콘솔에서 저장이 실제로 반영 안 될 수 있다는 뜻이다.

증상: private tier(private1/private2) 전체의 인터넷 아웃바운드가 도메인과 무관하게 전부 connection timeout.
NAT→firewall 방향(나가는 길)은 정상 작동해서 FLOW 로그에는 다른 트래픽이 정상적으로 찍히는데, 특정 연결만 골라서 안 되는 게 아니라 새로 시도하는 연결 전체가 타임아웃되는 형태로 나타났다.
원인은 나가는 길은 firewall1을 거치는데 돌아오는 길은 ingress redirect가 없어서 firewall을 안 거치는 **비대칭 라우팅**([02. Return Path 설계 원칙](./02-return-path-design-principle.md) 참고) — Network Firewall(GWLB 기반)은 왕복이 같은 endpoint를 지나야 정상 동작하므로 한쪽만 거치면 연결이 완성되지 않는다.

**따라서 3번을 완료한 직후 반드시 CLI로 재확인한다** (콘솔 화면만 믿지 말 것):
```bash
aws ec2 describe-route-tables --route-table-ids <igw-ingress-rtb-id> \
  --query 'RouteTables[0].Associations'
```
결과에 `GatewayId`가 포함된 association이 실제로 있는지 확인한다.
빈 배열(`[]`)이면 저장이 안 된 것이므로 3번을 다시 수행한다.

### 9.5. 정리(cleanup)
**firewall1/firewall2는 삭제 대상이 아니다** — 9.3에서 이미 재활용됨(public tier의 firewall endpoint 역할).
다만 이 subnet 자신의 route table은 이제 external1/external2의 NAT을 쓸 이유가 없으므로 IGW 직결로 바꾼다.

1. VPC 콘솔 → Route Tables → firewall1 route table → Routes → Edit routes → `0.0.0.0/0` target을 고아 NAT-A → IGW로 변경 → Save changes
2. firewall2 route table도 동일하게 `0.0.0.0/0` target을 고아 NAT-B → IGW로 변경
3. **external1/external2 삭제**: VPC 콘솔 → NAT Gateways → 고아 NAT-A 체크 → Delete NAT gateway(EIP-B는 필요 없으면 이후 Elastic IPs에서 Release)
4. VPC 콘솔 → Subnets → external1, external2 체크 → Actions → Delete subnet
5. 위 두 subnet에 연결됐던 route table도 Route Tables 메뉴에서 수동 삭제(subnet 삭제만으로 자동 삭제되지 않음)

### 9.6. 로깅 구축
Dev와 동일한 방식으로 구축한다(절차는 이미 Dev에서 검증됨).
1. CloudWatch 콘솔 → Log groups → Create log group: `/aws/network-firewall/stage/flow`(retention 30일), `/aws/network-firewall/stage/alert`(retention 180일)
2. Network Firewall 콘솔 → Stage Firewall → Firewall details → Logging → Edit → Flow logs/Alert logs 둘 다 체크, 각각 위 로그 그룹 지정
3. Enable the detailed monitoring dashboard 체크 → Save

### 9.7. 검증
1. ALB 콘솔에서 각 ALB의 Target group health가 모두 healthy인지 확인
2. 서비스 A/B/C의 EC2 인스턴스 애플리케이션 로그에서 외부 API 호출 실패가 없는지 확인
3. CloudWatch Logs Insights에서 alert 로그 그룹을 조회해, allow-list에 없는 도메인으로 나가는 트래픽(ALERT 로그)이 있는지 확인:
   ```
   fields @timestamp, event.src_ip, event.dest_ip, event.tls.sni, event.alert.action
   | filter ispresent(event.tls.sni)
   | sort @timestamp desc
   | limit 50
   ```
4. 여기서 발견된 도메인 중 정상 서비스 트래픽이면 Stage Policy의 allow-list에 추가, 비정상이면 원인 조사.

### 9.8. (향후) Stateful default action을 drop으로 전환
- 9.7에서 최소 수일간 문제 없다고 확인된 뒤에만 진행. dev보다 훨씬 신중해야 한다 — 실제 서비스가 걸려 있으므로.
- 전환 전 반드시 Stage Policy가 Dev Firewall과 공유 중이라는 점을 dev 담당자에게도 공지(정책 변경이 dev 쪽에도 영향을 줌).

---

## 10. Dev와의 핵심 차이 요약
| 구분 | Dev | Stage |
| --- | --- | --- |
| 시작 시점 워크로드 | 0건 | ALB 15개+, NLB 3개, EC2 다수 (실사용 중) |
| Public tier route table | AZ별 독립 | AZ 공유(선분리 필요) |
| Private tier NAT | AZ별 독립 primary firewall 경유 | AZ 공유, firewall 완전 미경유 |
| Firewall 실사용 여부(마이그레이션 전) | 사용 중(pre-NAT 검사) | 사실상 미사용(고아 상태) |
| VPC Peering | 없음 | Live/Bastion/오피스 3개 존재, 보존 필요 |
| 정책 default action | alert | alert(동일) |
| 로깅 | 미설정(마이그레이션 중 구축) | 미설정(동일하게 구축 필요) |
| 마이그레이션 리스크 | 낮음(워크로드 없음) | 높음(실서비스 트래픽 영향 가능) |

---

## 11. 성과 및 배운 점
- 실사용 중인 ALB 15개+, NLB 3개, EC2 인스턴스가 걸린 Public tier에서, 리소스는 배포돼 있지만 실제 트래픽은 Firewall을 하나도 거치지 않는 상태임을 CLI 전수 조회로 확인하고, 이를 근거로 우선순위를 재설정했다.
- 표준 대비 Gap 분석 9개 항목 중 5개가 미충족(❌), 2개가 부분 충족(⚠️)으로 확인됐고, 이를 근거로 9.1–9.8 단계의 전환 순서를 정했다.
- 실서비스 트래픽이 흐르는 환경의 위험 요소 5건을 사전에 식별해, Dev와 달리 매 단계마다 즉시 검증과 롤백 계획이 필요하다는 것을 계획 수립 과정에 반영했다.
- [02. Return Path 설계 원칙](./02-return-path-design-principle.md)에서 정리한 원칙과 Dev에서 겪은 장애 경험을 Stage 계획에 선제적으로 반영해, 동일한 사고가 반복되지 않도록 점검 절차를 구체화했다.

---
*회사명, 계정/리소스 식별자(계정 ID, VPC/Subnet/NAT/Endpoint/Peering ID, 공인 IP 등), 내부 서비스명 등은 포함하지 않았습니다.*
