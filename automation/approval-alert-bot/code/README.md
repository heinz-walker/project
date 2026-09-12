# 전자결재·보안 이벤트 슬랙 알림 봇 (소스)

익명화한 전체 소스입니다.
자격증명·채널 ID·사람 매핑은 저장소에 포함하지 않고 `.sample` 파일만 둡니다.

## 폴더 구조

```
code/
  credentials.json.sample        토큰·앱 비밀번호 템플릿 (프로젝트 루트에서 로드)
  alert_slack/
    __main__.py                  python3 -m alert_slack 진입점
    main.py                      IMAP 감시 + 규칙 엔진 + 슬랙 전송
    test.py                      오프라인 테스트 하니스 (pytest 불필요)
    requirements.txt             beautifulsoup4, slack_sdk
    config.json.sample           채널 ID·메일 계정 템플릿
    users.json.sample            담당자 → 슬랙 ID 매핑 템플릿
    rules/
      rule_approval.json         임직원 결재 상신 도착
      rule_approval_leader.json  기안자==나 AND 결재자 in 이름목록 (2차 조건)
      rule_approval_leader2.json 기안자==나, 결재자==나 인 경우 제외
      rule_media_control.json    매체제어 승인요청 (승인/반려/콘솔 버튼)
      employee_update.json       임직원 명부 변경 (시트 링크만)
      rule_create.html           브라우저 규칙 빌더 (서버 불필요, 단일 파일)
```

`main.py`는 `credentials.json`을 프로젝트 루트에서, `config.json`·`users.json`을 `alert_slack/`에서 읽습니다.

## 설정

1. 샘플 파일 복사
   ```bash
   cp credentials.json.sample credentials.json
   cp alert_slack/config.json.sample alert_slack/config.json
   cp alert_slack/users.json.sample alert_slack/users.json
   ```
2. 값 입력
   - `credentials.json`: Google API `client_id`·`client_secret`, 슬랙 봇 토큰, 메일 앱 비밀번호
   - `alert_slack/config.json`: 타겟 채널 ID, 메일 계정(`your_email@example.com`), IMAP 서버
   - `alert_slack/users.json`: `me`·`leader`의 이름과 슬랙 사용자 ID
3. 라이브러리 설치
   ```bash
   pip install -r alert_slack/requirements.txt
   ```
4. 실행
   ```bash
   python3 -m alert_slack
   ```

## 테스트

메일함·슬랙에 연결하지 않고 규칙 로직만 검증합니다.

1. 의존성 설치
   ```bash
   python3 -m pip install -r alert_slack/requirements.txt
   ```
2. `users.json`이 없으면 샘플로 만든 뒤 실행
   ```bash
   cp alert_slack/users.json.sample alert_slack/users.json
   ```
3. 전체 규칙 합성 테스트 — 규칙마다 positive/negative 케이스를 자동 생성해 매칭 결과를 검증
   ```bash
   python3 alert_slack/test.py
   ```
4. 특정 규칙만
   ```bash
   python3 alert_slack/test.py --rule rule_approval_leader2.json
   ```
5. 저장한 실제 메일(.eml) 하나로 전체 규칙 평가 — 파일은 직접 저장해서 사용
   ```bash
   python3 alert_slack/test.py --eml sample_employee_update.eml
   ```

합성 테스트가 확인하는 항목: 제목 키워드 일치, 1차 조건, 2차 조건, 배제 조건, `custom` 직접 입력 이름의 본문 포함 매칭.
