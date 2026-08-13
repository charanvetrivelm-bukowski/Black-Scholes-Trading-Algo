"""
Volatility model: derives a reference implied volatility from a live
option chain, for use as the single flat vol the screener prices every
strike against.

Expects the option chain in Dhan's documented shape:
    option_chain = {
        "data": {
            "expiry": "2026-08-07",         # or similar, verify exact key/format against live response
            "last_price": 24500.0,          # underlying spot, if present
            "oc": {
                "24500.000000": {
                    "ce": {"last_price": 191.5, "implied_volatility": ..., ...},
                    "pe": {"last_price": 160.2, ...},
                },
                ...
            }
        }
    }

NOTE: the exact field names/nesting should be verified against a real
sandbox response (see the option chain endpoint you test in the API
Playground) -- this is built from Dhan's documented structure but adjust
the key names below if the live response differs.
"""

import numpy as np
from models.black_scholes import implied_vol
from utils.logger import get_logger

logger = get_logger(__name__)


class VolatilityModel:
    def __init__(self):
        self.reference_iv = None

    def calculate_reference_iv(self, option_chain, spot, risk_free_rate, time_to_expiry, atm_band_pct=3.0):
        """Average implied vol of near-ATM strikes (both calls and puts)."""
        ivs = []
        lower, upper = spot * (1 - atm_band_pct / 100), spot * (1 + atm_band_pct / 100)
        # confirmed from a real response: get_option_chain() already strips
        # Dhan's SDK envelope, so the chain here is directly {"last_price":
        # ..., "oc": {...}} -- no further "data" nesting
        option_data = option_chain.get("oc", {})

        for strike_str, contracts in option_data.items():
            strike = float(strike_str)
            if strike < lower or strike > upper:
                continue
            for opt_key, opt_type in (("ce", "call"), ("pe", "put")):
                if opt_key in contracts and contracts[opt_key].get("last_price"):
                    iv = implied_vol(contracts[opt_key]["last_price"], spot, strike, risk_free_rate, time_to_expiry, opt_type)
                    if not np.isnan(iv):
                        ivs.append(iv)

        if not ivs:
            sample_keys = list(option_data.keys())[:3]
            sample_entry = option_data.get(sample_keys[0]) if sample_keys else None
            logger.warning(
                f"No near-ATM strikes yielded a valid implied vol -- reference_iv unset. "
                f"Diagnostic info: option_data has {len(option_data)} strikes total. "
                f"ATM band was [{lower:.1f}, {upper:.1f}] (spot={spot}, atm_band_pct={atm_band_pct}). "
                f"Sample strike keys: {sample_keys}. "
                f"Sample entry for '{sample_keys[0] if sample_keys else None}': {sample_entry!r}"
            )
            self.reference_iv = None
            return None

        self.reference_iv = float(np.mean(ivs))
        return self.reference_iv

    def get_reference_iv(self):
        return self.reference_iv


if __name__ == "__main__":
    # Sanity check against a synthetic chain shaped like Dhan's response
    from models.black_scholes import bs_price

    S, r, T = 24500, 0.065, 7 / 365
    true_iv = 0.13
    strikes = [24200, 24300, 24400, 24500, 24600, 24700, 24800]
    oc = {}
    for K in strikes:
        oc[str(float(K))] = {
            "ce": {"last_price": round(bs_price(S, K, r, T, true_iv, "call"), 2)},
            "pe": {"last_price": round(bs_price(S, K, r, T, true_iv, "put"), 2)},
        }
    chain = {"last_price": S, "oc": oc}

    vm = VolatilityModel()
    ref_iv = vm.calculate_reference_iv(chain, S, r, T)
    print(f"Reference IV recovered: {ref_iv*100:.2f}% (should be close to {true_iv*100:.2f}%)")
    assert abs(ref_iv - true_iv) < 0.005, "Reference IV calculation is off"
    print("Volatility model validated correctly.")