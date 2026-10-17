"""Environment configuration shared by Lambdas, scripts, and the voice server."""
import os

try:  # python-dotenv is not installed in Lambda; env vars come from the function config there
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

AWS_REGION = os.getenv("AWS_REGION", "us-east-2")
# Nova 2 Sonic is not offered in us-east-2, so the voice stream stays in us-east-1
SONIC_REGION = os.getenv("SONIC_REGION", "us-east-1")

FAIL_MODE_PARAM = os.getenv("FAIL_MODE_PARAM", "/pilotlight/checkout/fail_mode")
ALARM_NAME = os.getenv("ALARM_NAME", "pilotlight-checkout-5xx")

# CloudWatch Logs groups (created by scripts/setup_aws.py)
CHECKOUT_LOG_GROUP = os.getenv("CHECKOUT_LOG_GROUP", "/pilotlight/checkout")
CONFIG_AUDIT_LOG_GROUP = os.getenv("CONFIG_AUDIT_LOG_GROUP", "/pilotlight/config-audit")
TIMELINE_LOG_GROUP = os.getenv("TIMELINE_LOG_GROUP", "/pilotlight/timeline")
INCIDENTS_LOG_GROUP = os.getenv("INCIDENTS_LOG_GROUP", "/pilotlight/incidents")

# Local state (flag value, incident records), shared by every process on the demo laptop
STATE_DIR = os.getenv("STATE_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".state"))

# Alarm rule evaluated by services/incident/watcher.py
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

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
ONCALL_PHONE = os.getenv("ONCALL_PHONE", "")
PAGE_PHONE = os.getenv("PAGE_PHONE", "")

VOICE_SERVER_URL = os.getenv("VOICE_SERVER_URL", "").rstrip("/")

# Code-level check that the engineer said "confirm" before a remediation runs. Never disable in production.
REQUIRE_SPOKEN_CONFIRM = os.getenv("REQUIRE_SPOKEN_CONFIRM", "true").lower() != "false"

# Operator dashboard (dashboard/app.py)
DASHBOARD_USER = os.getenv("DASHBOARD_USER", "admin")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")  # no default: login is refused until set
DASHBOARD_SECRET = os.getenv("DASHBOARD_SECRET", "")
