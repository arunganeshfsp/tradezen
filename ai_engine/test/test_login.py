from SmartApi import SmartConnect
import pyotp
from config.credentials import API_KEY, CLIENT_ID, PIN, TOTP_SECRET


def login():
    try:
        # Initialize SmartAPI
        smart = SmartConnect(api_key=API_KEY)

        # Generate TOTP
        totp = pyotp.TOTP(TOTP_SECRET).now()

        print("🔐 Generated OTP:", totp)

        # Create session
        data = smart.generateSession(CLIENT_ID, PIN, totp)

        # Check response
        if not data or not data.get("status"):
            print("❌ Login failed")
            print("Response:", data)
            return None

        # Extract tokens
        auth_token = data["data"]["jwtToken"]
        refresh_token = data["data"]["refreshToken"]
        feed_token = smart.getfeedToken()

        print("✅ Login Success")
        print("Auth Token:", auth_token[:20], "...")
        print("Feed Token:", feed_token[:20], "...")

        return smart, auth_token, feed_token

    except Exception as e:
        print("❌ Exception during login:", str(e))
        return None


if __name__ == "__main__":
    login()