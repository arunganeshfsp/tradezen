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

# Validate
if not all([API_KEY, CLIENT_ID, PIN, TOTP_SECRET]):
    raise ValueError("❌ Missing one or more environment variables")

