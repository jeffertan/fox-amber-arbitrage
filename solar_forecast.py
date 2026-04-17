"""
Open-Meteo solar forecast client (free, no API key required).
Estimates tomorrow's solar generation to inform overnight charging decisions.
"""

import logging
import time
import requests
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

log = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
CACHE_TTL_SEC = 3600  # Re-fetch at most once per hour


@dataclass
class SolarForecast:
    for_date: date
    estimated_kwh: float    # Predicted solar generation (kWh)
    cloud_cover_pct: float  # Average daytime cloud cover (%)
    ghi_kwh_m2: float       # Global horizontal irradiance (kWh/m²)

    @property
    def is_sunny(self) -> bool:
        return self.cloud_cover_pct < 30

    @property
    def is_cloudy(self) -> bool:
        return self.cloud_cover_pct > 65

    def summary(self) -> str:
        if self.is_sunny:
            icon = "☀️ 晴天"
        elif self.is_cloudy:
            icon = "☁️ 阴天"
        else:
            icon = "⛅ 多云"
        return (
            f"{icon} | 预测发电 {self.estimated_kwh:.1f} kWh"
            f" | 云量 {self.cloud_cover_pct:.0f}%"
            f" | GHI {self.ghi_kwh_m2:.2f} kWh/m²"
        )


class SolarForecastClient:
    """
    Fetches tomorrow's solar irradiance from Open-Meteo and converts it to
    an estimated kWh generation figure for the configured solar system.

    Conversion:
      GHI (kWh/m²) / clear_sky_ghi → capacity ratio → × peak_daily_kwh
    """

    def __init__(self, config: dict):
        cfg = config["solar"]
        self.lat = cfg["latitude"]
        self.lon = cfg["longitude"]
        self.peak_daily_kwh = cfg["peak_daily_kwh"]
        self.clear_sky_ghi = cfg.get("clear_sky_ghi_kwh_m2", 5.5)
        self._cache: Optional[SolarForecast] = None
        self._cache_ts: float = 0.0

    def get_tomorrow(self) -> SolarForecast:
        if self._cache and (time.monotonic() - self._cache_ts) < CACHE_TTL_SEC:
            return self._cache
        forecast = self._fetch()
        self._cache = forecast
        self._cache_ts = time.monotonic()
        return forecast

    def _fetch(self) -> SolarForecast:
        log.info("Fetching solar forecast from Open-Meteo...")
        try:
            r = requests.get(
                OPEN_METEO_URL,
                params={
                    "latitude": self.lat,
                    "longitude": self.lon,
                    "hourly": "shortwave_radiation,cloud_cover",
                    "forecast_days": 2,
                    "timezone": "auto",
                },
                timeout=10,
            )
            r.raise_for_status()
        except Exception as e:
            log.warning(f"Solar forecast fetch failed: {e} — using neutral default")
            return self._neutral_default()

        data = r.json()
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        radiation = hourly.get("shortwave_radiation", [])
        cloud = hourly.get("cloud_cover", [])

        tomorrow = date.today() + timedelta(days=1)
        tomorrow_str = tomorrow.isoformat()

        daytime_radiation, daytime_cloud = [], []
        for i, t in enumerate(times):
            if not t.startswith(tomorrow_str):
                continue
            hour = int(t[11:13])
            if 6 <= hour <= 20:  # daylight window
                daytime_radiation.append(radiation[i] or 0.0)
                daytime_cloud.append(cloud[i] or 0.0)

        if not daytime_radiation:
            log.warning("No tomorrow solar data in response — using neutral default")
            return self._neutral_default()

        # Each hourly reading (W/m²) represents 1 hour → sum = Wh/m² → /1000 = kWh/m²
        ghi_kwh_m2 = sum(daytime_radiation) / 1000.0
        avg_cloud = sum(daytime_cloud) / len(daytime_cloud)
        ratio = min(ghi_kwh_m2 / self.clear_sky_ghi, 1.0)
        estimated_kwh = round(ratio * self.peak_daily_kwh, 1)

        forecast = SolarForecast(
            for_date=tomorrow,
            estimated_kwh=estimated_kwh,
            cloud_cover_pct=round(avg_cloud, 1),
            ghi_kwh_m2=round(ghi_kwh_m2, 2),
        )
        log.info(f"Solar forecast {tomorrow}: {forecast.summary()}")
        return forecast

    def _neutral_default(self) -> SolarForecast:
        """Return a 50% generation assumption when fetch fails, to avoid bad decisions."""
        return SolarForecast(
            for_date=date.today() + timedelta(days=1),
            estimated_kwh=self.peak_daily_kwh * 0.5,
            cloud_cover_pct=50.0,
            ghi_kwh_m2=self.clear_sky_ghi * 0.5,
        )
