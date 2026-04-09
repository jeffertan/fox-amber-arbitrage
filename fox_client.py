"""
FOX ESS Open API client.
API docs: https://www.foxesscloud.com/public/i18n/en/OpenApiDocument.html

Authentication: HMAC-MD5 signature
  signature = md5("<path>\r\n<token>\r\n<timestamp>")
"""

import hashlib
import time
import logging
import requests
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

FOX_BASE = "https://www.foxesscloud.com/op/v0"

# Work modes supported by FOX inverters
MODE_SELF_USE = "SelfUse"
MODE_FEED_IN = "Feedin"
MODE_BACKUP = "Backup"
MODE_FORCE_CHARGE = "ForceCharge"
MODE_FORCE_DISCHARGE = "ForceDischarge"


@dataclass
class BatteryStatus:
    soc: float            # State of charge (%)
    power_kw: float       # Positive = charging, negative = discharging
    temperature: float    # Celsius
    voltage: float        # Volts


@dataclass
class InverterStatus:
    work_mode: str
    pv_power_kw: float      # Solar generation
    grid_power_kw: float    # Positive = import, negative = export
    load_power_kw: float    # Home consumption
    battery: BatteryStatus


class FoxClient:
    def __init__(self, api_key: str, device_sn: str):
        if not api_key:
            raise ValueError("FOX_API_KEY is not set")
        if not device_sn:
            raise ValueError("FOX_DEVICE_SN is not set")
        self.api_key = api_key
        self.device_sn = device_sn
        self._last_mode: Optional[str] = None

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _sign(self, path: str) -> dict:
        """Generate FOX API authentication headers."""
        timestamp = str(round(time.time() * 1000))
        raw = f"{path}\r\n{self.api_key}\r\n{timestamp}"
        signature = hashlib.md5(raw.encode()).hexdigest()
        return {
            "token": self.api_key,
            "timestamp": timestamp,
            "signature": signature,
            "lang": "en",
            "Content-Type": "application/json",
        }

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{FOX_BASE}{path}"
        r = requests.post(url, headers=self._sign(path), json=payload, timeout=15)
        r.raise_for_status()
        body = r.json()
        if body.get("errno", 0) != 0:
            raise RuntimeError(f"FOX API error on {path}: {body}")
        return body.get("result", {})

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{FOX_BASE}{path}"
        r = requests.get(url, headers=self._sign(path), params=params or {}, timeout=15)
        r.raise_for_status()
        body = r.json()
        if body.get("errno", 0) != 0:
            raise RuntimeError(f"FOX API error on {path}: {body}")
        return body.get("result", {})

    # ── Read ─────────────────────────────────────────────────────────────────

    def get_battery_soc(self) -> float:
        """Return current battery state of charge (%)."""
        result = self._get("/device/battery/soc/get", {"sn": self.device_sn})
        soc = result.get("soc", 0)
        log.debug(f"Battery SOC: {soc}%")
        return float(soc)

    def get_real_power(self) -> InverterStatus:
        """Return real-time power flow data."""
        result = self._get(
            "/device/real/query",
            {
                "sn": self.device_sn,
                "variables": "pvPower,meterPower,loadsPower,SoC,batPower,batTemperature,batVoltage,workMode",
            },
        )
        # FOX returns a list of variable:value pairs
        data = {item["variable"]: item.get("value", 0) for item in result.get("datas", [])}

        return InverterStatus(
            work_mode=data.get("workMode", "Unknown"),
            pv_power_kw=float(data.get("pvPower", 0)) / 1000,
            grid_power_kw=float(data.get("meterPower", 0)) / 1000,
            load_power_kw=float(data.get("loadsPower", 0)) / 1000,
            battery=BatteryStatus(
                soc=float(data.get("SoC", 0)),
                power_kw=float(data.get("batPower", 0)) / 1000,
                temperature=float(data.get("batTemperature", 0)),
                voltage=float(data.get("batVoltage", 0)),
            ),
        )

    # ── Write ─────────────────────────────────────────────────────────────────

    def set_work_mode(self, mode: str) -> None:
        """Set inverter work mode."""
        log.info(f"Setting FOX work mode → {mode}")
        self._post("/device/battery/forceChargeTime/set", {
            "sn": self.device_sn,
            "workMode": mode,
        })
        self._last_mode = mode

    def force_discharge(self, power_kw: float, min_soc: int = 15) -> None:
        """
        Force discharge to grid at the given power.
        power_kw: discharge power (capped at QLD 5kW export limit in config)
        min_soc: stop discharging below this SOC
        """
        power_w = int(power_kw * 1000)
        log.info(f"Force DISCHARGE: {power_kw}kW, stop at SOC {min_soc}%")
        self._post("/device/battery/forceDischargeTime/set", {
            "sn": self.device_sn,
            "enable1": True,
            "power1": power_w,
            "minSoc": min_soc,
            # 24-hour window — main.py controls when to stop
            "startTime1": {"hour": 0, "minute": 0},
            "stopTime1": {"hour": 23, "minute": 59},
        })
        self._last_mode = MODE_FORCE_DISCHARGE

    def force_charge(self, power_kw: float, target_soc: int = 95) -> None:
        """
        Force charge from grid at the given power.
        Used for: negative prices, very cheap off-peak, pre-spike preparation.
        """
        power_w = int(power_kw * 1000)
        log.info(f"Force CHARGE: {power_kw}kW, target SOC {target_soc}%")
        self._post("/device/battery/forceChargeTime/set", {
            "sn": self.device_sn,
            "enable1": True,
            "power1": power_w,
            "targetSoc": target_soc,
            "startTime1": {"hour": 0, "minute": 0},
            "stopTime1": {"hour": 23, "minute": 59},
        })
        self._last_mode = MODE_FORCE_CHARGE

    def self_use(self) -> None:
        """Return to normal Self Use mode (solar → home → battery → grid)."""
        log.info("Setting FOX → Self Use mode")
        self._post("/device/battery/forceChargeTime/set", {
            "sn": self.device_sn,
            "enable1": False,
            "enable2": False,
        })
        self._post("/device/battery/forceDischargeTime/set", {
            "sn": self.device_sn,
            "enable1": False,
            "enable2": False,
        })
        self._last_mode = MODE_SELF_USE

    @property
    def current_mode(self) -> Optional[str]:
        return self._last_mode
