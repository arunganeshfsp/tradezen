from data.instrument_master import InstrumentMaster

def test_atm():
    im = InstrumentMaster()
    im.load()

    # Use your LTP from earlier
    ltp = 23842.65

    atm = im.get_atm_options(ltp)

    print("\n🎯 ATM RESULT")
    print("Expiry:", atm["expiry"])
    print("ATM Strike:", atm["atm_strike"])
    print("CE:", atm["ce"])
    print("PE:", atm["pe"])

if __name__ == "__main__":
    test_atm()