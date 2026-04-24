"""
Parse monitor.log to derive historical price and load patterns.

Outputs:
  PriceStats   — 7-day buy/sell price percentiles + hourly profile
  LoadStats    — hourly average home load + "high load" hours
  Insights     — actionable summary used by strategy and dashboard
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from collections import defaultdict
import statistics

log = logging.getLogger(__name__)

# Matches lines like:
#   2026-04-19 11:29:53,783 INFO 逆变器: SOC=63% solar=2.68kW grid=+8.56kW load=3.98kW
_INV_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*"
    r"逆变器: SOC=(\d+(?:\.\d+)?)%"
    r" solar=([\d.]+)kW"
    r" grid=([+-]?[\d.]+)kW"
    r" load=([\d.]+)kW"
)

# Matches lines like:
#   2026-04-19 11:29:53,334 INFO 买入: $0.0317/kWh | ...
_PRICE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*"
    r"买入: \$([\d.\-]+)/kWh.*"
    r"(?:卖出收入|出口成本): \$([\d.\-]+)/kWh"
)


@dataclass
class PriceStats:
    buy_p10: float = 0.0   # 10th percentile — "very cheap"
    buy_p25: float = 0.0   # 25th percentile — "cheap"
    buy_p50: float = 0.0   # median
    buy_p75: float = 0.0   # 75th percentile — "expensive"
    sell_p75: float = 0.0  # 75th percentile sell income — "good spike"
    sell_p90: float = 0.0  # 90th percentile — "great spike"
    # hourly median buy price, index = hour (0..23)
    hourly_buy: list[float] = field(default_factory=lambda: [0.0] * 24)
    n_samples: int = 0

    def suggested_buy_threshold(self) -> float:
        """Price below which charging is considered cheap."""
        return round(max(0.02, self.buy_p25), 3)

    def suggested_sell_threshold(self) -> float:
        """Price above which discharging is profitable."""
        return round(max(0.08, self.sell_p75), 3)

    def cheap_hours(self) -> list[int]:
        """Hours when buy prices are historically low."""
        t = self.suggested_buy_threshold()
        return [h for h, p in enumerate(self.hourly_buy) if 0 < p <= t]

    def expensive_hours(self) -> list[int]:
        """Hours when sell prices are historically high — good discharge windows."""
        return [h for h, p in enumerate(self.hourly_buy) if p >= self.buy_p75]


@dataclass
class LoadStats:
    hourly_avg: list[float] = field(default_factory=lambda: [0.0] * 24)
    peak_load: float = 0.0
    avg_load: float = 0.0
    n_samples: int = 0

    def high_load_hours(self, multiplier: float = 1.3) -> list[int]:
        """Hours where load is significantly above average."""
        threshold = self.avg_load * multiplier
        return [h for h, v in enumerate(self.hourly_avg) if v >= threshold]

    def min_soc_for_hour(self, hour: int, hours_ahead: int = 3, battery_kwh: float = 37.7) -> int:
        """Minimum SOC to keep to cover next `hours_ahead` hours of load."""
        future_load = sum(
            self.hourly_avg[(hour + i) % 24] for i in range(hours_ahead)
        )
        pct = future_load / battery_kwh * 100
        return min(80, max(20, int(pct) + 5))


@dataclass
class Insights:
    price: PriceStats
    load: LoadStats
    generated_at: datetime = field(default_factory=datetime.now)

    def summary(self) -> str:
        lines = [
            f"价格分析 ({self.price.n_samples} 样本):",
            f"  买入 P10/P25/P50: ${self.price.buy_p10:.3f}/${self.price.buy_p25:.3f}/${self.price.buy_p50:.3f}",
            f"  建议买入阈值: ${self.price.suggested_buy_threshold():.3f}/kWh",
            f"  建议卖出阈值: ${self.price.suggested_sell_threshold():.3f}/kWh",
            f"  低价时段: {self.price.cheap_hours()}",
            f"负载分析 ({self.load.n_samples} 样本):",
            f"  平均负载: {self.load.avg_load:.2f}kW, 峰值: {self.load.peak_load:.2f}kW",
            f"  高负载时段: {self.load.high_load_hours()}",
        ]
        return "\n".join(lines)


def analyse(log_path: str = "monitor.log", days: int = 7) -> Optional[Insights]:
    cutoff = datetime.now() - timedelta(days=days)
    path = Path(log_path)
    if not path.exists():
        return None

    # Per-hour buckets
    buy_by_hour: list[list[float]] = [[] for _ in range(24)]
    sell_by_hour: list[list[float]] = [[] for _ in range(24)]
    load_by_hour: list[list[float]] = [[] for _ in range(24)]
    all_buys: list[float] = []
    all_sells: list[float] = []
    seen_ts: set[str] = set()

    try:
        with open(log_path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                # Price data
                m = _PRICE_RE.search(line)
                if m:
                    ts_str = m.group(1)
                    if ts_str in seen_ts:
                        continue
                    try:
                        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        continue
                    if dt < cutoff:
                        continue
                    seen_ts.add(ts_str)
                    buy = float(m.group(2))
                    sell = float(m.group(3))
                    h = dt.hour
                    buy_by_hour[h].append(buy)
                    sell_by_hour[h].append(sell)
                    if buy > 0:
                        all_buys.append(buy)
                    if sell > 0:
                        all_sells.append(sell)

                # Load data
                m2 = _INV_RE.search(line)
                if m2:
                    ts_str = m2.group(1)
                    try:
                        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        continue
                    if dt < cutoff:
                        continue
                    load = float(m2.group(5))
                    load_by_hour[dt.hour].append(load)

    except Exception as e:
        log.warning(f"Log analysis failed: {e}")
        return None

    if len(all_buys) < 10:
        return None  # not enough data

    def pct(data: list[float], p: float) -> float:
        if not data:
            return 0.0
        idx = int(len(data) * p / 100)
        return sorted(data)[min(idx, len(data) - 1)]

    price = PriceStats(
        buy_p10=round(pct(all_buys, 10), 4),
        buy_p25=round(pct(all_buys, 25), 4),
        buy_p50=round(pct(all_buys, 50), 4),
        buy_p75=round(pct(all_buys, 75), 4),
        sell_p75=round(pct(all_sells, 75), 4),
        sell_p90=round(pct(all_sells, 90), 4),
        hourly_buy=[
            round(statistics.median(v), 4) if v else 0.0
            for v in buy_by_hour
        ],
        n_samples=len(all_buys),
    )

    all_loads = [v for h in load_by_hour for v in h]
    load = LoadStats(
        hourly_avg=[
            round(statistics.mean(v), 3) if v else 0.0
            for v in load_by_hour
        ],
        peak_load=round(max(all_loads), 2) if all_loads else 0.0,
        avg_load=round(statistics.mean(all_loads), 3) if all_loads else 0.0,
        n_samples=len(all_loads),
    )

    return Insights(price=price, load=load)
