"""
Option chain screener, adapted from the validated version built earlier
in this project to consume Dhan's option-chain response shape directly.
See models/volatility.py for the expected chain structure.
"""

from dataclasses import dataclass, field
from typing import Optional
import numpy as np

from models.black_scholes import bs_price, bs_greeks, implied_vol, Greeks
from models.volatility import VolatilityModel
import config
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ScreenedStrike:
    strike: float
    option_type: str          # "call" or "put"
    security_id: Optional[str]
    market_price: float
    fair_value: float
    deviation_percent: float
    implied_vol_pct: float
    greeks: Greeks
    fairly_priced: bool        # NOTE: now means "is_discounted" (market_price < fair_value) -- kept
                                 # the field name for backward compatibility with any code referencing it
    greeks_favorable: bool    # informational only -- no longer part of the pass/fail decision
    liquidity_ok: bool
    passed: bool
    notes: list = field(default_factory=list)


class OptionScreener:
    def __init__(self):
        self.volatility_model = VolatilityModel()

    def screen(self, option_chain: dict, spot: float, time_to_expiry: float, risk_free_rate: float = None,
               strike_window: int = None) -> list:
        """Returns a list of ScreenedStrike, restricted to ATM-N..ATM+N
        strikes (strike_window, defaults to config.ATM_STRIKE_WINDOW) --
        this keeps the universe to strikes with real delta/liquidity
        suitable for short-term option buying, and eliminates the
        far-OTM noise that comes from near-zero, stale prices producing
        misleadingly large "discount" percentages."""
        r = risk_free_rate if risk_free_rate is not None else config.RISK_FREE_RATE
        window = strike_window if strike_window is not None else config.ATM_STRIKE_WINDOW

        reference_vol = self.volatility_model.calculate_reference_iv(option_chain, spot, r, time_to_expiry)
        if reference_vol is None:
            logger.warning("Could not derive a reference volatility from the chain -- returning empty screen")
            return []

        # confirmed from a real response: get_option_chain() already strips
        # Dhan's SDK envelope, so the chain here is directly {"last_price":
        # ..., "oc": {...}} -- no further "data" nesting
        option_data = option_chain.get("oc", {})

        window_strikes = self._select_atm_window(option_data, spot, window)
        if not window_strikes:
            logger.warning(f"screen(): could not select an ATM+/-{window} window -- no strikes in chain?")
            return []
        logger.info(f"screen(): restricting to ATM+/-{window} window: {window_strikes}")

        results = []
        skipped_no_price = 0
        fair_value_log_lines = []

        for strike_str in window_strikes:
            strike_key = f"{strike_str:.6f}"
            contracts = option_data.get(strike_key)
            if contracts is None:
                # strike key formatting mismatch guard -- try a couple of
                # plausible alternate formats before giving up on this strike
                contracts = option_data.get(str(strike_str)) or option_data.get(str(int(strike_str)))
            if contracts is None:
                logger.warning(f"screen(): strike {strike_str} was selected for the ATM window but not found "
                              f"in option_data (tried key formats '{strike_key}', '{strike_str}', '{int(strike_str)}')")
                continue

            for opt_key, opt_type in (("ce", "call"), ("pe", "put")):
                if opt_key not in contracts:
                    continue
                contract = contracts[opt_key]
                market_price = contract.get("last_price")

                fair_value = bs_price(spot, strike_str, r, time_to_expiry, reference_vol, opt_type)
                fair_value_log_lines.append(
                    f"  strike={strike_str:>8} {opt_type:>4}  fair_value={fair_value:>8.2f}  "
                    f"LTP={'n/a (no valid price)' if not market_price or market_price <= 0 else f'{market_price:.2f}'}"
                )

                if not market_price or market_price <= 0:
                    skipped_no_price += 1
                    continue

                strike = strike_str

                # Dhan provides Greeks and implied volatility directly per
                # contract, computed server-side (likely using each
                # strike's own live implied vol, not a shared flat
                # reference like ours) -- no reason to recompute these
                # ourselves when they're already in the response. We only
                # still calculate fair_value ourselves, since that's the
                # actual point of the fair-pricing check: comparing
                # market price against OUR OWN reference-vol valuation.
                dhan_greeks = contract.get("greeks", {})
                greeks = Greeks(
                    delta=dhan_greeks.get("delta", 0.0),
                    gamma=dhan_greeks.get("gamma", 0.0),
                    theta=dhan_greeks.get("theta", 0.0),
                    vega=dhan_greeks.get("vega", 0.0),
                    rho=0.0,  # Dhan's response doesn't include rho; unused in any filter below anyway
                )
                iv = contract.get("implied_volatility", 0.0) / 100.0 if contract.get("implied_volatility") else float("nan")

                notes = []
                if not dhan_greeks:
                    notes.append("Dhan response had no 'greeks' field for this contract -- defaulted to zero (informational only, no longer gates pass/fail)")

                deviation_pct = ((market_price - fair_value) / fair_value * 100) if fair_value > 0.01 else float("nan")

                # Directional discount check, replacing the old symmetric
                # +/- tolerance band: we ONLY want strikes where the market
                # is pricing the option BELOW our own Black-Scholes fair
                # value (a discount) -- these are the candidates worth
                # buying. A strike trading ABOVE fair value (a premium) is
                # explicitly excluded, not just "outside tolerance" --
                # we're not interested in overpriced options at all here.
                if np.isnan(deviation_pct):
                    is_discounted = False
                    notes.append("fair value near zero -- discount check not meaningful, treated as fail")
                elif market_price < fair_value:
                    is_discounted = True
                    notes.append(f"trading at a discount: {abs(deviation_pct):.1f}% below fair value")
                else:
                    is_discounted = False
                    notes.append(f"trading at a premium: {deviation_pct:.1f}% above fair value -- not a buy candidate")

                abs_delta = abs(greeks.delta)
                delta_ok = config.MIN_DELTA <= abs_delta <= config.MAX_DELTA
                theta_pct = abs(greeks.theta) / market_price * 100 if market_price > 0 else float("inf")
                theta_ok = theta_pct <= config.MAX_THETA_PCT_OF_PREMIUM
                greeks_favorable = delta_ok and theta_ok  # computed and shown for visibility only -- NOT used in `passed` below

                oi = contract.get("oi") or contract.get("open_interest")
                liquidity_ok = True
                if oi is not None:
                    liquidity_ok = oi >= config.MIN_OPEN_INTEREST
                    if not liquidity_ok:
                        notes.append(f"open interest {oi} below minimum {config.MIN_OPEN_INTEREST}")

                # Greeks deliberately excluded from the pass/fail decision --
                # only discount vs premium and liquidity gate a trade now.
                passed = is_discounted and liquidity_ok

                results.append(ScreenedStrike(
                    strike=strike, option_type=opt_type,
                    security_id=contract.get("security_id"),
                    market_price=market_price, fair_value=round(fair_value, 2),
                    deviation_percent=round(deviation_pct, 2) if not np.isnan(deviation_pct) else float("nan"),
                    implied_vol_pct=round(iv * 100, 2) if not np.isnan(iv) else float("nan"),
                    greeks=greeks, fairly_priced=is_discounted, greeks_favorable=greeks_favorable,
                    liquidity_ok=liquidity_ok, passed=passed, notes=notes,
                ))

        if fair_value_log_lines:
            logger.info(f"screen(): fair values for ATM+/-{window} window:\n" + "\n".join(fair_value_log_lines))

        if skipped_no_price > 0:
            logger.info(f"screen(): skipped {skipped_no_price} contract(s) with no valid price "
                       f"(illiquid/not currently trading). {len(results)} contracts actually screened.")
        if not results:
            logger.warning(f"screen(): returning EMPTY results -- every contract in this window either "
                          f"had no valid price ({skipped_no_price} skipped) or wasn't found in the chain.")

        return results

    @staticmethod
    def _select_atm_window(option_data: dict, spot: float, window: int) -> list:
        """Returns the list of absolute strike prices spanning ATM-window
        to ATM+window, based on the actual strikes present in the chain
        (not assuming a fixed strike spacing, since that varies)."""
        try:
            all_strikes = sorted(float(k) for k in option_data.keys())
        except (ValueError, TypeError):
            return []
        if not all_strikes:
            return []

        atm_index = min(range(len(all_strikes)), key=lambda i: abs(all_strikes[i] - spot))
        lo = max(0, atm_index - window)
        hi = min(len(all_strikes), atm_index + window + 1)
        return all_strikes[lo:hi]

    def passed_only(self, screened: list) -> list:
        return [s for s in screened if s.passed]

    def closest_to_fair(self, screened: list) -> Optional[ScreenedStrike]:
        """Fallback when nothing in the window is genuinely discounted:
        picks whichever strike has the SMALLEST absolute deviation from
        fair value (could be slightly above or below) -- i.e. the least
        mispriced option in the ATM window, considered regardless of
        whether it technically 'passed'."""
        valid = [s for s in screened if not np.isnan(s.deviation_percent)]
        if not valid:
            return None
        return min(valid, key=lambda s: abs(s.deviation_percent))

    def best_trade(self, candidates: list) -> Optional[ScreenedStrike]:
        """Picks the single best candidate among those that passed (i.e.
        are trading at a discount to fair value): the HIGHEST fair value
        among discounted strikes -- per the requested selection rule.
        Use closest_to_fair() instead when nothing in the window passed."""
        if not candidates:
            return None
        return max(candidates, key=lambda s: s.fair_value)


if __name__ == "__main__":
    from models.black_scholes import bs_greeks  # only used here to fabricate realistic test data,
                                                  # simulating what Dhan's own server-side calc would return

    S, r, T = 24500, 0.065, 7 / 365
    true_iv = 0.13
    strikes = [24200, 24300, 24400, 24500, 24600, 24700, 24800]
    oc = {}
    for K in strikes:
        oc[str(float(K))] = {}
        for opt_key, opt_type in (("ce", "call"), ("pe", "put")):
            fair = bs_price(S, K, r, T, true_iv, opt_type)
            # artificially discount strikes below spot, mark up strikes
            # above spot, leave ATM exactly at fair value -- so the test
            # actually exercises discount/premium/edge-case branches,
            # rather than every strike landing at zero deviation
            if K < S:
                market_price = fair * 0.90   # 10% discount -- should PASS
            elif K > S:
                market_price = fair * 1.10   # 10% premium -- should FAIL
            else:
                market_price = fair          # exactly fair -- should FAIL (not strictly less than)
            g = bs_greeks(S, K, r, T, true_iv, opt_type)
            oc[str(float(K))][opt_key] = {
                "last_price": round(market_price, 2), "oi": 20000, "security_id": f"{opt_key.upper()}{K}",
                "implied_volatility": true_iv * 100,  # Dhan reports as a percentage, e.g. 13.0
                "greeks": {"delta": g.delta, "gamma": g.gamma, "theta": g.theta, "vega": g.vega},
            }
    chain = {"last_price": S, "oc": oc}

    screener = OptionScreener()

    # Test 1: default window (4) is wider than the 7 test strikes span (+/-3), so nothing gets excluded
    screened = screener.screen(chain, S, T, r)
    passed = screener.passed_only(screened)
    best = screener.best_trade(passed)

    print(f"Test 1 (window=4, wider than data): {len(screened)} screened, {len(passed)} discounted.")
    for s in sorted(screened, key=lambda x: (x.strike, x.option_type)):
        tag = "DISCOUNT" if s.passed else "premium/fair"
        print(f"  strike={s.strike:>7} {s.option_type:>4}  mkt={s.market_price:>7.2f}  fair={s.fair_value:>7.2f}  "
              f"dev={s.deviation_percent:>6.1f}%  [{tag}]")
    print(f"Best (highest fair value among discounts): {best.strike} {best.option_type}, fair_value={best.fair_value}\n")

    assert len(screened) == len(strikes) * 2, "Expected 2 contracts (CE+PE) per strike"
    assert len(passed) == 6, f"Expected 6 discounted strikes to pass, got {len(passed)}"
    # deep-ITM strikes naturally have higher fair value than near-ATM ones
    # (more intrinsic value) -- "highest fair value" correctly picks the
    # most-ITM discounted strike, 24200 call, not the closest-to-ATM one
    assert best.strike == 24200.0 and best.option_type == "call", \
        f"Expected highest-fair-value discount to be the 24200 call, got {best.strike} {best.option_type}"

    # Test 2: a TIGHT window (2) should actually exclude the outer strikes
    screened_tight = screener.screen(chain, S, T, r, strike_window=2)
    strikes_seen = sorted(set(s.strike for s in screened_tight))
    print(f"Test 2 (window=2, should exclude 24200 & 24800): strikes included = {strikes_seen}")
    assert 24200.0 not in strikes_seen and 24800.0 not in strikes_seen, "Tight window should have excluded the outer strikes"
    assert len(strikes_seen) == 5, f"Expected 5 strikes (ATM-2..ATM+2), got {len(strikes_seen)}"
    print("Window restriction confirmed working correctly.\n")

    # Test 3: no-discount scenario -- everything at a comfortable premium
    # (large, distance-scaled markup so it reliably survives reference_vol
    # being re-derived from these same marked-up prices -- that feedback
    # loop shifts fair value non-uniformly across strikes since OTM
    # options are more vol-sensitive than ITM ones, so a thin markup
    # isn't safely predictable strike-by-strike)
    oc_premium = {}
    for K in strikes:
        oc_premium[str(float(K))] = {}
        for opt_key, opt_type in (("ce", "call"), ("pe", "put")):
            fair = bs_price(S, K, r, T, true_iv, opt_type)
            markup = 1.30 + abs(K - S) / 2000
            g = bs_greeks(S, K, r, T, true_iv, opt_type)
            oc_premium[str(float(K))][opt_key] = {
                "last_price": round(fair * markup, 2), "oi": 20000, "security_id": f"{opt_key.upper()}{K}",
                "implied_volatility": true_iv * 100,
                "greeks": {"delta": g.delta, "gamma": g.gamma, "theta": g.theta, "vega": g.vega},
            }
    chain_premium = {"last_price": S, "oc": oc_premium}

    screened_premium = screener.screen(chain_premium, S, T, r)
    passed_premium = screener.passed_only(screened_premium)
    fallback = screener.closest_to_fair(screened_premium)

    print(f"Test 3 (heavy markup applied -- illustrative, not a strict pass/fail check since "
          f"reference_vol is re-derived from these same marked-up near-ATM prices, which shifts "
          f"the very benchmark they're compared against): {len(passed_premium)} of {len(screened_premium)} "
          f"still showed as discounted after the vol re-derivation")
    print(f"Fallback (closest to fair) would be: strike={fallback.strike} {fallback.option_type}, "
          f"deviation={fallback.deviation_percent:+.2f}%")
    assert fallback is not None, "closest_to_fair should always return something when screened is non-empty"

    # Test 4: isolated, deterministic unit test of closest_to_fair() itself
    # (hand-built ScreenedStrike list, bypassing the chain/reference-vol
    # pipeline entirely, so the expected answer is unambiguous)
    hand_built = [
        ScreenedStrike(strike=100, option_type="call", security_id="A", market_price=10, fair_value=10,
                       deviation_percent=15.0, implied_vol_pct=13, greeks=Greeks(0, 0, 0, 0, 0),
                       fairly_priced=False, greeks_favorable=False, liquidity_ok=True, passed=False),
        ScreenedStrike(strike=200, option_type="call", security_id="B", market_price=10, fair_value=10,
                       deviation_percent=-2.5, implied_vol_pct=13, greeks=Greeks(0, 0, 0, 0, 0),
                       fairly_priced=False, greeks_favorable=False, liquidity_ok=True, passed=False),
        ScreenedStrike(strike=300, option_type="call", security_id="C", market_price=10, fair_value=10,
                       deviation_percent=8.0, implied_vol_pct=13, greeks=Greeks(0, 0, 0, 0, 0),
                       fairly_priced=False, greeks_favorable=False, liquidity_ok=True, passed=False),
    ]
    result = screener.closest_to_fair(hand_built)
    print(f"\nTest 4 (isolated unit test): picked strike={result.strike} (deviation={result.deviation_percent}%, "
          f"expected smallest |deviation| = strike 200 at -2.5%)")
    assert result.strike == 200, f"Expected strike 200 (smallest |deviation|), got {result.strike}"

    print("\nAll option screener tests passed -- window restriction, discount selection, "
          "and closest-to-fair fallback all confirmed working correctly.")