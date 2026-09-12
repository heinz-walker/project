import argparse
import email
import json
import os
import sys
from email import policy

try:
    from main import decode_subject, evaluate_rule_match, extract_message_bodies, split_custom_names
except ModuleNotFoundError as exc:
    missing = exc.name or "unknown"
    print(
        "필수 패키지가 없습니다: "
        f"{missing}\n"
        "다음 명령으로 의존성을 먼저 설치하세요:\n"
        "python3 -m pip install -r alert_slack/requirements.txt"
    )
    sys.exit(2)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RULE_DIR = os.path.join(BASE_DIR, "rules")
USERS_PATH = os.path.join(BASE_DIR, "users.json")

FALLBACK_NAMES = ["홍길동", "성춘향", "이몽룡", "변학도", "임꺽정"]


def load_user_info():
    with open(USERS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_rules(selected_rules=None):
    selected = set(selected_rules or [])
    loaded = []
    for filename in sorted(os.listdir(RULE_DIR)):
        if not filename.endswith(".json"):
            continue
        if selected and filename not in selected:
            continue
        path = os.path.join(RULE_DIR, filename)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            for idx, rule in enumerate(data, start=1):
                loaded.append((f"{filename}#{idx}", rule))
        else:
            loaded.append((filename, data))
    return loaded


def pick_matching_name(compare_key, compare_name, user_info):
    if compare_key == "me":
        return user_info.get("me", {}).get("name", "홍길동")
    if compare_key == "leader":
        return user_info.get("leader", {}).get("name", "임꺽정")
    if compare_key == "any":
        return FALLBACK_NAMES[0]
    if compare_key == "custom":
        custom_names = split_custom_names(compare_name)
        return custom_names[0] if custom_names else FALLBACK_NAMES[0]
    return FALLBACK_NAMES[0]


def pick_non_matching_name(used_names):
    normalized = {name.replace(" ", "") for name in used_names if name}
    for candidate in FALLBACK_NAMES:
        if candidate.replace(" ", "") not in normalized:
            return candidate
    return "테스트사용자"


def build_body(drafter, approver, extra_lines=None):
    extras = "\n".join(extra_lines or [])
    return (
        "<html><body>"
        f"<p>기안자: {drafter}</p>"
        f"<p>결재자: {approver}</p>"
        f"<p>{extras}</p>"
        '<a href="https://example.com/doc">바로가기</a>'
        "</body></html>"
    )


def make_positive_case(rule, user_info):
    logic = rule.get("logic", {})
    used_names = []

    drafter = pick_non_matching_name([])
    approver = pick_non_matching_name([drafter])

    field = logic.get("check_field")
    if field and field != "always_pass":
        matched = pick_matching_name(logic.get("compare_with"), logic.get("compare_name", ""), user_info)
        used_names.append(matched)
        if field == "drafter":
            drafter = matched
        elif field == "approver":
            approver = matched

    second_field = logic.get("second_check_field")
    if second_field:
        second_matched = pick_matching_name(
            logic.get("second_compare_with"),
            logic.get("second_compare_name", ""),
            user_info,
        )
        used_names.append(second_matched)
        if second_field == "drafter":
            drafter = second_matched
        elif second_field == "approver":
            approver = second_matched

    exclude_field = logic.get("exclude_field")
    if exclude_field:
        excluded_name = pick_matching_name(
            logic.get("exclude_compare_with"),
            logic.get("exclude_compare_name", ""),
            user_info,
        )
        safe_name = pick_non_matching_name(used_names + [excluded_name, drafter, approver])
        if exclude_field == "drafter":
            drafter = safe_name
        elif exclude_field == "approver":
            approver = safe_name

    subject = f"[TEST] {rule.get('filter_keyword', '')} positive"
    html_body = build_body(drafter, approver)
    return {
        "name": "positive_match",
        "subject": subject,
        "html_body": html_body,
        "text_body": "",
        "expected": True,
    }


def make_keyword_miss_case(rule, user_info):
    case = make_positive_case(rule, user_info)
    case["name"] = "keyword_miss"
    case["subject"] = "[TEST] 키워드 불일치"
    case["expected"] = False
    return case


def make_primary_miss_case(rule, user_info):
    logic = rule.get("logic", {})
    if logic.get("check_field") in (None, "always_pass"):
        return None
    # compare_with == "any" 는 값이 비어있지 않기만 하면 매칭되므로 "1차 조건 불일치" 케이스를 만들 수 없다.
    if logic.get("compare_with") == "any":
        return None

    positive = make_positive_case(rule, user_info)
    used = [user_info.get("me", {}).get("name", ""), user_info.get("leader", {}).get("name", "")]
    used.extend(split_custom_names(logic.get("compare_name", "")))
    miss_name = pick_non_matching_name(used)

    drafter = positive["html_body"]
    approver = positive["html_body"]
    person = extract_persons_from_html(positive["html_body"])
    drafter = person["drafter"]
    approver = person["approver"]

    if logic.get("check_field") == "drafter":
        drafter = miss_name
    else:
        approver = miss_name

    return {
        "name": "primary_condition_miss",
        "subject": positive["subject"],
        "html_body": build_body(drafter, approver),
        "text_body": "",
        "expected": False,
    }


def make_second_miss_case(rule, user_info):
    logic = rule.get("logic", {})
    second_field = logic.get("second_check_field")
    if not second_field:
        return None

    positive = make_positive_case(rule, user_info)
    person = extract_persons_from_html(positive["html_body"])
    used = [user_info.get("me", {}).get("name", ""), user_info.get("leader", {}).get("name", "")]
    used.extend(split_custom_names(logic.get("second_compare_name", "")))
    miss_name = pick_non_matching_name(used + [person["drafter"], person["approver"]])

    drafter = person["drafter"]
    approver = person["approver"]
    if second_field == "drafter":
        drafter = miss_name
    else:
        approver = miss_name

    return {
        "name": "second_condition_miss",
        "subject": positive["subject"],
        "html_body": build_body(drafter, approver),
        "text_body": "",
        "expected": False,
    }


def make_excluded_case(rule, user_info):
    logic = rule.get("logic", {})
    exclude_field = logic.get("exclude_field")
    if not exclude_field:
        return None

    positive = make_positive_case(rule, user_info)
    person = extract_persons_from_html(positive["html_body"])
    excluded_name = pick_matching_name(
        logic.get("exclude_compare_with"),
        logic.get("exclude_compare_name", ""),
        user_info,
    )

    drafter = person["drafter"]
    approver = person["approver"]
    if exclude_field == "drafter":
        drafter = excluded_name
    else:
        approver = excluded_name

    return {
        "name": "excluded",
        "subject": positive["subject"],
        "html_body": build_body(drafter, approver),
        "text_body": "",
        "expected": False,
    }


def make_custom_body_match_case(rule, user_info):
    logic = rule.get("logic", {})
    compare_key = logic.get("compare_with")
    if compare_key != "custom":
        return None

    positive = make_positive_case(rule, user_info)
    person = extract_persons_from_html(positive["html_body"])
    custom_names = split_custom_names(logic.get("compare_name", ""))
    if not custom_names:
        return None

    miss_name = pick_non_matching_name(custom_names + [person["drafter"], person["approver"]])
    extra = [f"본문 참조자: {custom_names[-1]}"]
    if logic.get("check_field") == "drafter":
        person["drafter"] = miss_name
    else:
        person["approver"] = miss_name

    return {
        "name": "custom_name_found_in_body",
        "subject": positive["subject"],
        "html_body": build_body(person["drafter"], person["approver"], extra),
        "text_body": "",
        "expected": True,
    }


def extract_persons_from_html(html_body):
    import re

    def extract(label):
        m = re.search(label + r"\s*[:：]?\s*([^<\n\r]+)", html_body)
        return m.group(1).strip() if m else "미상"

    return {"drafter": extract("기안자"), "approver": extract("결재자")}


def generate_cases(rule, user_info):
    cases = [make_positive_case(rule, user_info), make_keyword_miss_case(rule, user_info)]
    for builder in (make_primary_miss_case, make_second_miss_case, make_excluded_case, make_custom_body_match_case):
        case = builder(rule, user_info)
        if case:
            cases.append(case)
    return cases


def run_synthetic_tests(rules, user_info):
    failures = 0
    total = 0
    for rule_name, rule in rules:
        print(f"\n[Rule] {rule_name} :: {rule.get('rule_name', '')}")
        for case in generate_cases(rule, user_info):
            total += 1
            result = evaluate_rule_match(rule, case["subject"], case["html_body"], case["text_body"], user_info)
            ok = result["matched"] == case["expected"]
            status = "PASS" if ok else "FAIL"
            print(
                f"  - {status} {case['name']}: expected={case['expected']} "
                f"actual={result['matched']} reason={result['reason']} "
                f"drafter={result['person']['drafter']} approver={result['person']['approver']}"
            )
            if not ok:
                failures += 1
    print(f"\nSynthetic summary: total={total} fail={failures}")
    return 1 if failures else 0


def run_eml_test(rules, user_info, eml_path):
    with open(eml_path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.default)

    subject = decode_subject(msg.get("Subject"))
    html_body, text_body = extract_message_bodies(msg)

    print(f"[EML] {eml_path}")
    print(f"Subject: {subject}\n")
    matched_count = 0
    for rule_name, rule in rules:
        result = evaluate_rule_match(rule, subject, html_body, text_body, user_info)
        if result["matched"]:
            matched_count += 1
        print(
            f"- {rule_name}: matched={result['matched']} reason={result['reason']} "
            f"drafter={result['person']['drafter']} approver={result['person']['approver']}"
        )
    print(f"\nEML summary: matched_rules={matched_count}/{len(rules)}")
    return 0


def parse_args():
    parser = argparse.ArgumentParser(description="Alert-bot rule test runner")
    parser.add_argument("--rule", action="append", help="특정 룰 파일만 테스트합니다. 예: --rule rule_approval_leader2.json")
    parser.add_argument("--eml", help="실제 EML 파일을 입력해 모든 룰을 평가합니다.")
    return parser.parse_args()


def main():
    args = parse_args()
    user_info = load_user_info()
    rules = load_rules(args.rule)

    if not rules:
        print("테스트할 룰이 없습니다.")
        return 1

    if args.eml:
        return run_eml_test(rules, user_info, args.eml)
    return run_synthetic_tests(rules, user_info)


if __name__ == "__main__":
    sys.exit(main())
