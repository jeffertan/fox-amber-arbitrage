"""
FOX ESS Open API client.
API docs: https://www.foxesscloud.com/public/i18n/en/OpenApiDocument.html

Authentication: HMAC-MD5 signature
  signature = md5("<path>\r\n<token>\r\n<timestamp>")

Work mode control uses the scheduler endpoint exclusively:
  POST /op/v0/device/scheduler/enable
"""

import hashlib
import time
import logging
import requests
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

FOX_BASE = "https://www.foxesscloud.com/op/v0"

MODE_SELF_USE = "SelfUse"
MODE_FEED_IN = "Feedin"
MODE_BACKUP = "Backup"
MODE_FORCE_CHARGE = "ForceCharge"
MODE_FORCE_DISCHARGE = "ForceDischarge"


@dataclass
class BatteryStatus:
    soc: float
    power_kw: float       # positive = charging, negative = discharging
    temperature: float
    voltage: float


@dataclass
class InverterStatus:
    work_mode: str
    pv_power_kw: float
    grid_power_kw: float  # positive = import, negative = export
    load_power_kw: float
    battery: BatteryStatus


class FoxClient:
    def __init__(self, api_key: str, device_sn: str = ""):
        if not api_key:
            raise ValueError("FOX_API_KEY is not set")
        self.api_key = api_key
        self._device_sn = device_sn or ""
        self._last_mode: Optional[str] = None

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _sign(self, path: str) -> dict:
        timestamp = str(round(time.time() * 1000))
        # FoxESS API requires literal \r\n (4 chars) and full /op/v0 prefix in the signed string
        full_path = f"/op/v0{path}"
        raw = full_path + r"\r\n" + self.api_key + r"\r\n" + timestamp
        signature = hashlib.md5(raw.encode("UTF-8")).hexdigest()
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

    # ── Device discovery ──────────────────────────────────────────────────────

    @property
    def device_sn(self) -> str:
        if not self._device_sn:
            self._device_sn = self._fetch_device_sn()
        return self._device_sn

    def _fetch_device_sn(self) -> str:
        log.info("Auto-discovering FOX device SN...")
        result = self._post("/device/list", {"currentPage": 1, "pageSize": 10})
        devices = result.get("devices", result.get("data", []))
        if not devices:
            raise RuntimeError(
                "No FOX devices found. Set FOX_DEVICE_SN in .env as a fallback."
            )
        sn = devices[0].get("deviceSN", devices[0].get("sn", ""))
        if not sn:
            raise RuntimeError(f"Cannot extract SN from device response: {devices[0]}")
        log.info(f"Discovered FOX device SN: {sn}")
        return sn

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_battery_soc(self) -> float:
        """Return current battery SOC via real/query (the soc/get endpoint returns settings, not live data)."""
        return self.get_real_power().battery.soc

    def get_real_power(self) -> InverterStatus:
        # Response is a list; the first element contains a "datas" array
        result = self._post("/device/real/query", {
            "sn": self.device_sn,
            "variables": [
                "pvPower", "meterPower", "loadsPower",
                "SoC", "batPower", "batTemperature", "batVoltage", "workMode",
            ],
        })
        # Unwrap list wrapper
        if isinstance(result, list):
            datas = result[0].get("datas", []) if result else []
        else:
            datas = result.get("datas", [])
        data = {item["variable"]: item.get("value", 0) for item in datas}
        pv   = float(data.get("pvPower", 0))
        grid = float(data.get("meterPower", 0))
        load = float(data.get("loadsPower", 0))
        # batPower often absent from API; derive from power balance (positive = charging)
        bat_power = float(data["batPower"]) if "batPower" in data else round(pv + grid - load, 3)
        work_mode = str(data["workMode"]) if "workMode" in data else (self._last_mode or "Unknown")
        return InverterStatus(
            work_mode=work_mode,
            pv_power_kw=pv,
            grid_power_kw=grid,
            load_power_kw=load,
            battery=BatteryStatus(
                soc=float(data.get("SoC", 0)),
                power_kw=bat_power,
                temperature=float(data.get("batTemperature", 0)),
                voltage=float(data.get("batVoltage", 0)),
            ),
        )

    # ── Scheduler (mode control) ──────────────────────────────────────────────

    def _set_scheduler(
        self,
        work_mode: str,
        fd_pwr_w: int = 0,
        fd_soc: int = 10,
        min_soc_on_grid: int = 10,
    ) -> None:
        """Set a single 24h scheduler segment with the given work mode.

        All mode changes go through this endpoint per the FoxESS API spec.
        ForceDischarge uses fdPwr (watts) and fdSoc (stop-discharge SOC %).
        """
        log.info(
            f"Scheduler → {work_mode} "
            f"(fdPwr={fd_pwr_w}W, fdSoc={fd_soc}%, minSoc={min_soc_on_grid}%)"
        )
        self._post("/device/scheduler/enable", {
            "deviceSN": self.device_sn,
            "groups": [{
                "enable": 1,
                "startHour": 0,
                "startMinute": 0,
                "endHour": 23,
                "endMinute": 59,
                "workMode": work_mode,
                "minSocOnGrid": min_soc_on_grid,
                "fdSoc": fd_soc,
                "fdPwr": fd_pwr_w,
            }],
        })
        self._last_mode = work_mode

    # ── Write ─────────────────────────────────────────────────────────────────

    def force_discharge(self, power_kw: float, min_soc: int = 15) -> None:
        """Force discharge to grid. min_soc: stop discharging below this SOC %."""
        power_w = int(power_kw * 1000)
        self._set_scheduler(
            MODE_FORCE_DISCHARGE,
            fd_pwr_w=power_w,
            fd_soc=min_soc,
            min_soc_on_grid=min_soc,
        )

    def force_charge(self, target_soc: int = 95, charge_power_kw: float = 5.0) -> None:
        """Force charge from grid up to target_soc % at charge_power_kw."""
        self._set_scheduler(
            MODE_FORCE_CHARGE,
            fd_pwr_w=int(charge_power_kw * 1000),
            fd_soc=target_soc,
            min_soc_on_grid=10,
        )

    def self_use(self) -> None:
        """Return to normal Self Use mode (solar → home → battery → grid)."""
        self._set_scheduler(MODE_SELF_USE)

    @property
    def current_mode(self) -> Optional[str]:
        return self._last_mode
