import os
import json
import requests
from datetime import datetime, timedelta

DATA_FILE = "data/instrument_master.json"
URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"


class InstrumentMaster:
    def __init__(self):
        self.data = []
        self.last_updated = None

    # 🔹 Download or load cached file
    def load(self):
        if self._is_cache_valid():
            self._load_from_file()
        else:
            self._download()

        self._filter_nifty_options()

    # 🔹 Check if cache is valid (1 day)
    def _is_cache_valid(self):
        if not os.path.exists(DATA_FILE):
            return False

        file_time = datetime.fromtimestamp(os.path.getmtime(DATA_FILE))
        return datetime.now() - file_time < timedelta(days=1)

    # 🔹 Download fresh file
    def _download(self):
        print("⬇️ Downloading instrument master...")

        response = requests.get(URL)
        data = response.json()

        os.makedirs("data", exist_ok=True)

        with open(DATA_FILE, "w") as f:
            json.dump(data, f)

        self.data = data
        self.last_updated = datetime.now()

        print("✅ Download complete")

    # 🔹 Load from file
    def _load_from_file(self):
        print("📂 Loading cached instrument master...")

        with open(DATA_FILE, "r") as f:
            self.data = json.load(f)

    # 🔹 Filter NIFTY options only
    def _filter_nifty_options(self):
        self.data = [
            self._normalize(i)
            for i in self.data
            if i["name"] == "NIFTY"
            and i["instrumenttype"] == "OPTIDX"
            and i["exch_seg"] == "NFO"
        ]

        print(f"✅ NIFTY options loaded: {len(self.data)}")

    # 🔹 Normalize structure
    def _normalize(self, inst):
        return {
            "token": inst["token"],
            "symbol": inst["symbol"],
            "expiry": inst["expiry"],
            "strike": float(inst["strike"]) / 100,  # ⚠️ important
            "type": "CE" if inst["symbol"].endswith("CE") else "PE"
        }

    # 🔹 Get options by expiry
    def get_options_by_expiry(self, expiry):
        return [i for i in self.data if i["expiry"] == expiry]
    
    def get_atm_options(self, ltp):
        expiry = self.get_nearest_expiry()
        options = self.get_options_by_expiry(expiry)

        # Get all strikes
        strikes = sorted(set(o["strike"] for o in options))

        # Find closest strike
        atm_strike = min(strikes, key=lambda x: abs(x - ltp))

        # Get CE & PE
        ce = next(o for o in options if o["strike"] == atm_strike and o["type"] == "CE")
        pe = next(o for o in options if o["strike"] == atm_strike and o["type"] == "PE")

        return {
            "expiry": expiry,
            "atm_strike": atm_strike,
            "ce": ce,
            "pe": pe
        }
    
    def get_atm_tokens(self, smart):
        """
        Fetch live NIFTY LTP → find ATM → return CE & PE tokens
        """

        # 🔹 Ensure data is loaded
        if not self.data:
            self.load()

        # 🔹 Get NIFTY LTP
        from core.indicators.constants import SPOT_TOKEN
        ltp_data = smart.ltpData("NSE", "NIFTY", SPOT_TOKEN)

        if not ltp_data["status"]:
            raise Exception("Failed to fetch LTP")

        ltp = ltp_data["data"]["ltp"]
        print(f"📊 NIFTY LTP: {ltp}")

        # 🔹 Get ATM options
        atm = self.get_atm_options(ltp)

        ce_token = str(atm["ce"]["token"])
        pe_token = str(atm["pe"]["token"])

        print("🎯 ATM Selected:")
        print("CE:", atm["ce"]["symbol"], ce_token)
        print("PE:", atm["pe"]["symbol"], pe_token)

        return ce_token, pe_token
    
    def get_option_chain(self, ltp, range_size=5, expiry=None):
        """
        Returns option chain around ATM for the given expiry.
        Defaults to the nearest (current) expiry when expiry=None.
        """

        if not self.data:
            self.load()

        # 🔹 Round to nearest strike
        atm = round(ltp / 50) * 50

        nearest_expiry = expiry if expiry else self.get_nearest_expiry()

        chain = []

        for strike in range(atm - 50*range_size, atm + 50*(range_size+1), 50):

            ce = next((x for x in self.data 
                    if x["strike"] == strike 
                    and x["type"] == "CE"
                    and x["expiry"] == nearest_expiry), None)

            pe = next((x for x in self.data 
                    if x["strike"] == strike 
                    and x["type"] == "PE"
                    and x["expiry"] == nearest_expiry), None)

            if ce and pe:
                chain.append({
                    "strike": strike,
                    "ce": ce,
                    "pe": pe
                })

        print(f"📊 Option chain built: {len(chain)} strikes (expiry {nearest_expiry})")

        return chain
    def get_nifty_futures_token(self):
        """
        Return the token for the nearest NIFTY futures contract (FUTIDX on NFO).
        Reads from the raw cached JSON because self.data only keeps OPTIDX.
        Returns None if not found.
        """
        try:
            with open(DATA_FILE, "r") as f:
                raw = json.load(f)
            today = datetime.now().date()
            futures = [
                i for i in raw
                if i.get("name") == "NIFTY"
                and i.get("instrumenttype") == "FUTIDX"
                and i.get("exch_seg") == "NFO"
                and datetime.strptime(i["expiry"], "%d%b%Y").date() >= today
            ]
            if not futures:
                return None
            nearest = min(futures, key=lambda i: datetime.strptime(i["expiry"], "%d%b%Y"))
            return nearest["token"]
        except Exception:
            return None

    def get_nearest_expiry(self):
        """Return the nearest expiry that has not yet passed."""
        return self.get_upcoming_expiries(n=1)[0]

    def get_upcoming_expiries(self, n=4):
        """
        Return up to n upcoming expiry strings (DDMMMYYYY format, uppercase)
        sorted chronologically, filtering out dates strictly before today.
        On expiry day itself the expiry is kept until midnight.

        NOTE: must sort by parsed date, NOT by string — string sort puts
        "01MAY2026" before "24APR2026" which gives the wrong nearest expiry.
        """
        today = datetime.now().date()
        expiries = set(x["expiry"] for x in self.data)
        future = sorted(
            (exp for exp in expiries
             if datetime.strptime(exp, "%d%b%Y").date() >= today),
            key=lambda exp: datetime.strptime(exp, "%d%b%Y")   # chronological
        )
        return future[:n]