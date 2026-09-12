<div align="center">
<h1>AWS Network Firewall Return Path 설계 필요성 보고서</h1>
<i>Why Return Path Design Matters in Firewall-Centric Networks</i>
</div>

*2026.06 · 클라우드 네트워크 보안 담당*

---

## 1. 요약
방화벽을 경유하는 네트워크 구조에서 return path를 명시적으로 설정해야 하는 원론적인 이유를 정리한 문서다.
특히 private subnet의 서버가 인터넷으로 나가는 트래픽을 Network Firewall로 검사하는 구조에서, 요청 방향 경로뿐 아니라 응답 방향 경로까지 동일한 보안 경로를 지나도록 설계해야 하는 이유를 다룬다.
이 원칙은 이후 여러 환경의 마이그레이션 계획([03](./03-stage-environment-migration-plan.md), [04](./04-live-environment-migration-plan.md))에서 공통 점검 기준으로 재사용됐다.

---

## 2. 문서 정보
| 항목 | 내용 |
| --- | --- |
| 작성일 | 2026-06-04 |
| 주제 | Network Firewall 경유 구조에서 return path 설계가 필요한 이유와 운영 기준 |
| 대상 아키텍처 | AWS VPC, Private subnet, External subnet, NAT Gateway, AWS Network Firewall |

---

## 3. 담당 역할
- Return path 미설계 시 발생하는 문제의 원리 정리
- 실제 장애 사례 기반 재발 방지 체크리스트 작성
- 이후 환경별 마이그레이션 계획에 이 원칙을 점검 항목으로 반영

---

## 4. 보고서 목적
Dev VPC 재구축 과정([01](./01-dev-environment-migration.md))에서 NAT Gateway를 교체하며 라우팅을 요청 방향 위주로만 다시 잡았다가, 기존 firewall subnet의 route table이 이미 삭제된 NAT을 참조한 채 blackhole 상태로 남은 것을 재조회 과정에서 뒤늦게 발견한 적이 있다.
요청 경로만 보고 라우팅을 설계하면 응답을 포함한 전체 경로가 예상과 다르게 끊기거나 우회할 수 있다는 것을 실제로 겪은 셈이다.
이 경험은 이후 다른 환경을 마이그레이션할 때 같은 문제가 재발하지 않도록, return path를 forward path와 동등한 설계 대상으로 명문화할 필요가 있다는 문제의식으로 이어졌다.

이 보고서는 AWS VPC, NAT Gateway, AWS Network Firewall을 사용하는 아웃바운드 보안 아키텍처에서 `return path`를 명시적으로 설정해야 하는 원론적인 이유를 설명한다.
특히 private subnet의 서버가 인터넷으로 나가는 트래픽을 Network Firewall로 검사하는 구조에서, 요청 방향 경로뿐 아니라 응답 방향 경로까지 동일한 보안 경로를 지나도록 설계해야 하는 이유를 정리한다.

---

## 5. 핵심 결론
`return path`는 단순한 라우팅 편의 설정이 아니라 방화벽 기반 보안 설계의 필수 조건이다.

방화벽을 경유하는 네트워크 구조에서는 하나의 통신 세션에 대해 요청 패킷과 응답 패킷이 논리적으로 같은 보안 경로를 지나야 한다.
요청 트래픽만 방화벽을 통과하고 응답 트래픽이 방화벽을 우회하면 다음 문제가 발생한다.

- 방화벽이 세션 전체를 관찰하지 못한다.
- stateful inspection의 전제가 깨진다.
- 보안 정책, 로깅, 추적, 장애 분석의 신뢰도가 낮아진다.
- 경로가 비대칭이 되어 일부 구간에서 패킷이 드롭될 수 있다.
- 설계상 "방화벽을 반드시 경유한다"는 통제 목표가 충족되지 않는다.

---

## 6. Return Path의 기본 개념
네트워크 통신은 일반적으로 요청 방향과 응답 방향으로 구성된다.

```text
Request path:
Client -> Gateway -> Firewall -> NAT -> Internet

Return path:
Internet -> NAT -> Firewall -> Gateway -> Client
```

`forward path`는 클라이언트가 목적지로 나가는 경로다.
`return path`는 목적지가 클라이언트로 응답을 돌려보내는 경로다.

라우팅은 방향성이 있다.
요청 패킷이 특정 장비를 통과했다고 해서 응답 패킷도 자동으로 같은 장비를 통과하는 것은 아니다.
각 구간의 route table은 패킷의 현재 위치와 목적지 IP를 기준으로 다음 hop을 독립적으로 결정한다.

따라서 보안 장비를 경유해야 하는 구조에서는 요청 방향 라우트만 설정하면 충분하지 않다.
응답 방향에서 어떤 route table이 어떤 destination을 어떤 target으로 보내야 하는지도 명시해야 한다.

---

## 7. Stateful Inspection과 Return Path
AWS Network Firewall 같은 방화벽은 단순히 패킷 하나만 보는 장비가 아니다.
일반적으로 다음 정보를 조합해 통신을 판단한다.

- 출발지 IP
- 목적지 IP
- 출발지 포트
- 목적지 포트
- 프로토콜
- TCP 세션 상태
- 애플리케이션 계층 정보
- 도메인, SNI, HTTP Host 등 정책 판단 정보

이러한 판단은 개별 패킷이 아니라 하나의 세션 흐름을 기준으로 이뤄진다.

예를 들어 private EC2가 외부 HTTPS 서비스에 접속하는 경우, 방화벽은 outbound SYN, TLS handshake, 이후 응답 패킷의 흐름을 함께 봐야 정상적인 stateful inspection을 수행할 수 있다.

요청 패킷만 방화벽을 통과하고 응답 패킷이 방화벽을 우회하면 방화벽 입장에서는 세션의 절반만 관찰한 상태가 된다.
이 경우 정책 판단, 세션 추적, 로깅이 불완전해진다.

---

## 8. 비대칭 라우팅 문제
`asymmetric routing`은 요청 방향과 응답 방향이 서로 다른 경로를 사용하는 상태를 의미한다.

```text
요청:
Private EC2 -> Firewall Endpoint AZ-A -> NAT Gateway AZ-A -> Internet

응답:
Internet -> NAT Gateway AZ-A -> Private EC2
```

위 예시는 응답 트래픽이 Network Firewall을 거치지 않는 비대칭 구조다.

비대칭 라우팅은 다음과 같은 문제를 만든다.

| 문제 | 설명 |
| --- | --- |
| 검사 우회 | 응답 트래픽이 방화벽을 지나지 않아 보안 검사가 누락된다. |
| 세션 상태 불일치 | 방화벽이 세션의 양방향 흐름을 보지 못한다. |
| 로그 불완전 | outbound 로그만 남고 inbound response 관찰 기록이 빠질 수 있다. |
| 장애 분석 어려움 | 패킷이 어느 구간에서 사라졌는지 추적하기 어렵다. |
| 정책 일관성 저하 | "모든 private egress는 방화벽을 경유한다"는 설계 원칙이 깨진다. |
| 드롭 가능성 | 다른 AZ, 다른 endpoint, 다른 stateful engine으로 응답이 들어가면 세션 상태가 맞지 않아 드롭될 수 있다. |

방화벽, NAT, 로드밸런서, VPN, Transit Gateway 같은 중간 장비가 있는 네트워크에서는 비대칭 라우팅을 명시적으로 방지해야 한다.

---

## 9. NAT Gateway와 Return Path
Private subnet의 서버는 사설 IP를 사용하므로 인터넷과 직접 통신할 수 없다.
NAT Gateway는 private IP를 public IP로 변환해 인터넷 통신을 가능하게 한다.

요청 방향에서는 다음 흐름이 발생한다.

```text
Private EC2
-> Network Firewall
-> NAT Gateway
-> Internet Gateway
-> Internet
```

응답 방향에서는 인터넷에서 돌아온 패킷이 NAT Gateway에 도착하고, NAT Gateway는 목적지를 원래 private EC2의 사설 IP로 다시 변환한다.

이때 중요한 지점은 NAT Gateway가 변환한 이후의 목적지다.
NAT Gateway가 응답 패킷의 목적지를 private EC2 IP로 바꾼 뒤에는, NAT Gateway가 위치한 subnet의 route table이 그 private IP 대역을 어디로 보낼지 결정한다.

만약 external subnet route table에 private CIDR에 대한 별도 반환 라우트가 없으면, VPC의 기본 local route에 의해 응답 트래픽이 private subnet으로 직접 전달될 수 있다.

```text
잘못된 응답 흐름:
Internet
-> Internet Gateway
-> NAT Gateway
-> VPC local route
-> Private EC2
```

이 흐름은 정상 통신처럼 보일 수 있지만, 보안 관점에서는 Network Firewall을 우회한 것이다.

따라서 NAT Gateway가 있는 external subnet route table에는 private CIDR로 향하는 트래픽을 Network Firewall Endpoint로 보내는 반환 라우트가 필요하다.

```text
올바른 응답 흐름:
Internet
-> Internet Gateway
-> NAT Gateway
-> external route table
-> Private CIDR return route
-> Network Firewall Endpoint
-> Private EC2
```

---

## 10. 현재 아키텍처에서 필요한 Return Path
현재 구조는 private subnet의 인터넷 아웃바운드 트래픽을 Network Firewall로 검사한 뒤 NAT Gateway를 통해 인터넷으로 내보내는 방식이다.

요청 방향의 핵심 라우트는 다음과 같다.

```text
private route table:
0.0.0.0/0 -> Network Firewall Endpoint

firewall route table:
0.0.0.0/0 -> NAT Gateway

external route table:
0.0.0.0/0 -> Internet Gateway
```

하지만 이것만으로는 충분하지 않다.
응답 방향에서 NAT Gateway가 private EC2로 돌려보내는 트래픽도 Network Firewall로 다시 넣어야 한다.

따라서 external route table에는 다음 라우트가 필요하다.

```text
external-az-a:
Private AZ-A CIDR -> Network Firewall Endpoint AZ-A

external-az-b:
Private AZ-B CIDR -> Network Firewall Endpoint AZ-B
```

이 라우트의 목적지는 firewall subnet CIDR이 아니라 private subnet CIDR이어야 한다.

NAT Gateway가 응답 패킷의 목적지를 private EC2의 IP로 변환하기 때문에, route table은 그 private EC2가 속한 CIDR을 기준으로 다음 hop을 결정한다.
따라서 `firewall subnet CIDR -> Firewall Endpoint`로 설정하면 실제 응답 트래픽 목적지와 맞지 않는다.

---

## 11. AZ 단위 Return Path가 필요한 이유
Multi-AZ 구조에서는 return path를 같은 AZ 기준으로 맞춰야 한다.

```text
AZ-A 요청:
Private AZ-A -> Firewall Endpoint AZ-A -> NAT Gateway AZ-A -> Internet

AZ-A 응답:
Internet -> NAT Gateway AZ-A -> Firewall Endpoint AZ-A -> Private AZ-A
```

```text
AZ-B 요청:
Private AZ-B -> Firewall Endpoint AZ-B -> NAT Gateway AZ-B -> Internet

AZ-B 응답:
Internet -> NAT Gateway AZ-B -> Firewall Endpoint AZ-B -> Private AZ-B
```

AZ가 섞이면 다음 문제가 발생할 수 있다.

- 불필요한 cross-AZ 트래픽 비용이 발생한다.
- 장애 영향 범위가 커진다.
- 방화벽 endpoint별 세션 상태가 달라질 수 있다.
- 특정 AZ 장애 시 우회 경로가 의도치 않게 동작할 수 있다.
- 운영자가 패킷 흐름을 예측하기 어렵다.

따라서 egress path와 return path는 모두 같은 AZ 안에서 닫히는 구조가 가장 명확하다.

---

## 12. Return Path 미설정 시 발생 가능한 시나리오
### 12.1. 응답 트래픽의 방화벽 우회
Private EC2의 요청은 Network Firewall을 통과하지만, 응답은 NAT Gateway 이후 local route를 통해 private subnet으로 바로 전달된다.

결과적으로 외부에서 들어오는 응답 패킷이 방화벽 검사 없이 workload에 도달한다.

### 12.2. 방화벽 로그 불완전
운영자는 Network Firewall 로그를 보고 특정 통신이 정상적으로 왕복했는지 판단하려고 한다.
그러나 return path가 방화벽을 우회하면 응답 방향 기록이 남지 않거나 불완전하게 보일 수 있다.

이 경우 보안 분석과 장애 분석에서 다음 질문에 답하기 어려워진다.

- 외부 서버가 실제로 응답했는가?
- 응답 패킷이 방화벽 정책에 의해 허용되었는가?
- 세션이 정상 종료되었는가?
- 중간에 드롭된 지점은 어디인가?

### 12.3. 정책 검증 실패
보안 정책의 목적이 "private subnet의 모든 인터넷 통신은 Network Firewall을 경유한다"라면, 요청 방향만 방화벽을 통과하는 것은 정책을 절반만 만족한 것이다.

감사 관점에서는 실제 통신 세션 전체가 통제 구간을 통과했는지 증명할 수 있어야 한다.

### 12.4. 장애 시 원인 분석 복잡도 증가
비대칭 경로는 장애 분석을 어렵게 만든다.

요청은 방화벽 로그에 보이지만 응답은 보이지 않을 수 있다.
반대로 애플리케이션에서는 응답 지연이나 연결 실패가 발생하는데, 방화벽 로그만 보면 원인을 찾기 어렵다.

이런 구조에서는 route table, NAT Gateway, Network Firewall, security group, NACL, 애플리케이션 로그를 모두 교차 확인해야 하며 장애 분석 시간이 늘어난다.

---

## 13. Return Path 설계 원칙
Return path는 다음 원칙으로 설계한다.

| 원칙 | 설명 |
| --- | --- |
| 양방향 경로 일관성 | 요청과 응답이 동일한 보안 장비를 지나도록 설계한다. |
| AZ 정합성 | 같은 AZ의 Firewall Endpoint와 NAT Gateway를 사용한다. |
| 목적지 CIDR 정확성 | 반환 라우트의 destination은 실제 응답 패킷의 목적지인 private CIDR로 설정한다. |
| 보안 장비 우회 방지 | VPC local route로 인해 방화벽을 우회하지 않도록 더 구체적인 private CIDR 라우트를 둔다. |
| 로깅 일관성 | 방화벽 로그에서 세션 흐름을 추적할 수 있도록 양방향 트래픽을 관찰 가능하게 한다. |
| 변경 관리 | NAT, route table, firewall endpoint 변경 시 return path 영향도를 함께 검토한다. |

---

## 14. 설정 기준 예시
예시 CIDR 기준은 다음과 같다.

| Subnet | CIDR | 역할 |
| --- | --- | --- |
| private-az-a | `<private-az-a-cidr>` | AZ-A workload |
| private-az-b | `<private-az-b-cidr>` | AZ-B workload |
| firewall-az-a | `<firewall-az-a-cidr>` | AZ-A Firewall Endpoint |
| firewall-az-b | `<firewall-az-b-cidr>` | AZ-B Firewall Endpoint |
| external-az-a | `<external-az-a-cidr>` | AZ-A NAT Gateway |
| external-az-b | `<external-az-b-cidr>` | AZ-B NAT Gateway |

External route table의 반환 라우트는 다음처럼 잡는다.

```text
external-az-a route table:
<private-az-a-cidr> -> Network Firewall Endpoint AZ-A

external-az-b route table:
<private-az-b-cidr> -> Network Firewall Endpoint AZ-B
```

잘못된 예시는 다음과 같다.

```text
external-az-a route table:
<firewall-az-a-cidr> -> Network Firewall Endpoint AZ-A

external-az-b route table:
<firewall-az-b-cidr> -> Network Firewall Endpoint AZ-B
```

위 설정은 firewall subnet CIDR을 목적지로 사용하고 있기 때문에 NAT 응답 트래픽의 실제 목적지와 맞지 않는다.
NAT Gateway가 응답 패킷을 private EC2 IP로 변환한 뒤에는 목적지가 `<private-az-a-cidr>` 또는 `<private-az-b-cidr>`이므로, 반환 라우트도 private CIDR을 기준으로 해야 한다.

---

## 15. 점검 체크리스트
Return path 설정은 다음 항목으로 점검한다.

| 점검 항목 | 확인 기준 |
| --- | --- |
| Private route table | `0.0.0.0/0`이 같은 AZ Network Firewall Endpoint를 향하는가 |
| Firewall route table | `0.0.0.0/0`이 같은 AZ NAT Gateway를 향하는가 |
| External route table 기본 라우트 | `0.0.0.0/0`이 Internet Gateway를 향하는가 |
| External route table 반환 라우트 | 같은 AZ private CIDR이 같은 AZ Network Firewall Endpoint를 향하는가 |
| Return route destination | firewall subnet CIDR이 아니라 private subnet CIDR인가 |
| AZ 정합성 | AZ-A 트래픽은 AZ-A endpoint와 NAT를 사용하고, AZ-B 트래픽은 AZ-B endpoint와 NAT를 사용하는가 |
| 로그 확인 | Network Firewall flow log와 alert log에서 허용/차단 흐름을 추적할 수 있는가 |
| 변경 영향도 | subnet, NAT, endpoint, route table 변경 시 return path가 함께 검토되는가 |

---

## 16. 운영 관점 결론
Private subnet의 인터넷 egress를 Network Firewall로 통제하려면 다음 두 문장이 동시에 성립해야 한다.

```text
나가는 트래픽은 Network Firewall을 지나야 한다.
돌아오는 트래픽도 Network Firewall을 지나야 한다.
```

첫 번째 문장만 만족하면 outbound inspection 구조가 완성되지 않는다.
NAT Gateway가 있는 external subnet에서 private CIDR별 반환 라우트를 같은 AZ Network Firewall Endpoint로 설정해야 비로소 세션 단위의 일관된 보안 경로가 완성된다.

---

## 17. 성과 및 배운 점
- 라우팅 문제를 "설정을 빠뜨렸다"가 아니라 "왜 이 설정이 구조적으로 필수인가"라는 원리 수준에서 정리하는 경험을 했다.
- 이 개념 정리가 이후 [03](./03-stage-environment-migration-plan.md), [04](./04-live-environment-migration-plan.md) 마이그레이션 계획의 공통 점검 기준으로 재사용됐다.

---
*회사명, 계정/리소스 식별자 등은 포함하지 않았습니다.*
