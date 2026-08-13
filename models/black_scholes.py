"""
Black-Scholes European option pricing + Greeks + implied volatility.

Deliberately the "regular" flat-volatility model, as requested -- no
smile/skew modeling. The intended use here isn't finding smile-driven
mispricing (that's what the Heston version was for); it's using ONE
reference volatility (e.g. India VIX, or the chain's own ATM implied
vol) to price every strike consistently, then flagging strikes whose
market premium deviates too far from that flat-vol fair value -- which
in practice tends to catch illiquid/wide-spread strikes or genuine
pricing anomalies, not smile effects (which are normal and expected,
not anomalies, under a flat-vol assumption).
"""

import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq
from dataclasses import dataclass


# ---------------------------------------------------------------------
# Core pricing
# ---------------------------------------------------------------------

def bs_price(S, K, r, T, sigma, option_type="call"):
    """S: spot, K: strike, r: risk-free rate (annualized, decimal),
    T: time to expiry in years, sigma: annualized volatility (decimal)."""
    if T <= 0 or sigma <= 0:
        # at/past expiry or degenerate vol -> intrinsic value
        if option_type == "call":
            return max(S - K, 0.0)
        else:
            return max(K - S, 0.0)

    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    if option_type == "call":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    elif option_type == "put":
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    else:
        raise ValueError("option_type must be 'call' or 'put'")


# ---------------------------------------------------------------------
# Greeks
# ---------------------------------------------------------------------

@dataclass
class Greeks:
    delta: float
    gamma: float
    theta: float   # per calendar day (not per year) -- more useful for short-term trading
    vega: float     # per 1 percentage-point (0.01) change in vol
    rho: float       # per 1 percentage-point (0.01) change in rate


def bs_greeks(S, K, r, T, sigma, option_type="call") -> Greeks:
    if T <= 0 or sigma <= 0:
        return Greeks(delta=0.0, gamma=0.0, theta=0.0, vega=0.0, rho=0.0)

    sqrtT = np.sqrt(T)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    pdf_d1 = norm.pdf(d1)

    gamma = pdf_d1 / (S * sigma * sqrtT)
    vega = S * pdf_d1 * sqrtT * 0.01  # scaled to 1% vol move

    if option_type == "call":
        delta = norm.cdf(d1)
        theta_annual = (-(S * pdf_d1 * sigma) / (2 * sqrtT) - r * K * np.exp(-r * T) * norm.cdf(d2))
        rho = K * T * np.exp(-r * T) * norm.cdf(d2) * 0.01
    else:
        delta = norm.cdf(d1) - 1
        theta_annual = (-(S * pdf_d1 * sigma) / (2 * sqrtT) + r * K * np.exp(-r * T) * norm.cdf(-d2))
        rho = -K * T * np.exp(-r * T) * norm.cdf(-d2) * 0.01

    theta_per_day = theta_annual / 365.0

    return Greeks(delta=delta, gamma=gamma, theta=theta_per_day, vega=vega, rho=rho)


# ---------------------------------------------------------------------
# Implied volatility (needed to derive a reference vol from market ATM
# price, e.g. if you don't want to just use India VIX directly)
# ---------------------------------------------------------------------

def implied_vol(market_price, S, K, r, T, option_type="call", bracket=(1e-4, 5.0)):
    """Solves for sigma such that bs_price(...) == market_price. Returns
    NaN if no solution exists in the bracket (e.g. price violates
    no-arbitrage bounds, which happens with bad/stale quotes)."""
    intrinsic = max(S - K, 0.0) if option_type == "call" else max(K - S, 0.0)
    if market_price < intrinsic - 1e-6:
        return float("nan")  # price below intrinsic value -- bad quote, not a vol problem

    def f(sigma):
        return bs_price(S, K, r, T, sigma, option_type) - market_price

    try:
        return brentq(f, bracket[0], bracket[1])
    except ValueError:
        return float("nan")


if __name__ == "__main__":
    # Sanity checks
    S, K, r, T, sigma = 24500, 24500, 0.065, 7 / 365, 0.13  # roughly Nifty-scale ATM weekly option

    price = bs_price(S, K, r, T, sigma, "call")
    greeks = bs_greeks(S, K, r, T, sigma, "call")
    recovered_iv = implied_vol(price, S, K, r, T, "call")

    print(f"ATM call price: {price:.2f}")
    print(f"Greeks: delta={greeks.delta:.3f}, gamma={greeks.gamma:.5f}, "
          f"theta={greeks.theta:.2f}/day, vega={greeks.vega:.2f}, rho={greeks.rho:.2f}")
    print(f"Implied vol recovered from price: {recovered_iv*100:.2f}% (should match input {sigma*100:.2f}%)")
    assert abs(recovered_iv - sigma) < 1e-6, "IV solver failed to recover known input vol"
    print("\nIV solver validated correctly.")

    # Put-call parity check: C - P = S - K*exp(-rT)
    call_p = bs_price(S, K, r, T, sigma, "call")
    put_p = bs_price(S, K, r, T, sigma, "put")
    parity_lhs = call_p - put_p
    parity_rhs = S - K * np.exp(-r * T)
    print(f"\nPut-call parity check: C-P={parity_lhs:.4f}, S-Ke^-rT={parity_rhs:.4f}, "
          f"diff={abs(parity_lhs-parity_rhs):.8f}")
    assert abs(parity_lhs - parity_rhs) < 1e-6, "Put-call parity violated -- pricing bug"
    print("Put-call parity holds.")
