"""FastAPI web dashboard for Fox-Amber arbitrage."""
from __future__ import annotations

import os
import threading
import yaml
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from jose import JWTError, jwt
from pydantic import BaseModel

from state import StateStore

load_dotenv()

SECRET_KEY = os.getenv("DASHBOARD_SECRET", "change-me-in-production-32chars!!")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "admin")
ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours
CONFIG_PATH = Path("config.yaml")

app = FastAPI(title="Fox-Amber Dashboard")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")

_state = StateStore()


# ── Auth ──────────────────────────────────────────────────────────────────────

def _create_token(data: dict) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    return jwt.encode({**data, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


async def _current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> str:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Invalid token")
        return sub
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


@app.post("/api/login")
async def login(form: Annotated[OAuth2PasswordRequestForm, Depends()]):
    if form.password != DASHBOARD_PASSWORD:
        raise HTTPException(status_code=401, detail="Incorrect password")
    return {"access_token": _create_token({"sub": "admin"}), "token_type": "bearer"}


# ── Data endpoints ────────────────────────────────────────────────────────────

def _fmt(snap) -> dict | None:
    if snap is None:
        return None
    d = snap.__dict__.copy()
    if "timestamp" in d and isinstance(d["timestamp"], datetime):
        d["timestamp"] = d["timestamp"].isoformat()
    return d


@app.get("/api/status")
async def status_endpoint(_: Annotated[str, Depends(_current_user)]):
    snap = _state.snapshot()
    return {
        "prices": _fmt(snap["prices"]),
        "inverter": _fmt(snap["inverter"]),
        "decision": _fmt(snap["decision"]),
        "override": _state.override_info(),
    }


@app.get("/api/history")
async def history(_: Annotated[str, Depends(_current_user)], days: int = 7):
    snap = _state.snapshot()
    cutoff = datetime.now() - timedelta(days=days)
    return [
        {"t": p.timestamp.isoformat(), "buy": p.buy_kwh, "sell": -p.sell_kwh}
        for p in snap["history"]
        if p.timestamp >= cutoff
    ]


@app.get("/api/analytics/daily")
async def analytics_daily(_: Annotated[str, Depends(_current_user)], days: int = 30):
    return _state.get_daily_analytics(days)


@app.get("/api/analytics/trades")
async def analytics_trades(_: Annotated[str, Depends(_current_user)], limit: int = 20):
    trades = _state.get_recent_trades(limit)
    return [
        {
            "timestamp": t.timestamp.isoformat(),
            "action": t.action,
            "price_kwh": t.price_kwh,
            "grid_kw": t.grid_kw,
            "duration_sec": t.duration_sec,
            "est_kwh": t.est_kwh,
            "est_revenue": t.est_revenue,
        }
        for t in trades
    ]


@app.get("/api/config")
async def get_config(_: Annotated[str, Depends(_current_user)]):
    return yaml.safe_load(CONFIG_PATH.read_text())


class ConfigUpdate(BaseModel):
    section: str
    key: str
    value: Any


_DEFAULT_CONFIG: dict = {
    "thresholds": {
        "sell_threshold": 0.10,
        "negative_price": 0.0,
        "min_profit_margin": 0.05,
        "night_cheap_buy": 0.08,
        "alert_delta": 0.10,
        "buy_high": 0.50,
        "sell_notify": 0.25,
    },
    "battery": {
        "night_reserve_soc": 25,
        "night_target_soc": 30,
        "max_charge_kw": 5.0,
        "max_discharge_kw": 5.0,
    },
    "schedule": {
        "day_start": "07:00",
        "night_start": "23:00",
        "max_grid_charge_hour": 14,
    },
    "control": {
        "poll_interval_seconds": 120,
        "manual_override_minutes": 60,
    },
}


@app.put("/api/config")
async def update_config(
    update: ConfigUpdate,
    _: Annotated[str, Depends(_current_user)],
):
    allowed_sections = {"thresholds", "battery", "schedule", "control", "solar", "notify"}
    if update.section not in allowed_sections:
        raise HTTPException(status_code=400, detail=f"Section '{update.section}' not editable")
    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    if update.section not in cfg or update.key not in cfg[update.section]:
        raise HTTPException(status_code=400, detail="Unknown config key")
    cfg[update.section][update.key] = update.value
    CONFIG_PATH.write_text(yaml.dump(cfg, allow_unicode=True, sort_keys=False))
    return {"ok": True}


@app.post("/api/config/reset")
async def reset_config(_: Annotated[str, Depends(_current_user)]):
    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    for section, keys in _DEFAULT_CONFIG.items():
        if section in cfg:
            cfg[section].update(keys)
    CONFIG_PATH.write_text(yaml.dump(cfg, allow_unicode=True, sort_keys=False))
    return {"ok": True, "defaults": _DEFAULT_CONFIG}


@app.get("/api/config/defaults")
async def get_defaults(_: Annotated[str, Depends(_current_user)]):
    return _DEFAULT_CONFIG


# ── Cached Fox client (avoids SN rediscovery per request) ────────────────────

_fox_client = None

def _get_fox() -> object:
    global _fox_client
    if _fox_client is None:
        fox_key = os.getenv("FOX_API_KEY", "")
        fox_sn = os.getenv("FOX_DEVICE_SN", "")
        if not fox_key:
            raise HTTPException(status_code=503, detail="FOX_API_KEY not configured")
        from fox_client import FoxClient
        _fox_client = FoxClient(fox_key, fox_sn)
    return _fox_client


# ── Manual control ────────────────────────────────────────────────────────────

class ControlRequest(BaseModel):
    action: str           # "force_charge" | "force_discharge" | "self_use"
    discharge_kw: float = 5.0
    charge_target_soc: int = 95   # stop charging above this %
    discharge_min_soc: int = 25   # stop discharging below this %


@app.post("/api/control")
async def manual_control(
    req: ControlRequest,
    _: Annotated[str, Depends(_current_user)],
):
    if req.action == "force_charge" and not (10 <= req.charge_target_soc <= 100):
        raise HTTPException(status_code=400, detail="charge_target_soc must be 10–100")
    if req.action == "force_discharge" and not (5 <= req.discharge_min_soc <= 95):
        raise HTTPException(status_code=400, detail="discharge_min_soc must be 5–95")

    fox = _get_fox()
    if req.action == "force_discharge":
        fox.force_discharge(req.discharge_kw, min_soc=req.discharge_min_soc)
    elif req.action == "force_charge":
        fox.force_charge(target_soc=req.charge_target_soc)
    elif req.action == "self_use":
        fox.self_use()
        _state.clear_manual_override()
        return {"ok": True, "action": req.action}
    else:
        raise HTTPException(status_code=400, detail="Unknown action")

    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    override_minutes = cfg.get("control", {}).get("manual_override_minutes", 60)
    _state.set_manual_override(req.action, override_minutes)
    return {"ok": True, "action": req.action, "override_minutes": override_minutes}


@app.get("/api/override")
async def get_override(_: Annotated[str, Depends(_current_user)]):
    return _state.override_info()


@app.delete("/api/override")
async def cancel_override(_: Annotated[str, Depends(_current_user)]):
    _state.clear_manual_override()
    return {"ok": True}


# ── Amber forecast passthrough ─────────────────────────────────────────────────

@app.get("/api/forecast")
async def forecast(_: Annotated[str, Depends(_current_user)], hours: int = 4):
    amber_key = os.getenv("AMBER_API_KEY", "")
    from amber_client import AmberClient
    amber = AmberClient(amber_key)
    points = amber.get_forecast(hours)
    return [
        {"t": p.start_time.isoformat(), "sell": -p.price_kwh, "is_spike": p.is_spike}
        for p in points
    ]


# ── Serve React SPA ───────────────────────────────────────────────────────────

DIST = Path("frontend/dist")

if DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        file = DIST / full_path
        if file.is_file():
            return FileResponse(str(file))
        return FileResponse(str(DIST / "index.html"))


# ── Background polling thread ─────────────────────────────────────────────────

def _start_polling():
    _state.load_history_from_log("monitor.log")
    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    from main import run
    t = threading.Thread(
        target=run, args=(cfg,),
        kwargs={"state": _state, "config_path": str(CONFIG_PATH)},
        daemon=True,
    )
    t.start()


@app.on_event("startup")
async def startup():
    _start_polling()
