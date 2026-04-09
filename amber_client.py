"""
Amber Electric API client.
Docs: https://app.amber.com.au/developers/
"""

import requests
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

log = logging.getLogger(__name__)

AMBER_BASE = "https://api.amber.com.au/v1"


@dataclass
class PricePoint:
    channel: str          # "general" (buy) or "feedIn" (sell)
    price_kwh: float      # AUD/kWh (already divided by 100)
    spike_status: str     # "none" | "potential" | "spike" | "extremelyHigh"
    descriptor: str       # "extremelyLow" | "low" | "neutral" | "high" | "spike" | "extremelyHigh"
    start_time: datetime
    end_time: datetime
    is_forecast: bool

    @property
    def is_spike(self) -> bool:
        return self.spike_status in ("spike", "extremelyHigh")

    @property
    def is_negative(self) -> bool:
        return self.price_kwh < 0


@dataclass
class CurrentPrices:
    buy: PricePoint
    sell: PricePoint

    def summary(self) -> str:
        spike_tag = " [SPIKE]" if self.sell.is_spike else ""
        neg_tag = " [NEGATIVE]" if self.buy.is_negative else ""
        return (
            f"Buy: ${self.buy.price_kwh:.4f}/kWh{neg_tag} | "
            f"Sell: ${self.sell.price_kwh:.4f}/kWh{spike_tag}"
        )


class AmberClient:
    def __init__(self, api_key: str, site_id: Optional[str] = None):
        if not api_key:
            raise ValueError("AMBER_API_KEY is not set")
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self._site_id = site_id

    @property
    def site_id(self) -> str:
        if not self._site_id:
            self._site_id = self._fetch_site_id()
        return self._site_id

    def _fetch_site_id(self) -> str:
        log.info("Fetching Amber site ID...")
        r = requests.get(f"{AMBER_BASE}/sites", headers=self.headers, timeout=10)
        r.raise_for_status()
        sites = r.json()
        if not sites:
            raise RuntimeError("No Amber sites found for this account")
        site = sites[0]
        log.info(f"Using site: {site['id']} ({site.get('nmi', 'unknown NMI')})")
        return site["id"]

    def _parse_price_point(self, item: dict) -> PricePoint:
        return PricePoint(
            channel=item["channelType"],
            price_kwh=item["perKwh"] / 100.0,
            spike_status=item.get("spikeStatus", "none"),
            descriptor=item.get("descriptor", ""),
            start_time=datetime.fromisoformat(item["startTime"].replace("Z", "+00:00")),
            end_time=datetime.fromisoformat(item["endTime"].replace("Z", "+00:00")),
            is_forecast=item.get("type", "ActualInterval") == "ForecastInterval",
        )

    def get_current_prices(self) -> CurrentPrices:
        """Fetch current real-time buy and sell prices."""
        r = requests.get(
            f"{AMBER_BASE}/sites/{self.site_id}/prices/current",
            headers=self.headers,
            params={"next": 1, "previous": 0},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()

        buy = sell = None
        for item in data:
            pp = self._parse_price_point(item)
            if item["channelType"] == "general":
                buy = pp
            elif item["channelType"] == "feedIn":
                sell = pp

        if buy is None or sell is None:
            raise RuntimeError(f"Missing price channels in response: {data}")

        return CurrentPrices(buy=buy, sell=sell)

    def get_forecast(self, hours: int = 4) -> list[PricePoint]:
        """Fetch price forecast for the next N hours (30-min intervals)."""
        slots = hours * 2
        r = requests.get(
            f"{AMBER_BASE}/sites/{self.site_id}/prices/current",
            headers=self.headers,
            params={"next": slots, "previous": 0},
            timeout=10,
        )
        r.raise_for_status()
        return [
            self._parse_price_point(item)
            for item in r.json()
            if item["channelType"] == "feedIn"
        ]

    def get_highest_forecast_price(self, hours: int = 4) -> float:
        """Return the highest forecast feed-in price in the next N hours."""
        forecasts = self.get_forecast(hours)
        if not forecasts:
            return 0.0
        return max(p.price_kwh for p in forecasts)
