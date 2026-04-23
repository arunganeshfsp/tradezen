from config.credentials import TOTP_SECRET
import pyotp

def test_totp():
    totp = pyotp.TOTP(TOTP_SECRET)
    otp = totp.now()

    print("Generated OTP:", otp)
    print("👉 Check if this matches your authenticator app")

if __name__ == "__main__":
    test_totp()