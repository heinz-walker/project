import imaplib
import email
import os
import json
import time
import re
from email.header import decode_header
from bs4 import BeautifulSoup
from slack_sdk import WebClient

# ==========================================
# 1. 설정 및 사용자 정보 로드 (경로 및 구조 최적화)
# ==========================================
def load_configurations():
    # 현재 파일(main.py) 위치: .../alert_slack/main.py
    base_dir = os.path.dirname(os.path.abspath(__file__)) 
    # alert_slack 폴더 위치
    alert_slack_dir = base_dir
    # 프로젝트 루트 폴더 위치
    root_dir = os.path.join(alert_slack_dir, "..")
    
    # 각 JSON 파일의 절대 경로 설정
    cred_path = os.path.join(root_dir, "credentials.json")
    config_path = os.path.join(alert_slack_dir, "config.json")
    user_config_path = os.path.join(alert_slack_dir, "users.json")

    try:
        # 1. 인증 정보 (민감 정보: 토큰, 비밀번호)
        with open(cred_path, "r", encoding="utf-8") as f:
            creds = json.load(f)
        
        # 2. 설정 정보 (일반 설정: 채널, 서버 주소)
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            
        # 3. 사용자 정보 (사용자 매핑)
        with open(user_config_path, "r", encoding="utf-8") as f:
            users = json.load(f)
            
        return creds, config, users
    except FileNotFoundError as e:
        print(f"❌ 설정 파일을 찾을 수 없습니다: {e.filename}")
        exit(1)
    except json.JSONDecodeError:
        print(f"❌ JSON 파일 형식에 에러가 있습니다. 형식을 확인해주세요.")
        exit(1)

# ==========================================
# 2. 유틸리티 함수
# ==========================================
def extract_link(html_content, keyword):
    if not html_content or not keyword: return None
    soup = BeautifulSoup(html_content, 'html.parser')
    # 일부 메일은 링크 텍스트가 중첩 태그로 감싸져 있어 .string이 None일 수 있습니다.
    for a in soup.find_all('a', href=True):
        text = a.get_text(" ", strip=True)
        if text and keyword in text:
            return a.get('href').strip()
    # 예외 처리: 텍스트 전체에서 정규식으로 링크 탐색
    for a in soup.find_all('a', href=True):
        text = a.get_text(" ", strip=True)
        if text and re.search(keyword, text):
            return a.get('href').strip()
    return None

def get_person_info(html_body):
    soup = BeautifulSoup(html_body, 'html.parser')
    text = soup.get_text(" ", strip=True)

    drafter = re.search(r"기안자\s*[:：]?\s*([^\s\n\r]+)", text)
    approver = re.search(r"결재자\s*[:：]?\s*([^\s\n\r]+)", text)
    drafter_name = drafter.group(1).strip() if drafter else None

    # 엔드포인트 보안 솔루션(매체제어) 메일은 "기안자" 대신 "요청자(PC)" 행을 쓸 수 있습니다.
    if not drafter_name:
        for td in soup.find_all('td'):
            label = td.get_text(" ", strip=True)
            if "요청자" in label:
                next_td = td.find_next_sibling('td')
                if next_td:
                    val = next_td.get_text(" ", strip=True)
                    # 예: "홍길동( ... )" -> "홍길동"
                    name = re.split(r"[\s(]", val, maxsplit=1)[0].strip()
                    if name:
                        drafter_name = name
                        break

    # 예외 처리: "OOO님이 ... 요청" 패턴
    if not drafter_name:
        m = re.search(r"([^\s]+)님이\s.*?요청", text)
        if m:
            drafter_name = m.group(1).strip()

    return {
        "drafter": drafter_name or "미상",
        "approver": approver.group(1).strip() if approver else "미상"
    }

def normalize_name(name):
    if not name:
        return ""
    # 매칭을 위해 공백/호칭/괄호 정보를 제거합니다.
    name = re.sub(r"\(.*?\)", "", name)
    name = name.replace("님", "")
    name = re.sub(r"\s+", "", name)
    return name.strip()

def split_custom_names(compare_name):
    if not compare_name:
        return []
    return [normalized for normalized in (normalize_name(part) for part in compare_name.split(",")) if normalized]

def match_person_condition(person, field, compare_key, user_info, body_text="", compare_name=""):
    p_val = normalize_name(person.get(field, ""))
    normalized_body = normalize_name(body_text)

    if compare_key == "any":
        return bool(p_val and p_val != "미상")

    if compare_key == "custom":
        custom_names = split_custom_names(compare_name)
        if not custom_names:
            return False
        if p_val and p_val in custom_names:
            return True
        return any(custom_name in normalized_body for custom_name in custom_names)

    comp_val = user_info.get(compare_key, {}).get("name")
    c_val = normalize_name(comp_val)
    return bool(p_val and c_val and p_val == c_val)

def apply_template(template, context):
    if not template:
        return ""
    out = template
    for k, v in context.items():
        out = out.replace("{" + k + "}", str(v))
    return out

def build_message_text(rule, subject, person, mention_id):
    labels = rule.get("labels", {}) or {}
    label_subject = labels.get("subject", "메일 제목")
    label_drafter = labels.get("drafter", "기안자")
    label_approver = labels.get("approver", "결재자")
    label_mention = labels.get("mention", "담당자 확인")

    show_subject = rule.get("show_subject", True)
    show_drafter = rule.get("show_drafter", True)
    show_approver = rule.get("show_approver", False)
    show_mention = rule.get("show_mention", True)

    context = {
        "subject": subject,
        "drafter": person.get("drafter", "미상"),
        "approver": person.get("approver", "미상"),
        "mention_id": mention_id,
        "mention": f"<@{mention_id}>" if mention_id else "",
        "rule_name": rule.get("rule_name", ""),
        "label_subject": label_subject,
        "label_drafter": label_drafter,
        "label_approver": label_approver,
        "label_mention": label_mention
    }

    # 메시지 템플릿이 있으면 해당 템플릿을 우선 적용합니다.
    if rule.get("message_template"):
        return apply_template(rule.get("message_template", ""), context)

    lines = []
    if show_subject:
        lines.append(f"> *{label_subject}:* {subject}")
    if show_drafter:
        lines.append(f"> *{label_drafter}:* {context['drafter']}")
    if show_approver:
        lines.append(f"> *{label_approver}:* {context['approver']}")

    extra_lines = rule.get("extra_lines", [])
    if isinstance(extra_lines, str):
        extra_lines = [s for s in extra_lines.splitlines() if s.strip()]
    for line in extra_lines:
        txt = apply_template(line, context).strip()
        if not txt:
            continue
        if txt.startswith(">"):
            lines.append(txt)
        else:
            lines.append("> " + txt)

    if show_mention:
        mention_template = rule.get("mention_template", "• *{label_mention}:* {mention}")
        lines.append(apply_template(mention_template, context))

    return "\n".join(lines).strip()

def build_header_text(rule):
    if rule.get("show_header", True) is False:
        return ""
    header_text = rule.get("header_text", "*🛡️ {rule_name} 도착*")
    return apply_template(header_text, {"rule_name": rule.get("rule_name", "")})

def build_quote_lines(rule, subject, person, mention_id):
    labels = rule.get("labels", {}) or {}
    label_subject = labels.get("subject", "메일 제목")
    label_drafter = labels.get("drafter", "기안자")
    label_approver = labels.get("approver", "결재자")
    label_mention = labels.get("mention", "담당자 확인")

    show_subject = rule.get("show_subject", True)
    show_drafter = rule.get("show_drafter", True)
    show_approver = rule.get("show_approver", False)
    show_mention = rule.get("show_mention", True)

    context = {
        "subject": subject,
        "drafter": person.get("drafter", "미상"),
        "approver": person.get("approver", "미상"),
        "mention_id": mention_id,
        "mention": f"<@{mention_id}>" if mention_id else "",
        "rule_name": rule.get("rule_name", ""),
        "label_subject": label_subject,
        "label_drafter": label_drafter,
        "label_approver": label_approver,
        "label_mention": label_mention
    }

    lines = []
    if show_subject:
        lines.append(f"*{label_subject}:* {subject}")
    if show_drafter:
        lines.append(f"*{label_drafter}:* {context['drafter']}")
    if show_approver:
        lines.append(f"*{label_approver}:* {context['approver']}")

    extra_lines = rule.get("extra_lines", [])
    if isinstance(extra_lines, str):
        extra_lines = [s for s in extra_lines.splitlines() if s.strip()]
    for line in extra_lines:
        txt = apply_template(line, context).strip()
        if txt:
            lines.append(txt)

    if show_mention:
        mention_template = rule.get("mention_template", "• *{label_mention}:* {mention}")
        lines.append(apply_template(mention_template, context))

    return lines

def decode_subject(subject_header):
    if not subject_header:
        return "(제목 없음)"
    parts = decode_header(subject_header)
    out = []
    for val, enc in parts:
        if isinstance(val, bytes):
            try:
                out.append(val.decode(enc or "utf-8", "ignore"))
            except Exception:
                out.append(val.decode("utf-8", "ignore"))
        else:
            out.append(val)
    return "".join(out)

def extract_message_bodies(msg):
    html_body = ""
    text_body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            decoded = payload.decode('utf-8', 'ignore')
            if content_type == "text/html" and not html_body:
                html_body = decoded
            elif content_type == "text/plain" and not text_body:
                text_body = decoded
    else:
        payload = msg.get_payload(decode=True)
        decoded = payload.decode('utf-8', 'ignore') if payload else ""
        if msg.get_content_type() == "text/plain":
            text_body = decoded
        else:
            html_body = decoded
    return html_body, text_body

def evaluate_rule_match(rule, subject, html_body, text_body, user_info):
    result = {
        "matched": False,
        "reason": "",
        "person": {"drafter": "미상", "approver": "미상"},
        "body_source": html_body or text_body or "",
        "body_text": ""
    }

    filter_keyword = rule.get("filter_keyword", "")
    if filter_keyword not in subject:
        result["reason"] = "keyword_miss"
        return result

    body_source = html_body or text_body or ""
    person = get_person_info(body_source)
    body_text = BeautifulSoup(body_source, 'html.parser').get_text(" ", strip=True)
    logic = rule.get("logic", {})

    is_match = False
    field = logic.get("check_field")
    if field == "always_pass":
        is_match = True
    else:
        compare_key = logic.get("compare_with")
        compare_name = logic.get("compare_name", "")
        if match_person_condition(person, field, compare_key, user_info, body_text, compare_name):
            s_field = logic.get("second_check_field")
            if s_field:
                s_key = logic.get("second_compare_with")
                s_name = logic.get("second_compare_name", "")
                if match_person_condition(person, s_field, s_key, user_info, body_text, s_name):
                    is_match = True
                else:
                    result["reason"] = "second_condition_miss"
            else:
                is_match = True
        else:
            result["reason"] = "primary_condition_miss"

    if is_match:
        exclude_field = logic.get("exclude_field")
        exclude_key = logic.get("exclude_compare_with")
        exclude_name = logic.get("exclude_compare_name", "")
        if exclude_field and exclude_key:
            if match_person_condition(person, exclude_field, exclude_key, user_info, body_text, exclude_name):
                is_match = False
                result["reason"] = "excluded"

    if is_match and not result["reason"]:
        result["reason"] = "matched"
    elif not is_match and not result["reason"]:
        result["reason"] = "logic_miss"

    result["matched"] = is_match
    result["person"] = person
    result["body_source"] = body_source
    result["body_text"] = body_text
    return result

# ==========================================
# 3. 메인 엔진
# ==========================================
def check_mail_and_notify():
    try:
        debug = os.getenv("ALERT_BOT_DEBUG") == "1"
        # 분리된 3개의 설정 로드
        creds, config, user_info = load_configurations()
        
        # 슬랙 클라이언트 초기화 (인증정보에서 토큰 로드)
        client = WebClient(token=creds["slack"]["bot_token"])

        # 룰 파일 로드 (상대 경로 유지)
        rules = []
        base_dir = os.path.dirname(os.path.abspath(__file__))
        rule_dir = os.path.join(base_dir, "rules")
        
        if os.path.exists(rule_dir):
            for filename in os.listdir(rule_dir):
                if filename.endswith(".json"):
                    with open(os.path.join(rule_dir, filename), "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list): rules.extend(data)
                        else: rules.append(data)
        if debug:
            print(f"🔎 rules loaded: {len(rules)}")

        # 메일 서버 접속 (설정과 인증정보 조합)
        mail = imaplib.IMAP4_SSL(config["email"]["imap_server"])
        mail.login(config["email"]["user"], creds["email"]["pass"])

        for rule in rules:
            target_label = rule.get("target_label", "INBOX")
            status, _ = mail.select(f'"{target_label}"')
            if status != 'OK': continue

            status, messages = mail.search(None, 'UNSEEN')
            if status != 'OK': continue
            if debug:
                count = len(messages[0].split()) if messages and messages[0] else 0
                print(f"📬 label={target_label} unseen={count}")

            for m_id in reversed(messages[0].split()):
                # 규칙 평가 중 읽음 처리되지 않도록 PEEK 사용
                res, msg_data = mail.fetch(m_id, "(BODY.PEEK[])")
                msg = email.message_from_bytes(msg_data[0][1])

                subject = decode_subject(msg["Subject"])
                if debug:
                    print(f"✉️ subject: {subject}")

                evaluation = evaluate_rule_match(rule, subject, *extract_message_bodies(msg), user_info)
                if evaluation["reason"] != "keyword_miss":
                    if debug:
                        print(f"✅ keyword match: {rule.get('filter_keyword')} -> {rule.get('rule_name')}")
                    body_source = evaluation["body_source"]
                    person = evaluation["person"]

                    if debug and not evaluation["matched"]:
                        print(f"🟡 룰 불일치: {rule.get('rule_name')}")
                        print(f"   subject: {subject}")
                        print(f"   person: {person}")
                        print(f"   logic: {rule.get('logic', {})}")
                        print(f"   reason: {evaluation['reason']}")

                    if evaluation["matched"]:
                        logic = rule.get("logic", {})
                        target_key = logic.get("mention_target", "me")
                        mention_id = user_info.get(target_key, {}).get("slack_id", "")

                        buttons = []
                        for l_config in rule.get("links", []):
                            btn_url = l_config.get("url")
                            if l_config.get("type") == "dynamic":
                                btn_url = extract_link(body_source, l_config.get("keyword"))

                            if btn_url:
                                button = {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": l_config["text"], "emoji": True},
                                    "url": btn_url
                                }
                                if "style" in l_config: button["style"] = l_config["style"]
                                buttons.append(button)

                        message_style = rule.get("message_style", "default")
                        if message_style in ("blockquote", "system_log"):
                            main_text = "\n".join(["> " + line for line in build_quote_lines(rule, subject, person, mention_id)])
                        else:
                            main_text = build_message_text(rule, subject, person, mention_id)
                        header_text = build_header_text(rule)

                        blocks = []
                        if header_text:
                            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": header_text}})
                        blocks.append({
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": main_text or "-"
                            },
                            "accessory": buttons[0] if buttons else None
                        })

                        if len(buttons) > 1:
                            blocks.append({"type": "actions", "elements": buttons[1:]})

                        blocks.append({"type": "divider"})

                        # 알림 전송 (config에서 채널 정보 로드)
                        client.chat_postMessage(channel=config["slack"]["target_channel"], blocks=blocks, text=subject)
                        mail.store(m_id, '+FLAGS', '\\Seen')
                        print(f"✅ [{target_label}] 처리 완료: {rule['rule_name']}")

        mail.logout()
    except Exception as e:
        print(f"❌ 시스템 에러: {e}")


def run():
    print("[Rule Engine On...]")
    while True:
        check_mail_and_notify()
        # 60초 대기
        time.sleep(60)

if __name__ == "__main__":
    run()
