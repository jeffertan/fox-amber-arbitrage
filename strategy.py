"""
Arbitrage decision engine.

Decision priority (highest → lowest):
  1. Negative buy price       → Force charge (grid paying us to consume)
  2. Extreme spike (>$1.00)   → Force discharge, ignore demand window
  3. Spike / high sell price  → Force discharge (if SOC allows + demand window OK)
  4. Low buy price            → Force charge from grid
  5. Scheduled discharge window + price OK → Force discharge
  6. Scheduled charge window  → Force charge (from solar, supplemented by grid if cheap)
  7. Default                  → Self Use
"""

from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional
import logging

from amber_client import CurrentPrices

log = logging.getLogger(__name__)

# Actions returned by the strategy
ACTION_FORCE_DISCHARGE = "force_discharge"
ACTION_FORCE_CHARGE = "force_charge"
ACTION_SELF_USE = "self_use"


@dataclass
class Decision:
    action: str
    reason: str
    sell_price: float
    buy_price: float
    soc: float
    discharge_power_kw: Optional[float] = None
    charge_power_kw: Optional[float] = None
    target_soc: Optional[int] = None

    def __str__(self):
        return f"[{self.action.upper()}] {self.reason} (SOC={self.soc:.0f}%, sell=${self.sell_price:.4f}, buy=${self.buy_price:.4f})"


class ArbitrageStrategy:
    def __init__(self, config: dict):
        self.cfg = config
        self._avg_charge_cost: float = 0.10  # Running average cost of energy in battery
        self._charge_cost_samples: list[float] = []

    def decide(self, prices: CurrentPrices, soc: float, forecast_prices: list = None) -> Decision:
        t = self.cfg["thresholds"]
        b = self.cfg["battery"]
        sys = self.cfg["system"]

        sell = prices.sell.price_kwh
        buy = prices.buy.price_kwh
        is_spike = prices.sell.is_spike
        now = datetime.now()

        discharge_kw = min(b["max_discharge_kw"], sys["max_export_kw"])
        charge_kw = b["max_charge_kw"]

        # Track charge cost for profit guard
        if buy > 0:
            self._update_avg_charge_cost(buy)

        # ── 1. Negative buy price: grid paying us to consume ─────────────────
        if buy <= t["negative_price"] and soc < b["max_soc"]:
            return Decision(
                action=ACTION_FORCE_CHARGE,
                reason=f"Negative price ${buy:.4f}/kWh — charging from grid",
                sell_price=sell, buy_price=buy, soc=soc,
                charge_power_kw=charge_kw,
                target_soc=b["max_soc"],
            )

        # ── 2. Extreme spike: override all protections ────────────────────────
        if sell >= t["sell_extreme"] and soc > b["min_soc"]:
            return Decision(
                action=ACTION_FORCE_DISCHARGE,
                reason=f"Extreme spike ${sell:.4f}/kWh — full discharge",
                sell_price=sell, buy_price=buy, soc=soc,
                discharge_power_kw=discharge_kw,
            )

        # ── 3. Spike / high sell price ─────────────────────────────────────────
        if (is_spike or sell >= t["sell_high"]) and soc > b["min_soc"]:
            if self._in_demand_window(now) and sell < t.get("override_price", 1.00):
                return Decision(
                    action=ACTION_SELF_USE,
                    reason=f"Spike ${sell:.4f}/kWh but in demand window — holding",
                    sell_price=sell, buy_price=buy, soc=soc,
                )
            if not self._is_profitable(sell):
                return Decision(
                    action=ACTION_SELF_USE,
                    reason=f"Sell ${sell:.4f} < avg charge cost ${self._avg_charge_cost:.4f} + margin",
                    sell_price=sell, buy_price=buy, soc=soc,
                )
            return Decision(
                action=ACTION_FORCE_DISCHARGE,
                reason=f"High sell price ${sell:.4f}/kWh (spike={is_spike})",
                sell_price=sell, buy_price=buy, soc=soc,
                discharge_power_kw=discharge_kw,
            )

        # ── 4. Good sell price (above sell_min) ───────────────────────────────
        if sell >= t["sell_min"] and soc > b["min_soc"]:
            if self._in_demand_window(now):
                log.debug("Price OK but in demand window — holding")
                return Decision(
                    action=ACTION_SELF_USE,
                    reason=f"Sell ${sell:.4f}/kWh OK but demand window active",
                    sell_price=sell, buy_price=buy, soc=soc,
                )
            if not self._is_profitable(sell):
                return Decision(
                    action=ACTION_SELF_USE,
                    reason=f"Sell ${sell:.4f} not profitable vs charge cost ${self._avg_charge_cost:.4f}",
                    sell_price=sell, buy_price=buy, soc=soc,
                )
            return Decision(
                action=ACTION_FORCE_DISCHARGE,
                reason=f"Sell price ${sell:.4f}/kWh above threshold",
                sell_price=sell, buy_price=buy, soc=soc,
                discharge_power_kw=discharge_kw,
            )

        # ── 5. Cheap grid power: charge from grid ─────────────────────────────
        if buy <= t["buy_max"] and soc < b["max_soc"]:
            return Decision(
                action=ACTION_FORCE_CHARGE,
                reason=f"Cheap grid ${buy:.4f}/kWh — charging",
                sell_price=sell, buy_price=buy, soc=soc,
                charge_power_kw=charge_kw,
                target_soc=b["max_soc"],
            )

        # ── 6. Scheduled force charge window (solar top-up) ───────────────────
        sched_charge = self.cfg["schedule"]["force_charge"]
        if (
            sched_charge["enabled"]
            and self._in_time_window(now, sched_charge["start"], sched_charge["end"])
            and soc < sched_charge["target_soc"]
        ):
            return Decision(
                action=ACTION_FORCE_CHARGE,
                reason=f"Scheduled charge window — targeting SOC {sched_charge['target_soc']}%",
                sell_price=sell, buy_price=buy, soc=soc,
                charge_power_kw=charge_kw,
                target_soc=sched_charge["target_soc"],
            )

        # ── 7. Scheduled discharge window ─────────────────────────────────────
        sched_dis = self.cfg["schedule"]["force_discharge"]
        if (
            sched_dis["enabled"]
            and self._in_time_window(now, sched_dis["start"], sched_dis["end"])
            and soc >= sched_dis["min_soc_start"]
            and sell > 0.15  # Only discharge if we get something for it
        ):
            return Decision(
                action=ACTION_FORCE_DISCHARGE,
                reason=f"Scheduled discharge window, sell=${sell:.4f}/kWh",
                sell_price=sell, buy_price=buy, soc=soc,
                discharge_power_kw=discharge_kw,
            )

        # ── Default: Self Use ─────────────────────────────────────────────────
        return Decision(
            action=ACTION_SELF_USE,
            reason="No arbitrage opportunity — self use mode",
            sell_price=sell, buy_price=buy, soc=soc,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_profitable(self, sell_price: float) -> bool:
        margin = self.cfg["thresholds"].get("min_profit_margin", 0.05)
        return sell_price >= (self._avg_charge_cost + margin)

    def _update_avg_charge_cost(self, buy_price: float, window: int = 20) -> None:
        """Rolling average of recent buy prices (proxy for battery charge cost)."""
        self._charge_cost_samples.append(buy_price)
        if len(self._charge_cost_samples) > window:
            self._charge_cost_samples.pop(0)
        self._avg_charge_cost = sum(self._charge_cost_samples) / len(self._charge_cost_samples)

    def _in_time_window(self, now: datetime, start_str: str, end_str: str) -> bool:
        start = time.fromisoformat(start_str)
        end = time.fromisoformat(end_str)
        return start <= now.time() <= end

    def _in_demand_window(self, now: datetime) -> bool:
        dw = self.cfg.get("demand_window", {})
        if not dw.get("enabled"):
            return False
        month = now.month
        peak_months = dw.get("summer_months", []) + dw.get("winter_months", [])
        if month not in peak_months:
            return False
        return self._in_time_window(now, dw["peak_start"], dw["peak_end"])
