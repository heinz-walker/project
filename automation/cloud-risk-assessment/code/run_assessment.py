#!/usr/bin/env python3
"""
AWS 위험평가 자동화 스크립트 (읽기 전용)
조회만 수행하며 AWS 리소스를 변경하지 않습니다.
"""

import boto3
import json
import csv
import sys
import os
import argparse
from datetime import datetime, timezone, timedelta
from botocore.exceptions import ClientError, NoCredentialsError

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
# 기준값은 스크립트와 같은 폴더의 settings.json으로 분리한다.
# settings.json이 없거나 항목이 비어 있으면 아래 기본값을 쓴다.
# (settings.json.example을 복사해 settings.json으로 만들어 조정)
DEFAULTS = {
    "default_profile": "default",
    "default_region": "ap-northeast-2",
    "access_key_max_age_days": 90,
    "dangerous_ports": [21, 22, 23, 25, 53, 80, 110, 135, 137, 138, 139, 143,
                        443, 445, 1433, 1521, 3306, 3389, 5432, 5900, 6379,
                        8080, 8443, 9200, 9300, 27017],
}

_SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "settings.json")


def _load_settings(path=_SETTINGS_PATH):
    """settings.json을 읽어 기본값 위에 덮어쓴 설정 dict를 반환한다."""
    cfg = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8") as f:
            user_cfg = json.load(f)
        for k, v in user_cfg.items():
            if v not in (None, "", [], {}):
                cfg[k] = v
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, OSError) as e:
        print(f"[경고] settings.json 로드 실패 — 기본값 사용: {e}")
    return cfg


SETTINGS = _load_settings()
DANGEROUS_PORTS = SETTINGS["dangerous_ports"]
ACCESS_KEY_MAX_AGE_DAYS = SETTINGS["access_key_max_age_days"]

RISK_LEVELS = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}

NOW = datetime.now(timezone.utc)


# ──────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────
def days_since(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (NOW - dt).days


def safe_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ClientError as e:
        return {"_error": str(e)}


# ──────────────────────────────────────────────
# 점검 함수
# ──────────────────────────────────────────────

def check_ec2_instances(session, region):
    """EC2 인스턴스 목록"""
    ec2 = session.client("ec2", region_name=region)
    findings = []
    try:
        paginator = ec2.get_paginator("describe_instances")
        for page in paginator.paginate():
            for reservation in page["Reservations"]:
                for inst in reservation["Instances"]:
                    name = next(
                        (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"),
                        "(no name)"
                    )
                    findings.append({
                        "InstanceId": inst["InstanceId"],
                        "Name": name,
                        "State": inst["State"]["Name"],
                        "Type": inst["InstanceType"],
                        "PublicIp": inst.get("PublicIpAddress", "-"),
                        "PrivateIp": inst.get("PrivateIpAddress", "-"),
                        "LaunchTime": str(inst.get("LaunchTime", "-")),
                    })
    except ClientError as e:
        findings.append({"_error": str(e)})
    return findings


def check_inspector_findings(session, region):
    """Inspector2 Critical/High 취약점"""
    inspector = session.client("inspector2", region_name=region)
    findings = []
    try:
        paginator = inspector.get_paginator("list_findings")
        filt = {
            "severity": [{"comparison": "EQUALS", "value": s}
                         for s in ["CRITICAL", "HIGH"]]
        }
        for page in paginator.paginate(filterCriteria=filt):
            for f in page["findings"]:
                pkg_details = f.get("packageVulnerabilityDetails", {})
                vuln_pkgs   = pkg_details.get("vulnerablePackages", [])
                remediation = f.get("remediation", {}).get("recommendation", {})

                # 취약 패키지 목록 (이름 + 현재버전 → 수정버전)
                pkg_lines = []
                for p in vuln_pkgs:
                    name    = p.get("name", "")
                    ver     = p.get("version", "")
                    fixed   = p.get("fixedInVersion", "미확인")
                    arch    = p.get("arch", "")
                    pkg_lines.append(f"{name} {ver} ({arch}) → 수정버전: {fixed}")

                findings.append({
                    "FindingArn":        f.get("findingArn", "-"),
                    "Severity":          f.get("severity", "-"),
                    "Title":             f.get("title", "-"),
                    "Description":       f.get("description", "-"),
                    "InspectorScore":    f.get("inspectorScore", "-"),
                    "ResourceType":      f.get("resources", [{}])[0].get("type", "-"),
                    "ResourceId":        f.get("resources", [{}])[0].get("id", "-"),
                    "Status":            f.get("status", "-"),
                    "VulnerablePackages": "\n".join(pkg_lines) if pkg_lines else "-",
                    "RemediationText":   remediation.get("text", "-"),
                    "CvssScore":         (pkg_details.get("cvss") or [{}])[0].get("baseScore", "-"),
                    "CvssVector":        (pkg_details.get("cvss") or [{}])[0].get("scoringVector", "-"),
                })
    except ClientError as e:
        if "is not enabled" in str(e) or "AccessDenied" in str(e):
            findings.append({"_error": "Inspector2가 활성화되지 않았거나 접근 권한이 없습니다."})
        else:
            findings.append({"_error": str(e)})
    return findings


def check_security_groups(session, region):
    """Security Group – 위험 포트 또는 0.0.0.0/0 오픈"""
    ec2 = session.client("ec2", region_name=region)
    findings = []
    try:
        paginator = ec2.get_paginator("describe_security_groups")
        for page in paginator.paginate():
            for sg in page["SecurityGroups"]:
                for rule in sg.get("IpPermissions", []):
                    from_port = rule.get("FromPort", 0)
                    to_port = rule.get("ToPort", 65535)
                    proto = rule.get("IpProtocol", "-1")

                    open_to_all = any(
                        r.get("CidrIp") in ("0.0.0.0/0", "::/0")
                        for r in rule.get("IpRanges", []) + rule.get("Ipv6Ranges", [])
                    )
                    if not open_to_all:
                        continue

                    # 전체 포트 오픈 또는 위험 포트 포함 여부 확인
                    if proto == "-1":
                        risky = True
                        port_info = "ALL"
                    else:
                        risky_ports_in_range = [
                            p for p in DANGEROUS_PORTS
                            if from_port <= p <= to_port
                        ]
                        risky = bool(risky_ports_in_range) or (from_port == 0 and to_port == 65535)
                        port_info = f"{from_port}-{to_port}" if from_port != to_port else str(from_port)

                    if risky:
                        name = next(
                            (t["Value"] for t in sg.get("Tags", []) if t["Key"] == "Name"),
                            "-"
                        )
                        findings.append({
                            "GroupId": sg["GroupId"],
                            "GroupName": sg.get("GroupName", "-"),
                            "Name": name,
                            "VpcId": sg.get("VpcId", "-"),
                            "Protocol": proto,
                            "PortRange": port_info,
                            "Direction": "Inbound",
                            "OpenTo": "0.0.0.0/0 or ::/0",
                        })
    except ClientError as e:
        findings.append({"_error": str(e)})
    return findings


def check_iam_admin_users(session):
    """IAM AdministratorAccess 보유 계정 (User/Role/Group)"""
    iam = session.client("iam")
    findings = []
    try:
        paginator = iam.get_paginator("list_entities_for_policy")
        for page in paginator.paginate(
            PolicyArn="arn:aws:iam::aws:policy/AdministratorAccess",
            EntityFilter="User"
        ):
            for user in page["PolicyUsers"]:
                findings.append({
                    "Type": "User",
                    "Name": user["UserName"],
                    "Policy": "AdministratorAccess",
                })
        for page in iam.get_paginator("list_entities_for_policy").paginate(
            PolicyArn="arn:aws:iam::aws:policy/AdministratorAccess",
            EntityFilter="Group"
        ):
            for group in page["PolicyGroups"]:
                # 그룹 소속 유저 목록 조회
                gp = iam.get_paginator("get_group")
                for gpage in gp.paginate(GroupName=group["GroupName"]):
                    for u in gpage["Users"]:
                        findings.append({
                            "Type": "UserViaGroup",
                            "Name": u["UserName"],
                            "Group": group["GroupName"],
                            "Policy": "AdministratorAccess",
                        })
        for page in iam.get_paginator("list_entities_for_policy").paginate(
            PolicyArn="arn:aws:iam::aws:policy/AdministratorAccess",
            EntityFilter="Role"
        ):
            for role in page["PolicyRoles"]:
                findings.append({
                    "Type": "Role",
                    "Name": role["RoleName"],
                    "Policy": "AdministratorAccess",
                })
    except ClientError as e:
        findings.append({"_error": str(e)})
    return findings


def check_mfa_disabled_users(session):
    """MFA 미적용 IAM 사용자"""
    iam = session.client("iam")
    findings = []
    try:
        paginator = iam.get_paginator("list_users")
        for page in paginator.paginate():
            for user in page["Users"]:
                mfa_resp = iam.list_mfa_devices(UserName=user["UserName"])
                if not mfa_resp["MFADevices"]:
                    # 콘솔 접근 가능 여부(로그인 프로파일) 확인
                    has_console = True
                    try:
                        iam.get_login_profile(UserName=user["UserName"])
                    except ClientError as e:
                        if e.response["Error"]["Code"] == "NoSuchEntity":
                            has_console = False
                        else:
                            has_console = "unknown"
                    findings.append({
                        "UserName": user["UserName"],
                        "ConsoleAccess": has_console,
                        "CreatedDate": str(user.get("CreateDate", "-")),
                        "PasswordLastUsed": str(user.get("PasswordLastUsed", "Never")),
                    })
    except ClientError as e:
        findings.append({"_error": str(e)})
    return findings


def check_old_access_keys(session):
    """Access Key 생성 후 90일 초과 계정"""
    iam = session.client("iam")
    findings = []
    try:
        paginator = iam.get_paginator("list_users")
        for page in paginator.paginate():
            for user in page["Users"]:
                keys_resp = iam.list_access_keys(UserName=user["UserName"])
                for key in keys_resp["AccessKeyMetadata"]:
                    age = days_since(key["CreateDate"])
                    if age is not None and age > ACCESS_KEY_MAX_AGE_DAYS:
                        findings.append({
                            "UserName": user["UserName"],
                            "AccessKeyId": key["AccessKeyId"],
                            "Status": key["Status"],
                            "AgeInDays": age,
                            "CreatedDate": str(key["CreateDate"]),
                        })
    except ClientError as e:
        findings.append({"_error": str(e)})
    return findings


def check_public_s3_buckets(session):
    """Public S3 버킷"""
    s3 = session.client("s3")
    findings = []
    try:
        buckets = s3.list_buckets().get("Buckets", [])
        for bucket in buckets:
            name = bucket["Name"]
            issues = []
            try:
                pab = s3.get_public_access_block(Bucket=name)
                conf = pab["PublicAccessBlockConfiguration"]
                if not all([
                    conf.get("BlockPublicAcls", False),
                    conf.get("IgnorePublicAcls", False),
                    conf.get("BlockPublicPolicy", False),
                    conf.get("RestrictPublicBuckets", False),
                ]):
                    issues.append("PublicAccessBlock 미설정 항목 있음")
            except ClientError as e:
                if e.response["Error"]["Code"] == "NoSuchPublicAccessBlockConfiguration":
                    issues.append("PublicAccessBlock 설정 없음")

            try:
                ps = s3.get_bucket_policy_status(Bucket=name)
                if ps["PolicyStatus"].get("IsPublic", False):
                    issues.append("버킷 Policy Public")
            except ClientError as e:
                if e.response["Error"]["Code"] not in ("NoSuchBucketPolicy", "AccessDenied"):
                    issues.append(f"Policy 조회 오류: {e.response['Error']['Code']}")

            if issues:
                findings.append({
                    "BucketName": name,
                    "Issues": ", ".join(issues),
                    "CreationDate": str(bucket.get("CreationDate", "-")),
                })
    except ClientError as e:
        findings.append({"_error": str(e)})
    return findings


def check_unencrypted_ebs(session, region):
    """암호화되지 않은 EBS 볼륨"""
    ec2 = session.client("ec2", region_name=region)
    findings = []
    try:
        paginator = ec2.get_paginator("describe_volumes")
        for page in paginator.paginate():
            for vol in page["Volumes"]:
                if not vol.get("Encrypted", False):
                    name = next(
                        (t["Value"] for t in vol.get("Tags", []) if t["Key"] == "Name"),
                        "-"
                    )
                    attachments = [a["InstanceId"] for a in vol.get("Attachments", [])]
                    findings.append({
                        "VolumeId": vol["VolumeId"],
                        "Name": name,
                        "SizeGiB": vol.get("Size", "-"),
                        "State": vol["State"],
                        "AttachedTo": ", ".join(attachments) if attachments else "Detached",
                        "VolumeType": vol.get("VolumeType", "-"),
                    })
    except ClientError as e:
        findings.append({"_error": str(e)})
    return findings


def check_cloudtrail(session, region):
    """CloudTrail 활성화 여부"""
    ct = session.client("cloudtrail", region_name=region)
    findings = []
    try:
        trails = ct.describe_trails(includeShadowTrails=False).get("trailList", [])
        if not trails:
            findings.append({"Status": "RISK", "Detail": "CloudTrail 트레일이 없습니다."})
            return findings
        for trail in trails:
            try:
                status = ct.get_trail_status(Name=trail["TrailARN"])
                findings.append({
                    "TrailName": trail["Name"],
                    "TrailArn": trail["TrailARN"],
                    "IsLogging": status.get("IsLogging", False),
                    "IsMultiRegion": trail.get("IsMultiRegionTrail", False),
                    "S3Bucket": trail.get("S3BucketName", "-"),
                    "LogFileValidation": trail.get("LogFileValidationEnabled", False),
                    "Status": "OK" if status.get("IsLogging") else "RISK",
                })
            except ClientError as e:
                findings.append({"TrailName": trail["Name"], "_error": str(e)})
    except ClientError as e:
        findings.append({"_error": str(e)})
    return findings


def check_guardduty(session, region):
    """GuardDuty 활성화 여부"""
    gd = session.client("guardduty", region_name=region)
    findings = []
    try:
        detectors = gd.list_detectors().get("DetectorIds", [])
        if not detectors:
            findings.append({"Status": "RISK", "Detail": "GuardDuty 디텍터가 없습니다."})
            return findings
        for det_id in detectors:
            det = gd.get_detector(DetectorId=det_id)
            findings.append({
                "DetectorId": det_id,
                "Status": det.get("Status", "-"),
                "FindingPublishingFrequency": det.get("FindingPublishingFrequency", "-"),
                "ServiceRole": det.get("ServiceRole", "-"),
                "Assessment": "OK" if det.get("Status") == "ENABLED" else "RISK",
            })
    except ClientError as e:
        findings.append({"_error": str(e)})
    return findings


def check_security_hub(session, region):
    """Security Hub 활성화 여부"""
    sh = session.client("securityhub", region_name=region)
    findings = []
    try:
        hub = sh.describe_hub()
        findings.append({
            "HubArn": hub.get("HubArn", "-"),
            "SubscribedAt": str(hub.get("SubscribedAt", "-")),
            "AutoEnableControls": hub.get("AutoEnableControls", False),
            "Status": "OK",
        })
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("InvalidAccessException", "ResourceNotFoundException"):
            findings.append({"Status": "RISK", "Detail": "Security Hub가 활성화되지 않았습니다."})
        else:
            findings.append({"_error": str(e)})
    return findings


def check_aws_config(session, region):
    """AWS Config 활성화 여부"""
    cfg = session.client("config", region_name=region)
    findings = []
    try:
        recorders = cfg.describe_configuration_recorders().get("ConfigurationRecorders", [])
        if not recorders:
            findings.append({"Status": "RISK", "Detail": "Config 레코더가 없습니다."})
            return findings
        statuses = cfg.describe_configuration_recorder_status().get("ConfigurationRecordersStatus", [])
        status_map = {s["name"]: s for s in statuses}
        for rec in recorders:
            st = status_map.get(rec["name"], {})
            findings.append({
                "RecorderName": rec["name"],
                "RoleArn": rec.get("roleARN", "-"),
                "AllSupported": rec.get("recordingGroup", {}).get("allSupported", False),
                "Recording": st.get("recording", False),
                "LastStatus": st.get("lastStatus", "-"),
                "Status": "OK" if st.get("recording") else "RISK",
            })
    except ClientError as e:
        findings.append({"_error": str(e)})
    return findings


def check_rds_public(session, region):
    """RDS 인스턴스 Public Access 여부"""
    rds = session.client("rds", region_name=region)
    findings = []
    try:
        paginator = rds.get_paginator("describe_db_instances")
        for page in paginator.paginate():
            for db in page["DBInstances"]:
                if db.get("PubliclyAccessible", False):
                    findings.append({
                        "DBInstanceIdentifier": db["DBInstanceIdentifier"],
                        "Engine": db.get("Engine", "-"),
                        "EngineVersion": db.get("EngineVersion", "-"),
                        "DBInstanceStatus": db.get("DBInstanceStatus", "-"),
                        "PubliclyAccessible": True,
                        "Endpoint": db.get("Endpoint", {}).get("Address", "-"),
                        "MultiAZ": db.get("MultiAZ", False),
                    })
    except ClientError as e:
        findings.append({"_error": str(e)})
    return findings


def check_public_ebs_snapshots(session, region):
    """EBS Snapshot Public 여부 (소유 계정의 스냅샷 중 공개된 것)"""
    ec2 = session.client("ec2", region_name=region)
    findings = []
    try:
        # RestorableBy='all' 이 아닌 자체 소유 스냅샷 중 공개된 것 조회
        sts = session.client("sts")
        account_id = sts.get_caller_identity()["Account"]

        paginator = ec2.get_paginator("describe_snapshots")
        for page in paginator.paginate(OwnerIds=[account_id]):
            for snap in page["Snapshots"]:
                try:
                    attr = ec2.describe_snapshot_attribute(
                        SnapshotId=snap["SnapshotId"],
                        Attribute="createVolumePermission"
                    )
                    perms = attr.get("CreateVolumePermissions", [])
                    if any(p.get("Group") == "all" for p in perms):
                        name = next(
                            (t["Value"] for t in snap.get("Tags", []) if t["Key"] == "Name"),
                            "-"
                        )
                        findings.append({
                            "SnapshotId": snap["SnapshotId"],
                            "Name": name,
                            "VolumeId": snap.get("VolumeId", "-"),
                            "SizeGiB": snap.get("VolumeSize", "-"),
                            "StartTime": str(snap.get("StartTime", "-")),
                            "Encrypted": snap.get("Encrypted", False),
                        })
                except ClientError:
                    continue
    except ClientError as e:
        findings.append({"_error": str(e)})
    return findings


# ──────────────────────────────────────────────
# 보고서 출력
# ──────────────────────────────────────────────

def print_section(title, findings, key_fields=None):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    if not findings:
        print("  [결과 없음]")
        return
    errors = [f for f in findings if "_error" in f]
    data = [f for f in findings if "_error" not in f]
    if errors:
        for e in errors:
            print(f"  [오류] {e['_error']}")
    if not data:
        return
    print(f"  총 {len(data)}건")
    for i, item in enumerate(data, 1):
        print(f"\n  [{i}]")
        fields = key_fields if key_fields else item.keys()
        for k in fields:
            if k in item:
                print(f"    {k}: {item[k]}")


CHECK_CATEGORIES = {
    "EC2 인스턴스 목록":                  "인프라 현황",
    "Inspector 취약점(Critical/High)":    "취약점 관리",
    "Security Group 위험 포트/0.0.0.0 노출": "네트워크 보안",
    "IAM AdministratorAccess 보유 계정":  "접근 제어",
    "MFA 미적용 사용자":                  "접근 제어",
    "오래된 Access Key(90일 초과)":       "접근 제어",
    "Public S3 버킷":                     "데이터 보호",
    "암호화되지 않은 EBS 볼륨":           "데이터 보호",
    "CloudTrail 활성화 여부":             "보안 모니터링",
    "GuardDuty 활성화 여부":              "보안 모니터링",
    "Security Hub 활성화 여부":           "보안 모니터링",
    "AWS Config 활성화 여부":             "보안 모니터링",
    "RDS Public Access":                  "데이터 보호",
    "EBS Snapshot Public":                "데이터 보호",
}

CHECK_CRITERIA = {
    "EC2 인스턴스 목록":
        "실행 중인 EC2 인스턴스 현황 파악 (정보 수집 항목)",
    "Inspector 취약점(Critical/High)":
        "AWS Inspector2에서 탐지된 Critical/High 등급 취약점이 없어야 함",
    "Security Group 위험 포트/0.0.0.0 노출":
        "SSH(22), RDP(3389), DB포트 등 위험 포트가 0.0.0.0/0(전체 허용)으로 열려있지 않아야 함",
    "IAM AdministratorAccess 보유 계정":
        "AdministratorAccess 정책이 불필요한 계정/역할에 부여되지 않아야 함",
    "MFA 미적용 사용자":
        "콘솔 접근 권한이 있는 모든 IAM 사용자는 MFA가 활성화되어 있어야 함",
    "오래된 Access Key(90일 초과)":
        "IAM Access Key는 생성 후 90일 이내에 교체되어야 하며, 미사용 키는 비활성화 또는 삭제해야 함",
    "Public S3 버킷":
        "S3 버킷은 퍼블릭 액세스 차단(Public Access Block)이 모두 활성화되어 있어야 함",
    "암호화되지 않은 EBS 볼륨":
        "모든 EBS 볼륨은 암호화가 활성화되어 있어야 함",
    "CloudTrail 활성화 여부":
        "모든 리전에서 CloudTrail이 활성화(IsLogging=true)되어 있어야 함",
    "GuardDuty 활성화 여부":
        "GuardDuty 디텍터가 활성화(ENABLED)되어 있어야 함",
    "Security Hub 활성화 여부":
        "Security Hub가 활성화되어 보안 표준 준수 여부를 모니터링해야 함",
    "AWS Config 활성화 여부":
        "AWS Config 레코더가 활성화(recording=true)되어 리소스 변경 이력을 기록해야 함",
    "RDS Public Access":
        "RDS 인스턴스의 PubliclyAccessible 속성이 false여야 함",
    "EBS Snapshot Public":
        "EBS 스냅샷의 공개 공유 권한(createVolumePermission=all)이 없어야 함",
}


def _judge(check_name, findings):
    """진단결과 판정: Y(양호), N(취약), N/A(해당없음)"""
    errors = [f for f in findings if "_error" in f]
    data = [f for f in findings if "_error" not in f]
    if errors and not data:
        return "N/A"
    if check_name == "EC2 인스턴스 목록":
        return "N/A"
    kind = CHECK_RISK_ITEMS.get(check_name, "RISK")
    if kind == "CONTROL":
        ok = all(f.get("Status") == "OK" for f in data) if data else False
        return "Y" if ok else "N"
    return "N" if data else "Y"


def _findings_summary(check_name, findings):
    """진단 의견 한 줄 요약"""
    errors = [f for f in findings if "_error" in f]
    data = [f for f in findings if "_error" not in f]
    if errors and not data:
        return errors[0]["_error"]
    if check_name == "EC2 인스턴스 목록":
        running = sum(1 for f in data if f.get("State") == "running")
        return f"총 {len(data)}개 인스턴스 (실행 중: {running}개)"
    kind = CHECK_RISK_ITEMS.get(check_name, "RISK")
    if kind == "CONTROL":
        ok = all(f.get("Status") == "OK" for f in data) if data else False
        if ok:
            return "활성화 확인됨 (양호)"
        else:
            detail = data[0].get("Detail", "비활성화") if data else "설정 없음"
            return f"미활성화 — {detail}"
    if not data:
        return "해당 없음 (양호)"
    return f"총 {len(data)}건 발견 (취약)"


def _findings_detail(check_name, findings, max_rows=30):
    """현황 상세 텍스트"""
    data = [f for f in findings if "_error" not in f]
    if not data:
        return "해당 없음"
    lines = []
    for i, item in enumerate(data[:max_rows], 1):
        parts = [f"{k}: {v}" for k, v in item.items()]
        lines.append(f"[{i}] " + " | ".join(parts))
    if len(data) > max_rows:
        lines.append(f"... 외 {len(data) - max_rows}건 (JSON 보고서 참고)")
    return "\n".join(lines)


def save_excel_report(results, output_path):
    from openpyxl import Workbook
    from openpyxl.styles import (Font, PatternFill, Alignment,
                                  Border, Side, GradientFill)
    from openpyxl.utils import get_column_letter

    meta = results["meta"]
    checks = results["checks"]
    ts = meta["timestamp"]
    dt_str = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}"

    wb = Workbook()

    # ── 공통 스타일 ──────────────────────────────────────
    NAVY   = "1A1A2E"
    BLUE   = "2C5F8A"
    LBLUE  = "D6E4F0"
    GREEN  = "1E7A3D"
    LGREEN = "D4EDDA"
    RED    = "C0392B"
    LRED   = "FADADD"
    GRAY   = "6C757D"
    LGRAY  = "F2F2F2"
    WHITE  = "FFFFFF"
    YELLOW = "FFF3CD"

    def ft(bold=False, color="000000", size=10, name="맑은 고딕"):
        return Font(bold=bold, color=color, size=size, name=name)

    def fill(hex_color):
        return PatternFill("solid", fgColor=hex_color)

    def align(h="center", v="center", wrap=False):
        return Alignment(horizontal=h, vertical=v, wrap_text=wrap)

    thin = Side(style="thin", color="CCCCCC")
    med  = Side(style="medium", color="888888")

    def border(left=thin, right=thin, top=thin, bottom=thin):
        return Border(left=left, right=right, top=top, bottom=bottom)

    def set_cell(ws, row, col, value, font=None, fill_=None,
                 align_=None, border_=None, number_format=None):
        c = ws.cell(row=row, column=col, value=value)
        if font:    c.font = font
        if fill_:   c.fill = fill_
        if align_:  c.alignment = align_
        if border_: c.border = border_
        if number_format: c.number_format = number_format
        return c

    # ════════════════════════════════════════════════════
    # Sheet 0 — 진단 개요 (범위·방법론·한계)
    # ════════════════════════════════════════════════════
    ws0 = wb.active
    ws0.title = "진단 개요"
    ws0.sheet_view.showGridLines = False
    ws0.column_dimensions["A"].width = 2
    ws0.column_dimensions["B"].width = 18
    ws0.column_dimensions["C"].width = 90
    ws0.row_dimensions[1].height = 6

    ws0.merge_cells("B2:C2")
    c = ws0.cell(row=2, column=2, value="AWS 클라우드 보안 위험평가 — 진단 개요")
    c.font = Font(bold=True, color=WHITE, size=16, name="맑은 고딕")
    c.fill = fill(NAVY)
    c.alignment = align("center", "center")
    ws0.row_dimensions[2].height = 36

    def _section_title(ws, row, text):
        ws.merge_cells(f"B{row}:C{row}")
        cc = ws.cell(row=row, column=2, value=text)
        cc.font = ft(bold=True, color=WHITE, size=11)
        cc.fill = fill(BLUE)
        cc.alignment = align("left", "center")
        ws.row_dimensions[row].height = 22
        return row + 1

    def _kv_row(ws, row, label, value, height=18):
        ws.row_dimensions[row].height = height
        cl = ws.cell(row=row, column=2, value=label)
        cl.font = ft(bold=True)
        cl.fill = fill(LGRAY)
        cl.alignment = align("left", "center")
        cl.border = border()
        cv = ws.cell(row=row, column=3, value=value)
        cv.font = ft()
        cv.alignment = align("left", "center", wrap=True)
        cv.border = border()
        return row + 1

    r0 = 4
    r0 = _section_title(ws0, r0, "1. 진단 대상 및 범위")
    r0 = _kv_row(ws0, r0, "진단 계정", meta["account"])
    r0 = _kv_row(ws0, r0, "진단 리전", f"{meta['region']} (단일 리전 — 타 리전 리소스는 본 진단 범위에 포함되지 않음)")
    r0 = _kv_row(ws0, r0, "진단 일시", dt_str)
    r0 = _kv_row(ws0, r0, "진단자", meta["arn"].split("/")[-1])
    r0 = _kv_row(ws0, r0, "점검 대상 서비스", "EC2, Inspector2, VPC Security Group, IAM, S3, EBS, CloudTrail, GuardDuty, Security Hub, AWS Config, RDS (총 13개 서비스 영역)")
    r0 += 1

    r0 = _section_title(ws0, r0, "2. 진단 방법론")
    r0 = _kv_row(ws0, r0, "수행 방식",
                 "AWS CLI(boto3) 기반 자동화 스크립트로 각 서비스의 설정·리소스 정보를 API로 조회하여 사전 정의된 보안 기준과 비교 판정. "
                 "리소스를 생성·수정·삭제하지 않는 읽기 전용(Read-Only) 점검.")
    r0 = _kv_row(ws0, r0, "판정 기준", "Y(양호) / N(취약) / N/A(해당없음) 3단계 판정. 세부 기준은 상세 시트의 \"진단 기준\" 열 참고.")
    r0 = _kv_row(ws0, r0, "집계 방식",
                 "요약 시트의 \"전체(ALL)/취약(N)\" 건수는 상세 시트에 나열된 개별 발견 건수를 합산한 값. "
                 "예: 네트워크 보안 21건 = 위험 포트가 0.0.0.0/0으로 열린 개별 규칙 21건.")
    r0 += 1

    r0 = _section_title(ws0, r0, "3. 한계 및 유의사항")
    limitations = [
        "\"전체(ALL)/취약(N)\" 건수는 발견된 위반 사례 수 기준이며, 전체 자산 모집단(예: 전체 IAM 사용자·S3 버킷·EBS 볼륨 총수) 대비 비율이 아님. "
        "즉, 전체 모집단 중 양호한 리소스 수는 별도로 집계하지 않았음.",
        "Inspector 취약점은 Critical/High 등급만 조회하였으며 Medium/Low 등급 취약점은 본 진단에 포함되지 않음.",
        "애플리케이션 코드·웹 취약점(OWASP 등) 진단은 범위에 포함되지 않으며, 인프라·클라우드 설정 레벨 진단에 한정됨.",
        "본 결과는 진단 일시 기준의 스냅샷이며, 이후 발생한 설정 변경 사항은 반영되지 않음.",
        "일부 항목(CloudTrail·GuardDuty·Security Hub·AWS Config)은 계정 단위 활성화 여부만 확인하며, 세부 규칙·정책 적용 수준까지는 검증하지 않음.",
    ]
    for i, text in enumerate(limitations, 1):
        r0 = _kv_row(ws0, r0, f"({i})", text, height=32)

    # ════════════════════════════════════════════════════
    # Sheet 1 — AWS 클라우드 진단 자산 목록
    # ════════════════════════════════════════════════════
    ws1 = wb.create_sheet("AWS 클라우드 진단 자산 목록")
    ws1.sheet_view.showGridLines = False
    ws1.column_dimensions["A"].width = 2
    ws1.row_dimensions[1].height = 6

    # ── 제목 ──
    ws1.merge_cells("B2:K2")
    c = ws1.cell(row=2, column=2, value="AWS 클라우드 보안 위험평가 진단 결과")
    c.font = Font(bold=True, color=WHITE, size=16, name="맑은 고딕")
    c.fill = fill(NAVY)
    c.alignment = align("center", "center")
    ws1.row_dimensions[2].height = 36

    # ── 메타 정보 ──
    meta_info = [
        ("진단 계정", meta["account"]),
        ("리전",     meta["region"]),
        ("진단 일시", dt_str),
        ("진단자",   meta["arn"].split("/")[-1]),
    ]
    for i, (label, val) in enumerate(meta_info):
        r = 3 + i
        ws1.row_dimensions[r].height = 18
        ws1.merge_cells(f"B{r}:C{r}")
        c = ws1.cell(row=r, column=2, value=label)
        c.font = ft(bold=True, color=WHITE)
        c.fill = fill(BLUE)
        c.alignment = align("center")
        c.border = border()
        ws1.merge_cells(f"D{r}:K{r}")
        c2 = ws1.cell(row=r, column=4, value=val)
        c2.font = ft()
        c2.fill = fill(LBLUE)
        c2.alignment = align("left")
        c2.border = border()
    ws1.row_dimensions[7].height = 10

    # ── 요약 통계 헤더 ──
    r = 8
    ws1.row_dimensions[r].height = 22
    headers1 = ["No.", "항목 영역", "점검 항목", "전체(ALL)", "양호(Y)", "취약(N)", "해당없음(N/A)", "보안수준(%)"]
    col_widths = [2, 6, 16, 40, 10, 9, 9, 12, 12]
    for j, col_w in enumerate(col_widths):
        ws1.column_dimensions[get_column_letter(j + 1)].width = col_w

    for j, h in enumerate(headers1, 2):
        c = ws1.cell(row=r, column=j, value=h)
        c.font = ft(bold=True, color=WHITE)
        c.fill = fill(BLUE)
        c.alignment = align("center", "center")
        c.border = border(left=med, right=med, top=med, bottom=med)

    # ── 데이터 행 ──
    # 집계 기준: "전체(ALL)/취약(N)"은 상세 시트(진단결과)의 개별 발견 건수와
    # 동일하게 맞춘다. CONTROL형 항목(CloudTrail 등 계정 단위 설정 1건)은
    # 원래부터 단일 항목이므로 그대로 두고, 목록형 항목(취약 사례 나열)은
    # 발견 건수를 그대로 ALL/N에 반영한다. 전체 자산 모집단(예: 전체 IAM
    # 사용자 수) 대비 비율이 아니라는 점은 하단 안내/방법론 문구로 별도 설명.
    row_data = []
    total_all = total_y = total_n = total_na = 0
    for name, findings in checks.items():
        data = [f for f in findings if "_error" not in f]
        judge = _judge(name, findings)
        kind = CHECK_RISK_ITEMS.get(name, "RISK")
        if name == "EC2 인스턴스 목록":
            cnt_all = len(data) if data else 1
            cnt_y   = 0
            cnt_n   = 0
            cnt_na  = cnt_all
        elif kind == "CONTROL":
            cnt_all = 1
            cnt_y   = 1 if judge == "Y"   else 0
            cnt_n   = 1 if judge == "N"   else 0
            cnt_na  = 1 if judge == "N/A" else 0
        else:
            cnt_all = len(data) if data else 1
            cnt_y   = 0 if data else 1
            cnt_n   = len(data)
            cnt_na  = 0
        total_all += cnt_all
        total_y   += cnt_y
        total_n   += cnt_n
        total_na  += cnt_na
        row_data.append((CHECK_CATEGORIES.get(name, "-"), name,
                         cnt_all, cnt_y, cnt_n, cnt_na, judge))

    for i, (cat, name, ca, cy, cn, cna, judge) in enumerate(row_data, 1):
        r = 8 + i
        ws1.row_dimensions[r].height = 18
        bg = LGREEN if judge == "Y" else (LRED if judge == "N" else LGRAY)
        row_vals = [i, cat, name, ca, cy, cn, cna,
                    f"{cy/(ca-cna)*100:.1f}%" if (ca - cna) > 0 else "N/A"]
        for j, v in enumerate(row_vals, 2):
            c = ws1.cell(row=r, column=j, value=v)
            c.font = ft(bold=(judge == "N"))
            c.fill = fill(bg)
            c.alignment = align("center" if j != 4 else "left")
            c.border = border()

    # ── 합계 행 ──
    r = 8 + len(row_data) + 1
    ws1.row_dimensions[r].height = 20
    ws1.merge_cells(f"B{r}:D{r}")
    c = ws1.cell(row=r, column=2, value="합 계")
    c.font = ft(bold=True, color=WHITE)
    c.fill = fill(NAVY)
    c.alignment = align("center")
    c.border = border(left=med, right=med, top=med, bottom=med)
    sec_total = total_all - total_na
    score = f"{total_y/sec_total*100:.1f}%" if sec_total > 0 else "N/A"
    for j, v in enumerate([total_all, total_y, total_n, total_na, score], 5):
        c = ws1.cell(row=r, column=j, value=v)
        c.font = ft(bold=True, color=WHITE)
        c.fill = fill(NAVY)
        c.alignment = align("center")
        c.border = border(left=med, right=med, top=med, bottom=med)

    r += 2
    ws1.row_dimensions[r].height = 10

    # ── 영역별 통계 ──
    r += 1
    ws1.merge_cells(f"B{r}:K{r}")
    c = ws1.cell(row=r, column=2, value="항목 영역 별 진단 통계")
    c.font = ft(bold=True, color=WHITE, size=11)
    c.fill = fill(BLUE)
    c.alignment = align("center")
    ws1.row_dimensions[r].height = 22

    r += 1
    cat_headers = ["항목 영역", "전체(ALL)", "양호(Y)", "취약(N)", "해당없음(N/A)", "보안수준(%)"]
    for j, h in enumerate(cat_headers, 2):
        c = ws1.cell(row=r, column=j, value=h)
        c.font = ft(bold=True, color=WHITE)
        c.fill = fill(BLUE)
        c.alignment = align("center")
        c.border = border()
    ws1.row_dimensions[r].height = 18

    from collections import defaultdict
    cat_stats = defaultdict(lambda: [0, 0, 0, 0])
    for cat, name, ca, cy, cn, cna, judge in row_data:
        cat_stats[cat][0] += ca
        cat_stats[cat][1] += cy
        cat_stats[cat][2] += cn
        cat_stats[cat][3] += cna

    for cat, (ca, cy, cn, cna) in cat_stats.items():
        r += 1
        ws1.row_dimensions[r].height = 18
        sec = ca - cna
        score = f"{cy/sec*100:.1f}%" if sec > 0 else "N/A"
        for j, v in enumerate([cat, ca, cy, cn, cna, score], 2):
            c = ws1.cell(row=r, column=j, value=v)
            c.font = ft()
            c.fill = fill(LGRAY if j % 2 == 0 else WHITE)
            c.alignment = align("center" if j != 2 else "left")
            c.border = border()

    # ── 집계 기준 안내 ──
    r += 2
    ws1.row_dimensions[r].height = 28
    ws1.merge_cells(f"B{r}:K{r}")
    c = ws1.cell(
        row=r, column=2,
        value=("※ 위 표의 전체(ALL)/취약(N) 건수는 상세 시트(AWS 클라우드 진단 결과)의 개별 발견 건수를 그대로 합산한 값입니다. "
               "전체 자산 모집단(예: 전체 IAM 사용자·S3 버킷·EBS 볼륨 수) 대비 비율이 아니라, 이번 진단에서 실제로 발견된 위반 사례 수 기준입니다. "
               "진단 범위·방법론·한계는 \"진단 개요\" 시트를 참고하십시오.")
    )
    c.font = ft(color=GRAY, size=9)
    c.alignment = align("left", "center", wrap=True)

    # ── 헬퍼 함수들 ──────────────────────────────────────
    CRIT_PORTS = {6379, 1433, 1521, 3306, 5432, 27017, 9200, 9300}
    HIGH_PORTS  = {22, 23, 3389, 5900, 445, 135}

    PORT_NAMES = {
        21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP",
        53: "DNS", 80: "HTTP", 110: "POP3", 135: "RPC",
        137: "NetBIOS", 138: "NetBIOS", 139: "NetBIOS",
        143: "IMAP", 443: "HTTPS", 445: "SMB",
        1433: "MSSQL", 1521: "Oracle", 3306: "MySQL",
        3389: "RDP", 5432: "PostgreSQL", 5900: "VNC",
        6379: "Redis", 8080: "HTTP-Alt", 8443: "HTTPS-Alt",
        9200: "Elasticsearch", 9300: "Elasticsearch",
        27017: "MongoDB",
    }

    def _port_label(port_str, proto):
        if proto == "-1":
            return "전체 프로토콜/포트"
        try:
            if "-" in str(port_str):
                lo, hi = port_str.split("-")
                ports_in = [p for p in PORT_NAMES if int(lo) <= p <= int(hi)]
                names = "/".join(PORT_NAMES[p] for p in ports_in[:3])
                return f"{port_str} ({names}{'...' if len(ports_in) > 3 else ''})"
            else:
                p = int(port_str)
                name = PORT_NAMES.get(p, "")
                return f"{port_str}({name})" if name else str(port_str)
        except Exception:
            return str(port_str)

    def _severity(check_name, finding):
        sev = finding.get("Severity", "").upper()
        if sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            return sev
        name = check_name
        if name == "Security Group 위험 포트/0.0.0.0 노출":
            proto = finding.get("Protocol", "")
            port_str = finding.get("PortRange", "")
            if proto == "-1":
                return "CRITICAL"
            try:
                ports = set(range(int(port_str.split("-")[0]), int(port_str.split("-")[1]) + 1)) \
                    if "-" in str(port_str) else {int(port_str)}
                if ports & CRIT_PORTS: return "CRITICAL"
                if ports & HIGH_PORTS: return "HIGH"
            except Exception:
                pass
            return "MEDIUM"
        if name == "IAM AdministratorAccess 보유 계정":
            return "HIGH" if finding.get("Type") == "User" else "MEDIUM"
        if name == "MFA 미적용 사용자":
            return "HIGH" if finding.get("ConsoleAccess") is True else "MEDIUM"
        if name == "오래된 Access Key(90일 초과)":
            try:
                return "HIGH" if int(finding.get("AgeInDays", 0)) > 365 else "MEDIUM"
            except Exception:
                return "MEDIUM"
        if name == "Public S3 버킷":
            return "HIGH" if "Policy Public" in finding.get("Issues", "") else "MEDIUM"
        if name == "암호화되지 않은 EBS 볼륨":
            return "MEDIUM"
        if name in ("CloudTrail 활성화 여부", "GuardDuty 활성화 여부", "AWS Config 활성화 여부"):
            return "HIGH" if finding.get("Status") in ("RISK",) or \
                             finding.get("Assessment") == "RISK" else "-"
        if name == "Security Hub 활성화 여부":
            return "MEDIUM" if finding.get("Status") == "RISK" else "-"
        if name in ("RDS Public Access", "EBS Snapshot Public"):
            return "HIGH"
        return "-"

    def _specific_check_name(check_name, finding):
        """점검항목: 각 finding에 맞는 구체적인 이름"""
        f = finding
        proto = f.get("Protocol", "")
        port  = f.get("PortRange", "")

        if check_name == "Inspector 취약점(Critical/High)":
            import re as _re
            title = f.get("Title", check_name)
            score = f.get("InspectorScore", "")
            score_str = f" [Score: {score}]" if score and score != "-" else ""

            # CVE/KB ID 추출 (접두어용)
            cve_m = _re.match(r'(CVE-\d+-\d+|KB\d+)', title)
            cve_id = cve_m.group(1) if cve_m else ""

            # 점검항목명은 한글 라벨만 사용 (영문 취약점 설명은 별도 "취약점 설명" 열로 분리)
            if cve_id.startswith("CVE"):
                label = "Linux 커널 취약점"
            elif cve_id.startswith("KB"):
                label = "Windows Server 보안 업데이트 미적용"
            else:
                label = "OS 취약점"

            if cve_id:
                return f"[{cve_id}] {label}{score_str}"
            return f"{label}{score_str}"

        if check_name == "Security Group 위험 포트/0.0.0.0 노출":
            proto_str = "전체 포트" if proto == "-1" else \
                        f"{proto.upper()} {_port_label(port, proto)}"
            return f"{proto_str} 인터넷(0.0.0.0/0) 허용"

        if check_name == "IAM AdministratorAccess 보유 계정":
            t = f.get("Type", "")
            name = f.get("Name", "")
            via = f" (via 그룹: {f.get('Group','')})" if t == "UserViaGroup" else ""
            return f"AdministratorAccess 보유 — {t}: {name}{via}"

        if check_name == "MFA 미적용 사용자":
            return f"MFA 미적용 — {f.get('UserName', '')}"

        if check_name == "오래된 Access Key(90일 초과)":
            return f"Access Key 장기 미교체 — {f.get('UserName', '')} ({f.get('AgeInDays', '')}일 경과)"

        if check_name == "Public S3 버킷":
            return f"S3 퍼블릭 액세스 미차단 — {f.get('BucketName', '')}"

        if check_name == "암호화되지 않은 EBS 볼륨":
            return f"EBS 볼륨 암호화 미적용 — {f.get('VolumeId', '')}"

        if check_name == "CloudTrail 활성화 여부":
            if f.get("Status") == "RISK":
                return "CloudTrail 미활성화"
            return f"CloudTrail 로깅 정상 — {f.get('TrailName', '')}"

        if check_name == "GuardDuty 활성화 여부":
            if f.get("Status") == "RISK" or f.get("Detail"):
                return "GuardDuty 디텍터 없음"
            return f"GuardDuty 활성화 — {f.get('DetectorId', '')}"

        if check_name == "Security Hub 활성화 여부":
            return "Security Hub 미활성화" if f.get("Status") == "RISK" \
                   else f"Security Hub 활성화"

        if check_name == "AWS Config 활성화 여부":
            if f.get("Status") == "RISK":
                return "AWS Config 레코더 없음"
            return f"Config 레코더 정상 — {f.get('RecorderName', '')}"

        if check_name == "RDS Public Access":
            return f"RDS 인터넷 노출 — {f.get('DBInstanceIdentifier', '')}"

        if check_name == "EBS Snapshot Public":
            return f"EBS 스냅샷 공개 공유 — {f.get('SnapshotId', '')}"

        return check_name

    def _resource_id(check_name, finding):
        f = finding
        m = {
            "Inspector 취약점(Critical/High)":       f.get("ResourceId", "-"),
            "Security Group 위험 포트/0.0.0.0 노출": f.get("GroupId", "-"),
            "IAM AdministratorAccess 보유 계정":     f.get("Name", "-"),
            "MFA 미적용 사용자":                     f.get("UserName", "-"),
            "오래된 Access Key(90일 초과)":          f.get("AccessKeyId", "-"),
            "Public S3 버킷":                        f.get("BucketName", "-"),
            "암호화되지 않은 EBS 볼륨":              f.get("VolumeId", "-"),
            "CloudTrail 활성화 여부":                f.get("TrailArn", f.get("Detail", "-")),
            "GuardDuty 활성화 여부":                 f.get("DetectorId", f.get("Detail", "-")),
            "Security Hub 활성화 여부":              f.get("HubArn", f.get("Detail", "-")),
            "AWS Config 활성화 여부":                f.get("RecorderName", f.get("Detail", "-")),
            "RDS Public Access":                     f.get("DBInstanceIdentifier", "-"),
            "EBS Snapshot Public":                   f.get("SnapshotId", "-"),
        }
        return m.get(check_name, "-")

    INSPECTOR_RESOURCE_TYPE_KO = {
        "AWS_EC2_INSTANCE": "EC2 인스턴스",
        "AWS_ECR_REPOSITORY": "ECR 저장소",
        "AWS_LAMBDA_FUNCTION": "Lambda 함수",
    }

    def _resource_type(check_name, finding):
        """리소스 ID가 구체적으로 어떤 유형의 리소스인지 표시"""
        f = finding
        if check_name == "Inspector 취약점(Critical/High)":
            rt = f.get("ResourceType", "-")
            return INSPECTOR_RESOURCE_TYPE_KO.get(rt, rt)
        if check_name == "Security Group 위험 포트/0.0.0.0 노출":
            return "Security Group"
        if check_name == "IAM AdministratorAccess 보유 계정":
            t = f.get("Type", "")
            return {"User": "IAM 사용자", "Role": "IAM 역할",
                    "UserViaGroup": "IAM 사용자(그룹 소속)"}.get(t, "IAM")
        if check_name == "MFA 미적용 사용자":
            return "IAM 사용자"
        if check_name == "오래된 Access Key(90일 초과)":
            return "IAM Access Key"
        if check_name == "Public S3 버킷":
            return "S3 버킷"
        if check_name == "암호화되지 않은 EBS 볼륨":
            return "EBS 볼륨"
        if check_name == "CloudTrail 활성화 여부":
            return "CloudTrail 트레일"
        if check_name == "GuardDuty 활성화 여부":
            return "GuardDuty 디텍터"
        if check_name == "Security Hub 활성화 여부":
            return "Security Hub"
        if check_name == "AWS Config 활성화 여부":
            return "AWS Config 레코더"
        if check_name == "RDS Public Access":
            return "RDS 인스턴스"
        if check_name == "EBS Snapshot Public":
            return "EBS 스냅샷"
        return "-"

    def _status_text(check_name, finding):
        """리소스의 현재 상태값"""
        f = finding
        if check_name == "Inspector 취약점(Critical/High)":
            return f.get("Status", "-")          # ACTIVE / CLOSED
        if check_name == "Security Group 위험 포트/0.0.0.0 노출":
            return "노출 중"
        if check_name == "IAM AdministratorAccess 보유 계정":
            return f"부여됨 ({f.get('Type', '-')})"
        if check_name == "MFA 미적용 사용자":
            return "콘솔 접근 있음" if f.get("ConsoleAccess") is True else "콘솔 접근 없음"
        if check_name == "오래된 Access Key(90일 초과)":
            return f"{f.get('Status','-')} ({f.get('AgeInDays','-')}일 경과)"
        if check_name == "Public S3 버킷":
            return f.get("Issues", "-")
        if check_name == "암호화되지 않은 EBS 볼륨":
            return f.get("State", "-")
        if check_name == "CloudTrail 활성화 여부":
            if f.get("Status") == "RISK": return "미활성화"
            return "로깅 중" if f.get("IsLogging") else "로깅 중단"
        if check_name == "GuardDuty 활성화 여부":
            return f.get("Status", f.get("Detail", "-"))
        if check_name == "Security Hub 활성화 여부":
            return f.get("Status", "-")
        if check_name == "AWS Config 활성화 여부":
            if f.get("Status") == "RISK": return "레코더 없음"
            return "기록 중" if f.get("Recording") else "기록 중단"
        if check_name == "RDS Public Access":
            return "공개 노출"
        if check_name == "EBS Snapshot Public":
            return "공개 공유"
        return "-"

    def _situation(check_name, finding):
        """현황: 왜 취약한지 실제 상황을 서술"""
        f = finding

        if check_name == "Inspector 취약점(Critical/High)":
            # 영향 리소스/상태/취약점 설명/점수/취약 패키지/조치 방법은
            # 각각 전용 열로 분리되어 있으므로 현황에는 별도 표기하지 않음.
            return "-"

        if check_name == "Security Group 위험 포트/0.0.0.0 노출":
            gid   = f.get("GroupId", "")
            gname = f.get("GroupName", "")
            vpc   = f.get("VpcId", "")
            proto = f.get("Protocol", "")
            port  = f.get("PortRange", "")
            proto_str = "전체 프로토콜" if proto == "-1" \
                        else proto.upper()
            port_label = _port_label(port, proto)
            return (f"Security Group [{gname} / {gid}] (VPC: {vpc})의\n"
                    f"인바운드 규칙에서 {proto_str} {port_label} 포트가\n"
                    f"0.0.0.0/0(전체 인터넷)으로 허용되어 있어\n"
                    f"외부에서 해당 포트에 무제한 접근 가능.")

        if check_name == "IAM AdministratorAccess 보유 계정":
            t    = f.get("Type", "")
            name = f.get("Name", "")
            grp  = f.get("Group", "")
            if t == "UserViaGroup":
                return (f"IAM 사용자 [{name}]이 그룹 [{grp}]을 통해\n"
                        f"AdministratorAccess 정책을 간접 보유.\n"
                        f"모든 AWS 리소스에 대한 완전한 권한 보유.")
            if t == "User":
                return (f"IAM 사용자 [{name}]에게 AdministratorAccess 정책이\n"
                        f"직접 부여됨. 최소 권한 원칙에 위배.")
            return (f"IAM 역할 [{name}]에 AdministratorAccess 정책 부여됨.\n"
                    f"SSO 또는 자동화 용도인지 검토 필요.")

        if check_name == "MFA 미적용 사용자":
            user    = f.get("UserName", "")
            console = f.get("ConsoleAccess", False)
            last_pw = f.get("PasswordLastUsed", "없음")
            console_str = "콘솔 로그인 가능 계정" if console \
                          else "콘솔 비활성화 계정 (Access Key 전용)"
            return (f"IAM 사용자 [{user}]에 MFA가 설정되지 않음.\n"
                    f"계정 유형: {console_str}.\n"
                    f"자격증명 탈취 시 추가 인증 없이 접근 가능.\n"
                    f"마지막 콘솔 로그인: {last_pw}")

        if check_name == "오래된 Access Key(90일 초과)":
            user    = f.get("UserName", "")
            key_id  = f.get("AccessKeyId", "")
            age     = f.get("AgeInDays", "")
            status  = f.get("Status", "")
            created = f.get("CreatedDate", "")
            return (f"[{user}] 계정의 Access Key [{key_id}]가\n"
                    f"{age}일 동안 교체되지 않은 채 {status} 상태 유지 중.\n"
                    f"생성일: {created}\n"
                    f"장기 미교체로 인한 키 유출 및 무단 접근 위험 존재.")

        if check_name == "Public S3 버킷":
            bucket = f.get("BucketName", "")
            issues = f.get("Issues", "")
            return (f"S3 버킷 [{bucket}]의 퍼블릭 액세스 차단 설정이 미흡함.\n"
                    f"문제 항목: {issues}\n"
                    f"버킷 정책 또는 ACL을 통해 객체가 인터넷에 공개될 수 있음.")

        if check_name == "암호화되지 않은 EBS 볼륨":
            vid      = f.get("VolumeId", "")
            size     = f.get("SizeGiB", "")
            vtype    = f.get("VolumeType", "")
            state    = f.get("State", "")
            attached = f.get("AttachedTo", "Detached")
            att_str  = f"인스턴스 [{attached}]에 연결됨" \
                       if attached != "Detached" else "미연결(가용 상태)"
            return (f"EBS 볼륨 [{vid}] ({size}GiB, {vtype})이 암호화되지 않은 상태.\n"
                    f"현재 상태: {state} / {att_str}\n"
                    f"물리적 스토리지 접근 시 데이터 평문 노출 위험.")

        if check_name == "CloudTrail 활성화 여부":
            if f.get("Status") == "RISK":
                return ("CloudTrail 트레일이 존재하지 않아 AWS API 호출 및\n"
                        "리소스 변경 이력이 전혀 기록되지 않음.\n"
                        "보안 사고 발생 시 감사 추적 불가.")
            trail  = f.get("TrailName", "")
            bucket = f.get("S3Bucket", "")
            multi  = "멀티리전 적용" if f.get("IsMultiRegion") else "단일 리전"
            valid  = "로그 파일 무결성 검증 활성화" if f.get("LogFileValidation") \
                     else "로그 파일 무결성 검증 미설정(권고 사항)"
            return (f"CloudTrail [{trail}]이 정상 로깅 중.\n"
                    f"적용 범위: {multi} / S3 저장: [{bucket}]\n"
                    f"{valid}")

        if check_name == "GuardDuty 활성화 여부":
            if f.get("Detail") or f.get("Status") == "RISK":
                return ("GuardDuty 디텍터가 존재하지 않음.\n"
                        "AWS 계정 내 악의적 활동, 자격증명 탈취,\n"
                        "암호화폐 채굴 등 위협 탐지 체계 없음.")
            det_id = f.get("DetectorId", "")
            freq   = f.get("FindingPublishingFrequency", "")
            return (f"GuardDuty 디텍터 [{det_id}] 활성화됨.\n"
                    f"위협 탐지 결과 발행 주기: {freq}")

        if check_name == "Security Hub 활성화 여부":
            if f.get("Status") == "RISK":
                return ("Security Hub가 활성화되지 않아\n"
                        "통합 보안 표준(CIS, AWS 모범 사례) 준수 여부\n"
                        "자동 모니터링 불가.")
            auto = "자동 제어 활성화" if f.get("AutoEnableControls") \
                   else "자동 제어 비활성화"
            return (f"Security Hub 활성화됨. {auto}\n"
                    f"구독일: {f.get('SubscribedAt', '-')}")

        if check_name == "AWS Config 활성화 여부":
            if f.get("Status") == "RISK":
                return ("AWS Config 레코더가 없어 리소스 구성 변경\n"
                        "이력 추적 불가. 보안 정책 준수 자동 평가 불가.")
            rec     = f.get("RecorderName", "")
            all_sup = "전체 리소스 유형 기록" if f.get("AllSupported") \
                      else "일부 리소스만 기록"
            last    = f.get("LastStatus", "")
            return (f"Config 레코더 [{rec}] 정상 기록 중.\n"
                    f"{all_sup} / 마지막 상태: {last}")

        if check_name == "RDS Public Access":
            db       = f.get("DBInstanceIdentifier", "")
            engine   = f.get("Engine", "")
            ver      = f.get("EngineVersion", "")
            endpoint = f.get("Endpoint", "")
            return (f"RDS 인스턴스 [{db}] ({engine} {ver})의\n"
                    f"PubliclyAccessible 속성이 true로 설정됨.\n"
                    f"인터넷에서 DB 엔드포인트 [{endpoint}]에 직접 접근 가능.")

        if check_name == "EBS Snapshot Public":
            snap = f.get("SnapshotId", "")
            vol  = f.get("VolumeId", "")
            size = f.get("SizeGiB", "")
            enc  = "암호화됨" if f.get("Encrypted") else "암호화 미적용"
            return (f"EBS 스냅샷 [{snap}] (볼륨: {vol}, {size}GiB, {enc})이\n"
                    f"공개 공유(createVolumePermission=all) 상태.\n"
                    f"모든 AWS 사용자가 해당 스냅샷으로 볼륨 생성 가능.")

        return "-"

    def _vuln_description(check_name, finding):
        """취약점 설명: Inspector가 제공하는 원문(영문) 취약점 설명. 그 외 항목은 해당 없음."""
        if check_name == "Inspector 취약점(Critical/High)":
            desc = finding.get("Description", "")
            return desc if desc and desc != "-" else "-"
        return "-"

    def _vuln_score(check_name, finding):
        """취약점 점수: Inspector Score / CVSS Base / CVSS Vector"""
        if check_name != "Inspector 취약점(Critical/High)":
            return "-"
        score = finding.get("InspectorScore", "")
        cvss  = finding.get("CvssScore", "")
        vec   = finding.get("CvssVector", "")
        if not score or score == "-":
            return "-"
        score_str = str(score)
        if cvss and cvss != "-":
            score_str += f" / CVSS Base: {cvss}"
        if vec and vec != "-":
            score_str += f" ({vec})"
        return score_str

    def _vuln_packages(check_name, finding):
        """취약 패키지: Inspector가 식별한 취약 패키지 및 수정 버전"""
        if check_name != "Inspector 취약점(Critical/High)":
            return "-"
        pkgs = finding.get("VulnerablePackages", "")
        return pkgs if pkgs and pkgs != "-" else "-"

    def _remediation(check_name, finding):
        """조치 방법: Inspector가 제공하는 조치 권고"""
        if check_name != "Inspector 취약점(Critical/High)":
            return "-"
        remed = finding.get("RemediationText", "")
        return remed if remed and remed != "-" else "-"

    def _criteria(check_name, finding):
        """진단기준: 해당 항목에 맞는 실질적인 보안 기준"""
        sev  = finding.get("Severity", "").upper()
        name = check_name

        if name == "Inspector 취약점(Critical/High)":
            if sev == "CRITICAL":
                return ("CVSS 9.0 이상의 치명적 취약점. "
                        "원격 코드 실행·권한 상승 등 심각한 피해 가능. "
                        "즉각적인 패치 적용 필요.")
            return ("CVSS 7.0~8.9의 고위험 취약점. "
                    "조속한 패치 또는 완화 조치 적용 필요.")

        if name == "Security Group 위험 포트/0.0.0.0 노출":
            proto = finding.get("Protocol", "")
            port  = finding.get("PortRange", "")
            if proto == "-1":
                return "모든 프로토콜/포트의 인터넷 허용은 금지. 필요한 포트만 특정 IP 대역으로 제한해야 함."
            pl = _port_label(port, proto)
            return (f"{pl} 포트는 업무상 필요한 특정 IP·대역만 허용해야 하며, "
                    "0.0.0.0/0(전체 인터넷) 허용은 금지.")

        if name == "IAM AdministratorAccess 보유 계정":
            return ("최소 권한 원칙에 따라 AdministratorAccess는 필수 관리자에게만 부여. "
                    "일반 사용자·서비스 계정에는 업무 범위의 최소 권한 정책 적용.")

        if name == "MFA 미적용 사용자":
            return ("IAM 사용자 콘솔 로그인 및 Access Key 사용 시 MFA 필수 적용. "
                    "콘솔 비활성 계정도 Access Key 탈취 대비 MFA 권고.")

        if name == "오래된 Access Key(90일 초과)":
            age = 0
            try: age = int(finding.get("AgeInDays", 0))
            except Exception: pass
            thresh = "1년 이상" if age > 365 else "90일 이상"
            return (f"Access Key는 90일 이내 주기적으로 교체해야 함. "
                    f"현재 {thresh} 미교체 상태. 미사용 키는 즉시 비활성화·삭제.")

        if name == "Public S3 버킷":
            return ("S3 버킷의 퍼블릭 액세스 차단(Block Public Access) 4개 항목 모두 활성화 필요. "
                    "정적 웹사이트 호스팅 목적이라도 불필요한 항목은 최소화.")

        if name == "암호화되지 않은 EBS 볼륨":
            return ("모든 EBS 볼륨은 AWS KMS(또는 기본 관리형 키)를 사용한 암호화 적용 필요. "
                    "개인정보·민감 데이터가 포함된 볼륨은 특히 필수.")

        if name == "CloudTrail 활성화 여부":
            return ("전체 리전에서 CloudTrail 활성화 필수. "
                    "멀티리전 트레일 사용 권고, 로그 파일 무결성 검증 활성화 권고.")

        if name == "GuardDuty 활성화 여부":
            return ("계정 내 모든 리전에서 GuardDuty 활성화 필수. "
                    "위협 탐지 결과는 정기적으로 검토하고 즉각 대응.")

        if name == "Security Hub 활성화 여부":
            return ("Security Hub 활성화 후 AWS 기본 보안 모범 사례(FSBP) 및 "
                    "CIS 표준 적용 권고. 발견 사항 정기 검토 및 조치.")

        if name == "AWS Config 활성화 여부":
            return ("모든 리전에서 AWS Config 레코더 활성화 필수. "
                    "전체 리소스 유형 기록 및 S3 버킷 저장 설정 권고.")

        if name == "RDS Public Access":
            return ("RDS 인스턴스의 PubliclyAccessible 속성은 false로 설정. "
                    "외부 접근이 필요한 경우 ALB·Bastion Host 경유 또는 VPN 사용.")

        if name == "EBS Snapshot Public":
            return ("EBS 스냅샷의 공개 공유(Public) 권한 설정 금지. "
                    "타 계정 공유가 필요한 경우 특정 Account ID만 허용.")

        return "-"

    SEV_STYLE = {
        "CRITICAL": ("7B0000", "FADADD"),
        "HIGH":     ("7D3C00", "FDEBD0"),
        "MEDIUM":   ("7D6608", "FEF9E7"),
        "LOW":      ("1A5276", "D6EAF8"),
        "-":        (GRAY,     LGRAY),
        "OK":       (GREEN,    LGREEN),
    }

    # ════════════════════════════════════════════════════
    # Sheet 2 — AWS 클라우드 진단 결과 (개별 행)
    # ════════════════════════════════════════════════════
    ws2 = wb.create_sheet("AWS 클라우드 진단 결과")
    ws2.sheet_view.showGridLines = False
    ws2.column_dimensions["A"].width = 2

    # No | 항목영역 | 점검항목 | 심각도 | 리소스유형 | 리소스ID | 상태 | 진단결과 | 진단기준
    # | 취약점설명 | 취약점 점수 | 취약 패키지 | 조치 방법 | 현황
    col_defs = [
        ("B", "No.",              5),
        ("C", "항목 영역",       13),
        ("D", "점검 항목",       34),
        ("E", "심각도",           9),
        ("F", "리소스 유형",     14),
        ("G", "리소스 ID",       24),
        ("H", "상  태",          16),
        ("I", "진단결과\n(Y/N/N/A)", 9),
        ("J", "진단 기준",       34),
        ("K", "취약점 설명",     44),
        ("L", "취약점 점수",     20),
        ("M", "취약 패키지",     30),
        ("N", "조치 방법",       30),
        ("O", "현  황",          30),
    ]
    for col_letter, _, width in col_defs:
        ws2.column_dimensions[col_letter].width = width

    ws2.row_dimensions[1].height = 6

    ws2.merge_cells("B2:O2")
    c = ws2.cell(row=2, column=2,
                 value="AWS 클라우드 보안 위험평가 진단 결과 (개별 항목)")
    c.font = Font(bold=True, color=WHITE, size=14, name="맑은 고딕")
    c.fill = fill(NAVY)
    c.alignment = align("center", "center")
    ws2.row_dimensions[2].height = 32

    r = 3
    ws2.row_dimensions[r].height = 26
    for j, (_, header, _) in enumerate(col_defs, 2):
        c = ws2.cell(row=r, column=j, value=header)
        c.font = ft(bold=True, color=WHITE)
        c.fill = fill(BLUE)
        c.alignment = align("center", "center", wrap=True)
        c.border = border(left=med, right=med, top=med, bottom=med)

    ws2.freeze_panes = "B4"

    SKIP_IN_DETAIL = {"EC2 인스턴스 목록"}

    r = 4
    seq = 0
    for check_name, findings in checks.items():
        if check_name in SKIP_IN_DETAIL:
            continue
        data   = [f for f in findings if "_error" not in f]
        errors = [f for f in findings if "_error" in f]
        cat    = CHECK_CATEGORIES.get(check_name, "-")

        # 이상없음(양호) 또는 오류: 1행
        if not data:
            seq += 1
            judge      = _judge(check_name, findings)
            item_name  = check_name
            rtype      = _resource_type(check_name, {})
            rid        = errors[0]["_error"][:60] if errors else "-"
            status_val = "오류" if errors else "이상 없음"
            situation  = errors[0]["_error"] if errors else "발견된 항목 없음 (양호)"
            crit_text  = _criteria(check_name, {})
            vulndesc   = "-"
            vscore     = "-"
            vpkgs      = "-"
            vremed     = "-"
            row_fill   = LGREEN if judge == "Y" else LGRAY
            j_fc, j_bg = (GREEN, LGREEN) if judge == "Y" else (GRAY, LGRAY)

            ws2.row_dimensions[r].height = 18
            vals = [seq, cat, item_name, "-", rtype, rid, status_val, judge, crit_text,
                    vulndesc, vscore, vpkgs, vremed, situation]
            for j, v in enumerate(vals, 2):
                c = ws2.cell(row=r, column=j, value=v)
                c.font = ft(bold=True, color=j_fc) if j == 9 else ft()
                c.fill = fill(j_bg if j == 9 else row_fill)
                c.alignment = align("center" if j in (2, 5, 9) else "left", "center", wrap=True)
                c.border = border()
            r += 1
            continue

        for finding in data:
            seq       += 1
            sev        = _severity(check_name, finding)
            judge      = _judge(check_name, [finding])
            item_name  = _specific_check_name(check_name, finding)
            rtype      = _resource_type(check_name, finding)
            rid        = _resource_id(check_name, finding)
            status_val = _status_text(check_name, finding)
            crit_text  = _criteria(check_name, finding)
            vulndesc   = _vuln_description(check_name, finding)
            vscore     = _vuln_score(check_name, finding)
            vpkgs      = _vuln_packages(check_name, finding)
            vremed     = _remediation(check_name, finding)
            situation  = _situation(check_name, finding)

            sev_fc, sev_bg = SEV_STYLE.get(sev, (GRAY, LGRAY))
            if judge == "Y":
                j_fc, j_bg = SEV_STYLE["OK"]
                row_fill   = LGREEN
            elif judge == "N":
                row_fill = LRED if sev in ("CRITICAL", "HIGH") else YELLOW
                j_fc, j_bg = RED, LRED
            else:
                j_fc, j_bg = GRAY, LGRAY
                row_fill   = LGRAY

            line_cnt = max(situation.count("\n"), vulndesc.count("\n"), vpkgs.count("\n")) + 1
            ws2.row_dimensions[r].height = min(max(20, line_cnt * 14 + 8), 280)

            vals = [seq, cat, item_name, sev, rtype, rid, status_val, judge, crit_text,
                    vulndesc, vscore, vpkgs, vremed, situation]
            for j, v in enumerate(vals, 2):
                c = ws2.cell(row=r, column=j, value=v)
                if j == 5:   # 심각도
                    c.font = ft(bold=True, color=sev_fc, size=10)
                    c.fill = fill(sev_bg)
                elif j == 9: # 진단결과
                    c.font = ft(bold=True, color=j_fc)
                    c.fill = fill(j_bg)
                else:
                    c.font = ft()
                    c.fill = fill(row_fill)
                c.alignment = align("center" if j in (2, 5, 9) else "left", "top", wrap=True)
                c.border = border()
            r += 1

    wb.save(output_path)
    print(f"[Excel 저장] {output_path}")


def save_json(results, output_path):
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[JSON 저장] {output_path}")


def save_summary_csv(results, output_path):
    rows = []
    for check_name, findings in results["checks"].items():
        errors = [f for f in findings if "_error" in f]
        data = [f for f in findings if "_error" not in f]
        status = "오류" if errors else ("발견" if data else "이상없음")
        rows.append({
            "점검항목": check_name,
            "결과": status,
            "건수": len(data),
            "오류": errors[0]["_error"] if errors else "",
        })
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["점검항목", "결과", "건수", "오류"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"[CSV 저장] {output_path}")


# 항목별 위험 분류 (이상 있으면 RISK, 없으면 OK, 오류면 ERROR)
CHECK_RISK_ITEMS = {
    "EC2 인스턴스 목록": "INFO",
    "Inspector 취약점(Critical/High)": "RISK",
    "Security Group 위험 포트/0.0.0.0 노출": "RISK",
    "IAM AdministratorAccess 보유 계정": "RISK",
    "MFA 미적용 사용자": "RISK",
    "오래된 Access Key(90일 초과)": "RISK",
    "Public S3 버킷": "RISK",
    "암호화되지 않은 EBS 볼륨": "RISK",
    "CloudTrail 활성화 여부": "CONTROL",
    "GuardDuty 활성화 여부": "CONTROL",
    "Security Hub 활성화 여부": "CONTROL",
    "AWS Config 활성화 여부": "CONTROL",
    "RDS Public Access": "RISK",
    "EBS Snapshot Public": "RISK",
}


def _html_table(data):
    if not data:
        return '<p class="no-data">이상 없음</p>'
    keys = list(data[0].keys())
    rows_html = ""
    for row in data:
        cells = ""
        for k in keys:
            val = str(row.get(k, ""))
            # 위험 값 강조
            if val in ("RISK", "False", "True") or (k == "AgeInDays" and val.isdigit() and int(val) > 365):
                if val == "RISK" or (k == "AgeInDays" and int(val) > 365):
                    cells += f'<td class="cell-risk">{val}</td>'
                elif val == "True":
                    cells += f'<td class="cell-ok">{val}</td>'
                else:
                    cells += f'<td>{val}</td>'
            else:
                cells += f"<td>{val}</td>"
        rows_html += f"<tr>{cells}</tr>"
    headers = "".join(f"<th>{k}</th>" for k in keys)
    return f"""
    <div class="table-wrap">
      <table>
        <thead><tr>{headers}</tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>"""


def save_html_report(results, output_path):
    meta = results["meta"]
    checks = results["checks"]
    ts = meta["timestamp"]
    dt_str = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}"

    # 요약 카드 계산
    summary_rows = []
    risk_count = 0
    ok_count = 0
    for name, findings in checks.items():
        errors = [f for f in findings if "_error" in f]
        data = [f for f in findings if "_error" not in f]
        kind = CHECK_RISK_ITEMS.get(name, "RISK")

        if errors:
            badge = "ERROR"
            badge_class = "badge-error"
        elif kind == "INFO":
            badge = f"{len(data)}건"
            badge_class = "badge-info"
        elif kind == "CONTROL":
            # Status 필드로 판단
            is_ok = all(f.get("Status") == "OK" for f in data) if data else False
            badge = "정상" if is_ok else "비활성"
            badge_class = "badge-ok" if is_ok else "badge-risk"
            if not is_ok:
                risk_count += 1
            else:
                ok_count += 1
        else:
            badge = f"{len(data)}건 발견" if data else "이상없음"
            badge_class = "badge-risk" if data else "badge-ok"
            if data:
                risk_count += 1
            else:
                ok_count += 1

        summary_rows.append((name, badge, badge_class, len(data), kind))

    # 섹션별 상세 HTML 생성
    sections_html = ""
    for i, (name, findings) in enumerate(checks.items(), 1):
        errors = [f for f in findings if "_error" in f]
        data = [f for f in findings if "_error" not in f]
        kind = CHECK_RISK_ITEMS.get(name, "RISK")

        error_html = ""
        if errors:
            error_html = f'<p class="error-msg">오류: {errors[0]["_error"]}</p>'

        table_html = _html_table(data) if data else ""
        count_badge = f'<span class="count">{len(data)}건</span>' if data else '<span class="count ok">이상없음</span>'

        sections_html += f"""
        <section id="section-{i}">
          <h2>{i}. {name} {count_badge}</h2>
          {error_html}
          {table_html}
        </section>"""

    # 요약 테이블
    summary_html = ""
    for name, badge, badge_class, cnt, kind in summary_rows:
        summary_html += f"""
        <tr>
          <td>{name}</td>
          <td><span class="badge {badge_class}">{badge}</span></td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AWS 위험평가 보고서 — {meta['account']}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f0f2f5; color: #1a1a2e; font-size: 14px; }}
  a {{ color: #4361ee; text-decoration: none; }}

  /* 헤더 */
  header {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: #fff; padding: 32px 40px; }}
  header h1 {{ font-size: 22px; font-weight: 700; margin-bottom: 8px; }}
  header .meta {{ font-size: 13px; color: #a0aec0; line-height: 1.8; }}
  header .meta span {{ margin-right: 28px; }}

  /* 레이아웃 */
  .container {{ max-width: 1280px; margin: 0 auto; padding: 32px 24px; }}

  /* 요약 대시보드 */
  .dashboard {{ background: #fff; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,.08); padding: 28px 32px; margin-bottom: 32px; }}
  .dashboard h2 {{ font-size: 16px; font-weight: 700; margin-bottom: 20px; color: #2d3748; border-bottom: 2px solid #e2e8f0; padding-bottom: 12px; }}
  .dashboard table {{ width: 100%; border-collapse: collapse; }}
  .dashboard table td {{ padding: 10px 14px; border-bottom: 1px solid #f0f0f0; font-size: 13px; }}
  .dashboard table tr:last-child td {{ border-bottom: none; }}
  .dashboard table td:first-child {{ font-weight: 500; width: 55%; }}

  /* 배지 */
  .badge {{ display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }}
  .badge-risk  {{ background: #fff5f5; color: #c53030; border: 1px solid #feb2b2; }}
  .badge-ok    {{ background: #f0fff4; color: #276749; border: 1px solid #9ae6b4; }}
  .badge-info  {{ background: #ebf8ff; color: #2b6cb0; border: 1px solid #90cdf4; }}
  .badge-error {{ background: #fffaf0; color: #c05621; border: 1px solid #fbd38d; }}

  /* 섹션 */
  section {{ background: #fff; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,.08); padding: 28px 32px; margin-bottom: 24px; }}
  section h2 {{ font-size: 15px; font-weight: 700; color: #2d3748; margin-bottom: 18px; display: flex; align-items: center; gap: 10px; }}
  .count {{ font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 12px; background: #fff5f5; color: #c53030; border: 1px solid #feb2b2; }}
  .count.ok {{ background: #f0fff4; color: #276749; border: 1px solid #9ae6b4; }}

  /* 테이블 */
  .table-wrap {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  thead tr {{ background: #f7fafc; }}
  th {{ padding: 10px 14px; text-align: left; font-weight: 600; color: #4a5568; border-bottom: 2px solid #e2e8f0; white-space: nowrap; }}
  td {{ padding: 9px 14px; border-bottom: 1px solid #f0f0f0; vertical-align: top; word-break: break-all; }}
  tr:hover td {{ background: #fafafa; }}
  .cell-risk {{ color: #c53030; font-weight: 600; }}
  .cell-ok   {{ color: #276749; font-weight: 600; }}
  .no-data   {{ color: #48bb78; font-weight: 600; padding: 8px 0; }}
  .error-msg {{ color: #c05621; background: #fffaf0; border: 1px solid #fbd38d; padding: 10px 14px; border-radius: 6px; margin-bottom: 12px; font-size: 13px; }}

  /* 네비게이션 */
  nav {{ background: #fff; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,.08); padding: 20px 28px; margin-bottom: 28px; }}
  nav h3 {{ font-size: 13px; font-weight: 700; color: #718096; margin-bottom: 12px; text-transform: uppercase; letter-spacing: .5px; }}
  nav ul {{ list-style: none; display: flex; flex-wrap: wrap; gap: 8px; }}
  nav ul li a {{ font-size: 12px; padding: 4px 12px; border-radius: 6px; background: #edf2f7; color: #4a5568; font-weight: 500; transition: background .15s; }}
  nav ul li a:hover {{ background: #4361ee; color: #fff; }}
</style>
</head>
<body>

<header>
  <h1>AWS 위험평가 보고서</h1>
  <div class="meta">
    <span>계정: {meta['account']}</span>
    <span>리전: {meta['region']}</span>
    <span>프로필: {meta['profile']}</span>
    <span>점검일시: {dt_str}</span>
  </div>
</header>

<div class="container">

  <!-- 요약 대시보드 -->
  <div class="dashboard">
    <h2>점검 항목 요약</h2>
    <table>
      <tbody>{summary_html}
      </tbody>
    </table>
  </div>

  <!-- 네비게이션 -->
  <nav>
    <h3>바로가기</h3>
    <ul>
      {''.join(f'<li><a href="#section-{i+1}">{name}</a></li>' for i, (name, *_) in enumerate(summary_rows))}
    </ul>
  </nav>

  <!-- 상세 결과 -->
  {sections_html}

</div>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[HTML 저장] {output_path}")


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="AWS 위험평가 자동화 스크립트 (읽기 전용)")
    parser.add_argument("--profile", default=SETTINGS["default_profile"],
                        help="AWS 프로필 이름 (기본값은 settings.json)")
    parser.add_argument("--region", default=SETTINGS["default_region"],
                        help="AWS 리전 (기본값은 settings.json)")
    parser.add_argument("--output-dir", default=None, help="보고서 저장 경로 (기본: reports/)")
    args = parser.parse_args()

    # 출력 경로 설정
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.dirname(script_dir)
    output_dir = args.output_dir or os.path.join(base_dir, "reports")
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"\n{'#'*60}")
    print(f"  AWS 위험평가 자동화 스크립트")
    print(f"  Profile : {args.profile}")
    print(f"  Region  : {args.region}")
    print(f"  Started : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*60}")

    try:
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        # 인증 확인
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        print(f"\n  Account : {identity['Account']}")
        print(f"  ARN     : {identity['Arn']}")
    except (NoCredentialsError, ClientError) as e:
        print(f"\n[오류] AWS 인증 실패: {e}")
        sys.exit(1)

    checks = {}

    print("\n[1/14] EC2 인스턴스 목록 조회 중...")
    checks["EC2 인스턴스 목록"] = check_ec2_instances(session, args.region)

    print("[2/14] Inspector 취약점(Critical/High) 조회 중...")
    checks["Inspector 취약점(Critical/High)"] = check_inspector_findings(session, args.region)

    print("[3/14] Security Group 위험 포트 및 0.0.0.0/0 노출 조회 중...")
    checks["Security Group 위험 포트/0.0.0.0 노출"] = check_security_groups(session, args.region)

    print("[4/14] IAM AdministratorAccess 보유 계정 조회 중...")
    checks["IAM AdministratorAccess 보유 계정"] = check_iam_admin_users(session)

    print("[5/14] MFA 미적용 사용자 조회 중...")
    checks["MFA 미적용 사용자"] = check_mfa_disabled_users(session)

    print("[6/14] 오래된 Access Key(90일 초과) 조회 중...")
    checks["오래된 Access Key(90일 초과)"] = check_old_access_keys(session)

    print("[7/14] Public S3 버킷 조회 중...")
    checks["Public S3 버킷"] = check_public_s3_buckets(session)

    print("[8/14] 암호화되지 않은 EBS 볼륨 조회 중...")
    checks["암호화되지 않은 EBS 볼륨"] = check_unencrypted_ebs(session, args.region)

    print("[9/14] CloudTrail 활성화 여부 조회 중...")
    checks["CloudTrail 활성화 여부"] = check_cloudtrail(session, args.region)

    print("[10/14] GuardDuty 활성화 여부 조회 중...")
    checks["GuardDuty 활성화 여부"] = check_guardduty(session, args.region)

    print("[11/14] Security Hub 활성화 여부 조회 중...")
    checks["Security Hub 활성화 여부"] = check_security_hub(session, args.region)

    print("[12/14] AWS Config 활성화 여부 조회 중...")
    checks["AWS Config 활성화 여부"] = check_aws_config(session, args.region)

    print("[13/14] RDS Public Access 여부 조회 중...")
    checks["RDS Public Access"] = check_rds_public(session, args.region)

    print("[14/14] EBS Snapshot Public 여부 조회 중...")
    checks["EBS Snapshot Public"] = check_public_ebs_snapshots(session, args.region)

    # ── 콘솔 출력 ──
    print_section("1. EC2 인스턴스 목록", checks["EC2 인스턴스 목록"])
    print_section("2. Inspector 취약점(Critical/High)", checks["Inspector 취약점(Critical/High)"],
                  ["Severity", "Title", "ResourceType", "ResourceId", "Status"])
    print_section("3. Security Group 위험 포트/0.0.0.0 노출", checks["Security Group 위험 포트/0.0.0.0 노출"])
    print_section("4. IAM AdministratorAccess 보유 계정", checks["IAM AdministratorAccess 보유 계정"])
    print_section("5. MFA 미적용 사용자", checks["MFA 미적용 사용자"])
    print_section("6. 오래된 Access Key(90일 초과)", checks["오래된 Access Key(90일 초과)"])
    print_section("7. Public S3 버킷", checks["Public S3 버킷"])
    print_section("8. 암호화되지 않은 EBS 볼륨", checks["암호화되지 않은 EBS 볼륨"])
    print_section("9. CloudTrail 활성화 여부", checks["CloudTrail 활성화 여부"])
    print_section("10. GuardDuty 활성화 여부", checks["GuardDuty 활성화 여부"])
    print_section("11. Security Hub 활성화 여부", checks["Security Hub 활성화 여부"])
    print_section("12. AWS Config 활성화 여부", checks["AWS Config 활성화 여부"])
    print_section("13. RDS Public Access", checks["RDS Public Access"])
    print_section("14. EBS Snapshot Public", checks["EBS Snapshot Public"])

    # ── 결과 저장 ──
    results = {
        "meta": {
            "profile": args.profile,
            "region": args.region,
            "account": identity["Account"],
            "arn": identity["Arn"],
            "timestamp": timestamp,
        },
        "checks": checks,
    }

    json_path  = os.path.join(output_dir, f"risk_assessment_{timestamp}.json")
    csv_path   = os.path.join(output_dir, f"risk_assessment_{timestamp}_summary.csv")
    html_path  = os.path.join(output_dir, f"risk_assessment_{timestamp}.html")
    excel_path = os.path.join(output_dir, f"risk_assessment_{timestamp}.xlsx")
    save_json(results, json_path)
    save_summary_csv(results, csv_path)
    save_html_report(results, html_path)
    save_excel_report(results, excel_path)

    print(f"\n{'#'*60}")
    print(f"  점검 완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*60}\n")


if __name__ == "__main__":
    main()
