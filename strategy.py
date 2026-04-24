"""
Arbitrage decision engine — time-phase aware.

Two phases per day:

  DAY (day_start – night_start, default 07:00–23:00)
  ────────────────────────────────────────────────────
  1. Negative buy price + before max_grid_charge_hour + SOC < 95%
       → Force Charge  (grid paying us; stop before solar peak to leave room)
  2. Extreme sell (≥ $1.00) + SOC > night_reserve
       → Force Discharge  (no exceptions)
  3. sell ≥ sell_threshold ($0.10) + SOC > night_reserve + profitable
       → Force Discharge
  4. Default → Self Use  (solar → home → battery; no grid draw forced)

  NIGHT (night_start – day_start, default 23:00–07:00)
  ──────────────────────────────────────────────────────
  1. SOC ≤ night_reserve_soc (25%)
       → Self Use  (protect floor; grid covers home load)
  2. sell ≥ sell_threshold + SOC > night_reserve + 5% buffer
       → Force Discharge  (fdSoc = night_reserve)
  3. buy ≤ night_cheap_buy + SOC < night_target_soc
       → Force Charge  (cheap top-up to reach morning reserve)
  4. Default → Self Use
"""

from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional
import logging

from amber_client import CurrentPrices
from fox_client import InverterStatus
from solar_forecast import SolarForecast

log = logging.getLogger(__name__)

ACTION_FORCE_DISCHARGE = "force_discharge"
ACTION_FORCE_CHARGE = "force_charge"
ACTION_SELF_USE = "self_use"

# Sell price above which we always discharge regardless of profit guard
EXTREME_SPIKE = 1.00


@dataclass
class Decision:
    action: str
    reason: str
    sell_price: float
    buy_price: float
    soc: float
    pv_kw: float = 0.0
    discharge_power_kw: Optional[float] = None
    charge_target_soc: Optional[int] = None

    def __str__(self):
        return (
            f"[{self.action.upper()}] {self.reason}"
            f" (SOC={self.soc:.0f}%, solar={self.pv_kw:.2f}kW,"
            f" sell=${self.sell_price:.4f}, buy=${self.buy_price:.4f})"
        )


class ArbitrageStrategy:
    def __init__(self, config: dict):
        self.cfg = config
        self._avg_charge_cost: float = 0.10
        self._charge_cost_samples: list[float] = []

    def decide(
        self,
        prices: CurrentPrices,
        inverter: InverterStatus,
        solar: Optional[SolarForecast] = None,
    ) -> Decision:
        t = self.cfg["thresholds"]
        b = self.cfg["battery"]
        sched = self.cfg["schedule"]
        sys_cfg = self.cfg["system"]

        sell = prices.sell.price_kwh
        buy = prices.buy.price_kwh
        soc = inverter.battery.soc
        pv_kw = inverter.pv_power_kw
        now = datetime.now()

        discharge_kw = min(b["max_discharge_kw"], sys_cfg["max_export_kw"])
        night_reserve = b["night_reserve_soc"]           # 25%
        day_reserve = b.get("day_discharge_reserve_soc", 45)  # 45%
        sell_threshold = t["sell_threshold"]              # $0.10

        solar_tag = f" | solar={pv_kw:.2f}kW" if pv_kw > 0.05 else ""

        if self._is_night(now, sched):
            decision = self._decide_night(
                sell, buy, soc, pv_kw, solar_tag,
                sell_threshold, night_reserve, discharge_kw, t, b, solar,
            )
        else:
            decision = self._decide_day(
                sell, buy, soc, pv_kw, solar_tag, now, sched,
                sell_threshold, day_reserve, discharge_kw, t, b, solar,
            )

        if decision.action == ACTION_FORCE_CHARGE and buy > 0:
            self._update_avg_charge_cost(buy)

        return decision

    # ── Phase handlers ────────────────────────────────────────────────────────

    def _decide_day(
        self, sell, buy, soc, pv_kw, solar_tag, now, sched,
        sell_threshold, night_reserve, discharge_kw, t, b,
        solar: Optional[SolarForecast] = None,
    ) -> Decision:

        aggressive_soc = b.get("aggressive_charge_soc", 80)  # below this, always charge on negative price
        charge_to_soc = b.get("aggressive_charge_target", 90)   # target when charging aggressively

        # 1. Negative price: charge from grid — only before max_grid_charge_hour
        if (
            buy <= t["negative_price"]
            and now.hour < sched["max_grid_charge_hour"]
            and soc < b["max_soc"]
        ):
            # SOC below threshold: always charge aggressively regardless of solar
            if soc < aggressive_soc:
                return Decision(
                    action=ACTION_FORCE_CHARGE,
                    reason=f"Negative price ${buy:.4f}/kWh, SOC={soc:.0f}% < {aggressive_soc}% — full charge to {charge_to_soc}%{solar_tag}",
                    sell_price=sell, buy_price=buy, soc=soc, pv_kw=pv_kw,
                    charge_target_soc=charge_to_soc,
                )
            # SOC >= threshold: skip if solar will fill the battery
            if self._solar_will_saturate(soc, pv_kw, sched, b):
                return Decision(
                    action=ACTION_SELF_USE,
                    reason=f"Solar will saturate battery (SOC={soc:.0f}%, PV={pv_kw:.2f}kW) — skip negative-price charge",
                    sell_price=sell, buy_price=buy, soc=soc, pv_kw=pv_kw,
                )
            target = self._charge_target_soc(solar, b)
            return Decision(
                action=ACTION_FORCE_CHARGE,
                reason=f"Negative price ${buy:.4f}/kWh before {sched['max_grid_charge_hour']}:00, target SOC={target}%{solar_tag}",
                sell_price=sell, buy_price=buy, soc=soc, pv_kw=pv_kw,
                charge_target_soc=target,
            )

        # 1b. Cheap daytime price — charge unless battery is nearly full and solar will top it off
        day_cheap = t.get("day_cheap_buy", 0.05)
        solar_will_fill = soc >= aggressive_soc and self._solar_will_saturate(soc, pv_kw, sched, b)
        if (
            buy <= day_cheap
            and now.hour < sched["max_grid_charge_hour"]
            and soc < b["max_soc"]
            and not solar_will_fill
        ):
            return Decision(
                action=ACTION_FORCE_CHARGE,
                reason=f"Cheap daytime price ${buy:.4f}/kWh ≤ ${day_cheap}, target SOC={charge_to_soc}%{solar_tag}",
                sell_price=sell, buy_price=buy, soc=soc, pv_kw=pv_kw,
                charge_target_soc=charge_to_soc,
            )

        # 2. Extreme spike — discharge regardless of profit guard
        # feedIn is negative when receiving money; <= -1.00 means receiving >= $1/kWh
        if sell <= -EXTREME_SPIKE and soc > night_reserve:
            return Decision(
                action=ACTION_FORCE_DISCHARGE,
                reason=f"Extreme spike receiving ${-sell:.4f}/kWh{solar_tag}",
                sell_price=sell, buy_price=buy, soc=soc, pv_kw=pv_kw,
                discharge_power_kw=discharge_kw,
            )

        # 3. Profitable sell opportunity
        # sell <= -threshold means receiving >= threshold per kWh
        if sell <= -sell_threshold and soc > night_reserve:
            if not self._is_profitable(sell, t):
                return Decision(
                    action=ACTION_SELF_USE,
                    reason=(
                        f"receive=${-sell:.4f} < cost ${self._avg_charge_cost:.4f}"
                        f" + margin{solar_tag}"
                    ),
                    sell_price=sell, buy_price=buy, soc=soc, pv_kw=pv_kw,
                )
            return Decision(
                action=ACTION_FORCE_DISCHARGE,
                reason=f"receive=${-sell:.4f} ≥ threshold ${sell_threshold}{solar_tag}",
                sell_price=sell, buy_price=buy, soc=soc, pv_kw=pv_kw,
                discharge_power_kw=discharge_kw,
            )

        # 4. Default — let solar + inverter self-optimise
        return Decision(
            action=ACTION_SELF_USE,
            reason=f"receive=${-sell:.4f} < threshold ${sell_threshold}{solar_tag}",
            sell_price=sell, buy_price=buy, soc=soc, pv_kw=pv_kw,
        )

    def _decide_night(
        self, sell, buy, soc, pv_kw, solar_tag,
        sell_threshold, night_reserve, discharge_kw, t, b,
        solar: Optional[SolarForecast] = None,
    ) -> Decision:
        cheap_buy = t["night_cheap_buy"]
        # Dynamic night target: charge more if tomorrow is cloudy, less if sunny
        night_target = self._dynamic_night_target(solar, b)

        # 1. Below floor — stop all discharge, let grid cover home
        if soc <= night_reserve:
            return Decision(
                action=ACTION_SELF_USE,
                reason=f"SOC {soc:.0f}% ≤ night reserve {night_reserve}% — protecting floor{solar_tag}",
                sell_price=sell, buy_price=buy, soc=soc, pv_kw=pv_kw,
            )

        # 2. Sell opportunity — discharge down to night_reserve floor
        if sell <= -sell_threshold and soc > night_reserve + 5:
            if self._is_profitable(sell, t):
                return Decision(
                    action=ACTION_FORCE_DISCHARGE,
                    reason=f"Night sell receiving ${-sell:.4f}/kWh, SOC {soc:.0f}%{solar_tag}",
                    sell_price=sell, buy_price=buy, soc=soc, pv_kw=pv_kw,
                    discharge_power_kw=discharge_kw,
                )

        # 3. Cheap top-up — target adjusted for tomorrow's solar forecast
        if buy <= cheap_buy and soc < night_target:
            solar_hint = f" (cloudy tomorrow)" if solar and solar.is_cloudy else (
                         f" (sunny tomorrow)" if solar and solar.is_sunny else "")
            return Decision(
                action=ACTION_FORCE_CHARGE,
                reason=f"Night cheap charge ${buy:.4f}/kWh → target {night_target}%{solar_hint}{solar_tag}",
                sell_price=sell, buy_price=buy, soc=soc, pv_kw=pv_kw,
            )

        # 4. Default
        return Decision(
            action=ACTION_SELF_USE,
            reason=f"Night hold — SOC {soc:.0f}%{solar_tag}",
            sell_price=sell, buy_price=buy, soc=soc, pv_kw=pv_kw,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _solar_will_saturate(self, soc: float, pv_kw: float, sched: dict, b: dict) -> bool:
        """Return True if remaining solar output today will likely fill the battery."""
        if pv_kw < 0.5:
            return False  # not generating meaningfully
        capacity_kwh = b.get("capacity_kwh", 37.7)
        max_soc = b.get("max_soc", 95)
        remaining_kwh = (max_soc - soc) / 100 * capacity_kwh

        now = datetime.now()
        sunset_hour = sched.get("sunset_hour", 19)
        hours_left = max(0.0, sunset_hour - now.hour - now.minute / 60)
        estimated_kwh = pv_kw * hours_left * 0.7  # 0.7 = efficiency/self-consumption factor

        threshold = b.get("solar_saturation_threshold", 0.8)
        return estimated_kwh >= remaining_kwh * threshold

    def _charge_target_soc(self, solar: Optional[SolarForecast], b: dict) -> int:
        """Adjust grid-charge target SOC based on tomorrow's solar forecast."""
        base = b.get("max_soc", 95)
        if solar is None:
            return base
        if solar.is_sunny:
            return max(50, base - 20)   # sunny tomorrow: don't overfill, solar will top up
        if solar.is_cloudy:
            return base                  # cloudy: charge fully, solar won't help much
        return base - 10                 # partly cloudy: middle ground

    def _dynamic_night_target(self, solar: Optional[SolarForecast], b: dict) -> int:
        """Night charge target SOC adjusted for tomorrow's solar generation forecast."""
        base = b["night_target_soc"]  # default 30%
        if solar is None:
            return base
        # Tomorrow sunny (>20 kWh): solar will fill battery — stay conservative
        if solar.estimated_kwh > 20:
            return base
        # Tomorrow cloudy (<10 kWh): charge more now as solar won't compensate
        if solar.estimated_kwh < 10:
            return min(80, base + 20)
        # Partly cloudy: modest top-up
        return min(60, base + 10)

    def _is_night(self, now: datetime, sched: dict) -> bool:
        night_start = time.fromisoformat(sched["night_start"])
        day_start = time.fromisoformat(sched["day_start"])
        t = now.time()
        return t >= night_start or t < day_start

    def _is_profitable(self, sell_price: float, t: dict) -> bool:
        margin = t.get("min_profit_margin", 0.05)
        # sell_price is negative (feedIn convention); -sell_price = amount received
        return -sell_price >= self._avg_charge_cost + margin

    def _update_avg_charge_cost(self, buy_price: float, window: int = 20) -> None:
        self._charge_cost_samples.append(buy_price)
        if len(self._charge_cost_samples) > window:
            self._charge_cost_samples.pop(0)
        self._avg_charge_cost = sum(self._charge_cost_samples) / len(self._charge_cost_samples)
