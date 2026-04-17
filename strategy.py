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
        night_reserve = b["night_reserve_soc"]      # 25%
        night_target = b["night_target_soc"]         # 30%
        sell_threshold = t["sell_threshold"]          # $0.10

        if buy > 0:
            self._update_avg_charge_cost(buy)

        solar_tag = f" | solar={pv_kw:.2f}kW" if pv_kw > 0.05 else ""

        if self._is_night(now, sched):
            return self._decide_night(
                sell, buy, soc, pv_kw, solar_tag,
                sell_threshold, night_reserve, night_target, discharge_kw, t, b,
            )
        else:
            return self._decide_day(
                sell, buy, soc, pv_kw, solar_tag, now, sched,
                sell_threshold, night_reserve, discharge_kw, t, b,
            )

    # ── Phase handlers ────────────────────────────────────────────────────────

    def _decide_day(
        self, sell, buy, soc, pv_kw, solar_tag, now, sched,
        sell_threshold, night_reserve, discharge_kw, t, b,
    ) -> Decision:
        charge_kw = b["max_charge_kw"]

        # 1. Negative price: charge from grid — only before max_grid_charge_hour
        if (
            buy <= t["negative_price"]
            and now.hour < sched["max_grid_charge_hour"]
            and soc < b["max_soc"]
        ):
            return Decision(
                action=ACTION_FORCE_CHARGE,
                reason=f"Negative price ${buy:.4f}/kWh before {sched['max_grid_charge_hour']}:00{solar_tag}",
                sell_price=sell, buy_price=buy, soc=soc, pv_kw=pv_kw,
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
        sell_threshold, night_reserve, night_target, discharge_kw, t, b,
    ) -> Decision:
        cheap_buy = t["night_cheap_buy"]

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

        # 3. Cheap top-up to ensure morning reserve
        if buy <= cheap_buy and soc < night_target:
            return Decision(
                action=ACTION_FORCE_CHARGE,
                reason=f"Night cheap charge ${buy:.4f}/kWh → target {night_target}%{solar_tag}",
                sell_price=sell, buy_price=buy, soc=soc, pv_kw=pv_kw,
            )

        # 4. Default
        return Decision(
            action=ACTION_SELF_USE,
            reason=f"Night hold — SOC {soc:.0f}%{solar_tag}",
            sell_price=sell, buy_price=buy, soc=soc, pv_kw=pv_kw,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

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
