"""Environment configuration shared by Lambdas, scripts, and the voice server."""
import os

try:  # python-dotenv is not installed in Lambda; env vars come from the function config there
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
SONIC_REGION = os.getenv("SONIC_REGION", "us-east-1")

FAIL_MODE_PARAM = os.getenv("FAIL_MODE_PARAM", "/pilotlight/checkout/fail_mode")
ALARM_NAME = os.getenv("ALARM_NAME", "pilotlight-checkout-5xx")

# DynamoDB tables (connect branch)
TIMELINE_TABLE = os.getenv("TIMELINE_TABLE", "pilotlight-timeline")
INCIDENTS_TABLE = os.getenv("INCIDENTS_TABLE", "pilotlight-incidents")

# CloudWatch Logs groups
CHECKOUT_LOG_GROUP = os.getenv("CHECKOUT_LOG_GROUP", "/aws/lambda/pilotlight-checkout")
CONFIG_AUDIT_LOG_GROUP = os.getenv("CONFIG_AUDIT_LOG_GROUP", "/pilotlight/config-audit")
TIMELINE_LOG_GROUP = os.getenv("TIMELINE_LOG_GROUP", "/pilotlight/timeline")
INCIDENTS_LOG_GROUP = os.getenv("INCIDENTS_LOG_GROUP", "/pilotlight/incidents")

# Local state (flag value, incident records)
STATE_DIR = os.getenv("STATE_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".state"))

# Alarm rule
ALARM_WINDOW_SECONDS = int(os.getenv("ALARM_WINDOW_SECONDS", "10"))
ALARM_THRESHOLD = int(os.getenv("ALARM_THRESHOLD", "3"))
CHECKOUT_PORT = int(os.getenv("CHECKOUT_PORT", "8080"))

BOX_CLIENT_ID = os.getenv("BOX_CLIENT_ID", "")
BOX_CLIENT_SECRET = os.getenv("BOX_CLIENT_SECRET", "")
BOX_ENTERPRISE_ID = os.getenv("BOX_ENTERPRISE_ID", "")
BOX_RUNBOOKS_FOLDER_ID = os.getenv("BOX_RUNBOOKS_FOLDER_ID", "")
BOX_INCIDENTS_FOLDER_ID = os.getenv("BOX_INCIDENTS_FOLDER_ID", "")
BOX_REVIEWER_LOGIN = os.getenv("BOX_REVIEWER_LOGIN", "")

SONIC_MODEL_ID = os.getenv("SONIC_MODEL_ID", "amazon.nova-2-sonic-v1:0")
TEXT_MODEL_ID = os.getenv("TEXT_MODEL_ID", "")

CONNECT_INSTANCE_ID = os.getenv("CONNECT_INSTANCE_ID", "")
CONNECT_CONTACT_FLOW_ID = os.getenv("CONNECT_CONTACT_FLOW_ID", "")
CONNECT_SOURCE_PHONE = os.getenv("CONNECT_SOURCE_PHONE", "")
CONNECT_QUEUE_ID = os.getenv("CONNECT_QUEUE_ID", "")
ONCALL_PHONE = os.getenv("ONCALL_PHONE", "")
PAGE_PHONE = os.getenv("PAGE_PHONE", "")

# Code-level check that the caller said "confirm" before a remediation runs. Never disable in production.
REQUIRE_SPOKEN_CONFIRM = os.getenv("REQUIRE_SPOKEN_CONFIRM", "true").lower() != "false"

VOICE_SERVER_URL = os.getenv("VOICE_SERVER_URL", "").rstrip("/")

# Operator dashboard (dashboard/app.py)
DASHBOARD_USER = os.getenv("DASHBOARD_USER", "admin")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")  # no default: login is refused until set
DASHBOARD_SECRET = os.getenv("DASHBOARD_SECRET", "")

# GitHub (for auto-fix PR creation)
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
