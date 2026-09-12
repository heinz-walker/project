# PIMS 접속 이력 감사 (소스)

익명화한 전체 소스입니다.
실제 설정 파일(`reviewer_config.json`)과 실행 결과물(XLSX, `data/`)은 저장소에 포함하지 않고 예시 파일만 둡니다.

## 폴더 구조

```
code/
  generate_report.py             CloudTrail·CloudWatch Logs 수집부터 HTML/XLSX 생성까지 전체 로직
  report_template.html           HTML 보고서 템플릿 ($변수로 치환)
  reviewer_config.example.json   설정 파일 예시 (인가자·허용 IP·자동 판정 규칙 등, 값은 모두 가상)
```

`generate_report.py`는 `reviewer_config.json`을 `code/`에서, `report_template.html`을 같은 경로에서 읽습니다(둘 다 `--config`/`--template` 인수로 경로 변경 가능).

## 설정

1. 예시 파일 복사
   ```bash
   cp code/reviewer_config.example.json code/reviewer_config.json
   ```
2. `reviewer_config.json` 값 채우기 — 인가자 목록(`authorized_users`), 허용 IP/CIDR(`allowed_ips`/`allowed_ip_cidrs`), 공휴일(`holidays`), 자동 판정 규칙(`*_auto_rules`) 등. 아래 "설정 파일" 절 참고
3. 의존성 준비 — AWS CLI가 설치·설정되어 있어야 하고(내부적으로 `aws s3 sync`·`aws logs` 등을 직접 호출), Python 라이브러리는 `openpyxl`만 필요하다
   ```bash
   pip install openpyxl
   ```
4. AWS 로그인 (CloudTrail S3 버킷·CloudWatch Logs 조회 권한이 있는 프로파일)
   ```bash
   aws sso login --profile <aws-profile>
   ```

## 실행

```bash
python3 code/generate_report.py \
  --profile     <aws-profile> \
  --bucket      <cloudtrail-bucket-name> \
  --account-id  <aws-account-id> \
  --region      <aws-region> \
  --date-from   2026-06-01 \
  --date-to     2026-06-30 \
  --webapp-workbook "data/log/2026년 06월 접속 로그.xlsx"
```

실행이 완료되면 `data/reports/202606/` 폴더에 결과가 생성됩니다.

`--webapp-workbook`을 생략하면 웹앱(관리툴) 섹션이 비어 있는 보고서가 생성됩니다.

### 전체 인수 목록

| 인수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `--profile` | Y | — | AWS 프로파일 이름 |
| `--bucket` | Y | — | CloudTrail S3 버킷 이름 |
| `--account-id` | Y | — | AWS 계정 ID |
| `--region` | Y | — | CloudTrail 리전 |
| `--log-group` | | `/aws/ssm/bastion-audit-logs` | CloudWatch Logs 그룹 |
| `--date-from` | Y | — | 검토 시작일 (`YYYY-MM-DD`) |
| `--date-to` | Y | — | 검토 종료일 (`YYYY-MM-DD`) |
| `--business-start-hour` | | `9` | 업무시간 시작 (시) |
| `--business-end-hour` | | `19` | 업무시간 종료 (시) |
| `--webapp-workbook` | | 없음 | 웹앱(관리툴) 접속 로그 XLSX 경로 |
| `--config` | | `code/reviewer_config.json` | 설정 파일 경로 |
| `--template` | | `code/report_template.html` | HTML 템플릿 경로 |
| `--out-dir` | | `data/reports` | 출력 루트 디렉토리 |

`--region`은 회사마다 다른 실제 운영 리전이 기본값으로 코드에 박히지 않도록 필수 인수로 뒀습니다.

## 출력 파일

`data/reports/YYYYMM/` 아래에 생성됩니다.

| 파일 | 설명 |
| --- | --- |
| `audit_report.html` | 전자결재 업로드용 HTML 보고서 |
| `audit_report_details.xlsx` | 상세 내역 XLSX (원시 이벤트 + 검토 결과) |
| `ssm_session_events.csv` | 접속 성공 이벤트 원본 |
| `ssm_blocked_events.csv` | 차단 이벤트 원본 |
| `ssm_session_commands.csv` | 세션 명령 로그 원본 |
| `report_summary.json` | 검토 결과 요약 JSON |

## 설정 파일 (`reviewer_config.json`)

`reviewer_config.example.json`이 전체 항목의 형태를 보여줍니다.
이름·IP·계정 식별자는 전부 가상 값이며, 실제 값으로 바꿔서 씁니다.

| 항목 | 설명 |
| --- | --- |
| `authorized_users` | bastion host 인가자 목록 및 표시 이름·부서 |
| `webapp_authorized_users` | 웹앱(관리툴) 인가자 목록 |
| `allowed_ips` | 허용 IP 단일 목록 |
| `allowed_ip_cidrs` | 허용 IP CIDR 목록 (내부망 등) |
| `ip_labels` | IP별 표시 레이블 |
| `user_aliases` | CloudTrail AssumedRole ID → 사용자 ID 매핑 |
| `holidays` | 공휴일 날짜 목록 (`YYYY-MM-DD`). 해당일 접속은 주말과 동일하게 업무시간 외로 처리 |
| `after_hours_approvals` / `command_approvals` / `blocked_approvals` | 세션/이벤트 ID로 키를 건, 사람이 이미 판단을 내린 개별 건에 대한 승인 오버라이드 |
| `after_hours_auto_rules` | 업무시간 외 bastion 접속 자동 판정 규칙 |
| `webapp_after_hours_auto_rules` | 업무시간 외 웹앱 로그인 자동 판정 규칙 |
| `command_auto_rules` | 위험 패턴 명령 자동 판정 규칙 |
| `blocked_auto_rules` | 차단 이벤트 자동 판정 규칙 |
| `service_labels` | 인스턴스 ID → 서비스 표시 이름 매핑 |

### 자동 판정 규칙 작성 방법

규칙은 배열 순서대로 매칭하며, 조건 키가 모두 일치하는 첫 번째 규칙을 적용합니다.
조건 없이 `status`/`reason`/`remark`만 있는 규칙은 전체 catch-all로 동작합니다.
`_regex` 접미사 키는 정규식(`re.search`)으로 매칭합니다.

```json
"after_hours_auto_rules": [
  {
    "user_authorized": "Y",
    "status": "이상없음(양호)",
    "reason": "인가 사용자의 업무 목적 접속 확인",
    "remark": "담당자 확인"
  }
]
```

```json
"command_auto_rules": [
  {
    "risk_flags": "privilege_change",
    "command_regex": "sudo su - example-service-account$",
    "status": "이상없음(양호)",
    "reason": "운영 표준 계정 전환 패턴",
    "remark": "사전 정의된 승인 패턴"
  },
  {
    "status": "이상없음(양호)",
    "reason": "인가 사용자의 업무 목적 명령 확인",
    "remark": "담당자 확인"
  }
]
```

### 개별 세션/이벤트 승인 오버라이드

자동 규칙으로 걸러지지 않는 예외 건은 `after_hours_approvals`/`command_approvals`/`blocked_approvals`에 세션 ID 또는 이벤트 ID를 키로 직접 기록합니다.
한 번 사람이 판단을 내린 세션은 다음 달 다시 나타나도 이 오버라이드로 즉시 처리되며, 자동 규칙보다 우선 적용됩니다.

### 공휴일 관리

`reviewer_config.json`의 `holidays` 배열에 `YYYY-MM-DD` 형식으로 추가합니다.
매년 초에 해당 연도 공휴일을 추가합니다.
