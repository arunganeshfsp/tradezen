from dotenv import load_dotenv
import os
from SmartApi import SmartConnect
import pyotp

# Load .env from ai_engine root
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
load_dotenv(env_path)

# Read variables
API_KEY = os.getenv("API_KEY")
CLIENT_ID = os.getenv("CLIENT_ID")
PIN = os.getenv("PIN")
TOTP_SECRET = os.getenv("TOTP_SECRET")

def get_smart_api():
    smart = SmartConnect(api_key=API_KEY)

    otp = pyotp.TOTP(TOTP_SECRET).now()
    session = smart.generateSession(CLIENT_ID, PIN, otp)

    if not session["status"]:
        raise Exception("Login failed")

    smart.generateToken(session["data"]["refreshToken"])

    return smart


# Live-order credentials (separate funded account).
# LIVE_API_KEY is optional — falls back to API_KEY if not set.
# If LIVE_CLIENT_ID is not set, get_live_smart_api() raises so the caller
# can detect "not configured" and fall back to the data session.
LIVE_API_KEY    = os.getenv("LIVE_API_KEY") or API_KEY
LIVE_CLIENT_ID  = os.getenv("LIVE_CLIENT_ID")
LIVE_PIN        = os.getenv("LIVE_PIN")
LIVE_TOTP_SECRET = os.getenv("LIVE_TOTP_SECRET")


def get_live_smart_api():
    """Return a SmartAPI session for the live-order account (LIVE_* env vars).
    Raises RuntimeError if LIVE_CLIENT_ID / LIVE_PIN / LIVE_TOTP_SECRET are not set."""
    if not all([LIVE_CLIENT_ID, LIVE_PIN, LIVE_TOTP_SECRET]):
        raise RuntimeError(
            "LIVE_* credentials not configured — set LIVE_CLIENT_ID, LIVE_PIN, "
            "LIVE_TOTP_SECRET (and optionally LIVE_API_KEY) in .env"
        )
    smart = SmartConnect(api_key=LIVE_API_KEY)
    otp = pyotp.TOTP(LIVE_TOTP_SECRET).now()
    session = smart.generateSession(LIVE_CLIENT_ID, LIVE_PIN, otp)
    if not session["status"]:
        raise Exception("Live login failed")
    smart.generateToken(session["data"]["refreshToken"])
    return smart


# Validate data-account credentials (hard fail at startup if missing)
if not all([API_KEY, CLIENT_ID, PIN, TOTP_SECRET]):
    raise ValueError("❌ Missing one or more environment variables")

