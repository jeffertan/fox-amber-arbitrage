from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

ACTION_FORCE_DISCHARGE = "force_discharge"
ACTION_FORCE_CHARGE = "force_charge"


@dataclass
class PriceSnapshot:
    buy_kwh: float
    sell_kwh: float
    spike_status: str
    timestamp: datetime


@dataclass
class InverterSnapshot:
    soc: float
    pv_kw: float
    grid_kw: float
    load_kw: float
    battery_kw: float
    battery_temp: float
    work_mode: str
    timestamp: datetime


@dataclass
class DecisionSnapshot:
    action: str
    reason: str
    avg_charge_cost: float
    timestamp: datetime


@dataclass
class HistoryPoint:
    timestamp: datetime
    buy_kwh: float
    sell_kwh: float


@dataclass
class TradeEvent:
    timestamp: datetime
    action: str       # "force_discharge" | "force_charge"
    price_kwh: float  # sell price (neg=income) for discharge; buy price for charge
    grid_kw: float    # grid power during event (positive=import, negative=export)
    duration_sec: float
    est_kwh: float    # abs energy transacted
    est_revenue: float  # positive=income, negative=cost

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "action": self.action,
            "price_kwh": self.price_kwh,
            "grid_kw": self.grid_kw,
            "duration_sec": self.duration_sec,
            "est_kwh": self.est_kwh,
            "est_revenue": self.est_revenue,
        }

    @staticmethod
    def from_dict(d: dict) -> TradeEvent:
        return TradeEvent(
            timestamp=datetime.fromisoformat(d["timestamp"]),
            action=d["action"],
            price_kwh=d["price_kwh"],
            grid_kw=d["grid_kw"],
            duration_sec=d["duration_sec"],
            est_kwh=d["est_kwh"],
            est_revenue=d["est_revenue"],
        )


_TRADES_PATH = Path("trades.json")
_TRADES_MAX_DAYS = 90


class StateStore:
    def __init__(self):
        self._lock = threading.Lock()
        self.prices: Optional[PriceSnapshot] = None
        self.inverter: Optional[InverterSnapshot] = None
        self.decision: Optional[DecisionSnapshot] = None
        self.history: list[HistoryPoint] = []
        self._max_history = 14 * 24 * 2  # 14 days × 30-min slots
        self._manual_override_until: Optional[datetime] = None
        self._manual_override_action: Optional[str] = None
        self.trades: list[TradeEvent] = []
        self._load_trades()

    def update_prices(self, buy: float, sell: float, spike: str) -> None:
        with self._lock:
            now = datetime.now()
            self.prices = PriceSnapshot(buy, sell, spike, now)
            self.history.append(HistoryPoint(now, buy, sell))
            if len(self.history) > self._max_history:
                self.history = self.history[-self._max_history:]

    def update_inverter(self, inv) -> None:
        with self._lock:
            self.inverter = InverterSnapshot(
                soc=inv.battery.soc,
                pv_kw=inv.pv_power_kw,
                grid_kw=inv.grid_power_kw,
                load_kw=inv.load_power_kw,
                battery_kw=inv.battery.power_kw,
                battery_temp=inv.battery.temperature,
                work_mode=inv.work_mode,
                timestamp=datetime.now(),
            )

    def update_decision(self, action: str, reason: str, avg_cost: float) -> None:
        with self._lock:
            self.decision = DecisionSnapshot(action, reason, avg_cost, datetime.now())

    def set_manual_override(self, action: str, minutes: int) -> None:
        with self._lock:
            self._manual_override_until = datetime.now() + timedelta(minutes=minutes)
            self._manual_override_action = action

    def clear_manual_override(self) -> None:
        with self._lock:
            self._manual_override_until = None
            self._manual_override_action = None

    def is_manual_override(self) -> bool:
        with self._lock:
            if self._manual_override_until is None:
                return False
            if datetime.now() >= self._manual_override_until:
                self._manual_override_until = None
                self._manual_override_action = None
                return False
            return True

    def override_info(self) -> dict:
        with self._lock:
            if self._manual_override_until is None or datetime.now() >= self._manual_override_until:
                return {"active": False}
            remaining = (self._manual_override_until - datetime.now()).seconds // 60
            return {
                "active": True,
                "action": self._manual_override_action,
                "until": self._manual_override_until.isoformat(),
                "remaining_minutes": remaining,
            }

    def record_trade(self, action: str, price_kwh: float, grid_kw: float, duration_sec: float) -> None:
        if duration_sec < 30 or abs(grid_kw) < 0.05:
            return  # ignore noise / self_use events
        est_kwh = abs(grid_kw) * duration_sec / 3600
        est_revenue = est_kwh * (-price_kwh)
        event = TradeEvent(
            timestamp=datetime.now(),
            action=action,
            price_kwh=price_kwh,
            grid_kw=grid_kw,
            duration_sec=duration_sec,
            est_kwh=est_kwh,
            est_revenue=est_revenue,
        )
        with self._lock:
            self.trades.append(event)
            cutoff = datetime.now() - timedelta(days=_TRADES_MAX_DAYS)
            self.trades = [t for t in self.trades if t.timestamp >= cutoff]
            data = [t.to_dict() for t in self.trades]
        try:
            _TRADES_PATH.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def get_recent_trades(self, limit: int = 20) -> list[TradeEvent]:
        with self._lock:
            return list(reversed(self.trades[-limit:]))

    def get_daily_analytics(self, days: int = 30) -> list[dict]:
        cutoff = datetime.now() - timedelta(days=days)
        with self._lock:
            recent = [t for t in self.trades if t.timestamp >= cutoff]
        by_date: dict[str, dict] = {}
        for t in recent:
            date_str = t.timestamp.strftime("%Y-%m-%d")
            if date_str not in by_date:
                by_date[date_str] = {
                    "date": date_str,
                    "charge_kwh": 0.0,
                    "charge_cost": 0.0,
                    "discharge_kwh": 0.0,
                    "discharge_revenue": 0.0,
                    "net_profit": 0.0,
                }
            d = by_date[date_str]
            if t.action == ACTION_FORCE_DISCHARGE:
                d["discharge_kwh"] += t.est_kwh
                d["discharge_revenue"] += t.est_revenue
            elif t.action == ACTION_FORCE_CHARGE:
                d["charge_kwh"] += t.est_kwh
                d["charge_cost"] += -t.est_revenue  # positive cost
            d["net_profit"] = d["discharge_revenue"] - d["charge_cost"]
        return sorted(by_date.values(), key=lambda x: x["date"])

    def _load_trades(self) -> None:
        try:
            data = json.loads(_TRADES_PATH.read_text())
            self.trades = [TradeEvent.from_dict(d) for d in data]
        except (FileNotFoundError, Exception):
            pass

    def load_history_from_log(self, log_path: str) -> None:
        """Pre-populate price history from monitor.log on startup."""
        import re
        from datetime import timedelta as td
        pattern = re.compile(
            r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*Buy: \$([0-9.\-]+)/kWh \| (?:卖出收入|Sell): \$([0-9.\-]+)/kWh"
        )
        try:
            cutoff = datetime.now() - td(days=14)
            seen: set = set()
            points: list[HistoryPoint] = []
            with open(log_path) as f:
                for line in f:
                    m = pattern.search(line)
                    if not m:
                        continue
                    ts_str = m.group(1)
                    if ts_str in seen:
                        continue
                    seen.add(ts_str)
                    dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                    if dt < cutoff:
                        continue
                    buy = float(m.group(2))
                    sell = -abs(float(m.group(3)))  # restore feedIn sign convention
                    points.append(HistoryPoint(dt, buy, sell))
            with self._lock:
                self.history = points[-self._max_history:]
        except FileNotFoundError:
            pass
        except Exception:
            pass

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "prices": self.prices,
                "inverter": self.inverter,
                "decision": self.decision,
                "history": list(self.history),
            }
