"""
Black-Scholes greeks for Indian index/equity options (European-style).
Computes Theta (daily rupee decay) and Vega (per 1% IV move).
"""
import math


_RFR = 0.065   # India 10Y Gsec ≈ 6.5% risk-free rate


def _d1d2(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0, 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return d1, d1 - sigma * math.sqrt(T)


def _npdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def _ncdf(x):
    return (1.0 + math.erf(x / math.sqrt(2))) / 2.0


def compute_greeks(
    option_type: str,
    S: float,
    K: float,
    T_years: float,
    sigma: float,
    r: float = _RFR,
) -> dict:
    """
    option_type : "CE" or "PE"
    S           : spot price
    K           : strike
    T_years     : time to expiry in years  (e.g. 7/365 for weekly)
    sigma       : IV as decimal            (e.g. 0.18 for 18%)
    r           : risk-free rate

    Returns delta, gamma, theta (per day), vega (per 1% IV move).
    """
    T = T_years
    if T <= 0 or sigma <= 0:
        return {"delta": None, "gamma": None, "theta": None, "vega": None}

    d1, d2 = _d1d2(S, K, T, r, sigma)
    pdf_d1 = _npdf(d1)
    sqrt_T = math.sqrt(T)

    gamma          = pdf_d1 / (S * sigma * sqrt_T)
    vega_per_pct   = S * pdf_d1 * sqrt_T / 100   # rupee change per 1% IV move
    theta_common   = -(S * pdf_d1 * sigma) / (2 * sqrt_T)
    e_neg_rT       = math.exp(-r * T)

    if option_type.upper() == "CE":
        delta = _ncdf(d1)
        theta = (theta_common - r * K * e_neg_rT * _ncdf(d2)) / 365
    else:
        delta = _ncdf(d1) - 1
        theta = (theta_common + r * K * e_neg_rT * _ncdf(-d2)) / 365

    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta, 2),
        "vega":  round(vega_per_pct, 2),
    }


def implied_volatility(
    option_type: str,
    option_price: float,
    S: float,
    K: float,
    T_years: float,
    r: float = _RFR,
    tol: float = 0.01,
    max_iter: int = 100,
):
    """
    Solve for IV via bisection given observed option price.
    Returns IV as percentage (e.g. 18.5 for 18.5%) or None if unsolvable.
    """
    if T_years <= 0 or option_price <= 0 or S <= 0 or K <= 0:
        return None

    def _bs_price(sigma):
        d1, d2 = _d1d2(S, K, T_years, r, sigma)
        e_neg = math.exp(-r * T_years)
        if option_type.upper() == "CE":
            return S * _ncdf(d1) - K * e_neg * _ncdf(d2)
        return K * e_neg * _ncdf(-d2) - S * _ncdf(-d1)

    lo, hi = 0.001, 5.0
    if _bs_price(lo) > option_price or _bs_price(hi) < option_price:
        return None
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        diff = _bs_price(mid) - option_price
        if abs(diff) < tol:
            return round(mid * 100, 2)
        if diff < 0:
            lo = mid
        else:
            hi = mid
    return None


def days_to_expiry(expiry_str: str) -> int:
    """Parse '28APR2026' → calendar days from today."""
    from datetime import date, datetime
    today = date.today()
    for fmt in ("%d%b%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return max(0, (datetime.strptime(expiry_str.upper(), fmt.upper()).date() - today).days)
        except ValueError:
            continue
    return 0
