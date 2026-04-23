from test.test_login import login


def test_ltp():
    result = login()
    if not result:
        print("❌ Login failed. Cannot fetch LTP.")
        return

    smart, _, _ = result

    try:
        # NIFTY index token
        response = smart.ltpData("NSE", "NIFTY", "26000")

        print("📊 LTP Response:")
        print(response)

    except Exception as e:
        print("❌ Error fetching LTP:", str(e))


if __name__ == "__main__":
    test_ltp()