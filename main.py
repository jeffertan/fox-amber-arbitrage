"""
Amber + Fox ESS 电价套利监控

Usage:
  python main.py              # 启动套利（arbitrage.enabled=true 时控制逆变器）
  python main.py --dry-run    # 只打印决策，不发通知也不控制逆变器
  python main.py --status     # 打印当前价格 + 电池状态并退出
"""

import argparse
import logging
import os
import re
import sys
import time
import yaml
from datetime import datetime, timedelta
from dotenv import load_dotenv

from amber_client import AmberClient
from strategy import ACTION_FORCE_DISCHARGE, ACTION_FORCE_CHARGE, ACTION_SELF_USE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

LOG_PATH = "monitor.log"


def prune_log(path: str, keep_days: int = 14) -> None:
    if not os.path.exists(path):
        return
    cutoff = datetime.now() - timedelta(days=keep_days)
    ts_re = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
    kept, removed = [], 0
    with open(path) as f:
        for line in f:
            m = ts_re.match(line)
            if m:
                try:
                    ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                    if ts < cutoff:
                        removed += 1
                        continue
                except ValueError:
                    pass
            kept.append(line)
    with open(path, "w") as f:
        f.writelines(kept)
    if removed:
        log.info(f"Log pruned: {removed} lines older than {keep_days} days removed")


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def status_report(amber: AmberClient, fox=None) -> None:
    print("\n─── Amber 当前价格 ────────────────────────────────")
    prices = amber.get_current_prices()
    print(f"  {prices.summary()}")
    print(f"  Spike状态: {prices.sell.spike_status}")

    print("\n─── 2小时预测 ────────────────────────────────────")
    forecast = amber.get_forecast(hours=2)
    for p in forecast:
        t = p.start_time.strftime("%H:%M")
        spike = " ← SPIKE" if p.is_spike else ""
        print(f"  {t}  ${p.price_kwh:.4f}/kWh{spike}")

    if fox:
        print("\n─── Fox 逆变器状态 ───────────────────────────────")
        try:
            status = fox.get_real_power()
            print(f"  工作模式: {status.work_mode}")
            print(f"  电池 SOC: {status.battery.soc:.0f}%")
            print(f"  太阳能: {status.pv_power_kw:.2f} kW")
            print(f"  电网: {status.grid_power_kw:+.2f} kW  (正=进口, 负=出口)")
            print(f"  家庭负载: {status.load_power_kw:.2f} kW")
        except Exception as e:
            print(f"  无法获取逆变器状态: {e}")
    print()


def _apply_decision(fox, decision, config: dict, dry_run: bool) -> None:
    if dry_run:
        log.info(f"[DRY RUN] {decision}")
        return
    night_reserve = config["battery"]["night_reserve_soc"]
    if decision.action == ACTION_FORCE_DISCHARGE:
        fox.force_discharge(decision.discharge_power_kw, min_soc=night_reserve)
    elif decision.action == ACTION_FORCE_CHARGE:
        fox.force_charge()
    else:
        fox.self_use()


def run(config: dict, dry_run: bool = False, state=None, config_path: str = "config.yaml") -> None:
    from notifier import Notifier

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    amber_key = os.getenv("AMBER_API_KEY", "")

    prune_log(LOG_PATH)
    amber = AmberClient(amber_key)
    notifier = Notifier(config, bot_token=bot_token, chat_id=chat_id, log_path=LOG_PATH)

    # ── 初始化套利组件 ──────────────────────────────────────────────────────────
    fox = None
    strategy = None
    solar_client = None
    if config.get("arbitrage", {}).get("enabled"):
        fox_key = os.getenv("FOX_API_KEY", "")
        fox_sn = os.getenv("FOX_DEVICE_SN", "")
        if fox_key:
            from fox_client import FoxClient
            from strategy import ArbitrageStrategy
            fox = FoxClient(fox_key, fox_sn)
            strategy = ArbitrageStrategy(config)
            log.info("套利策略已启用 — 将通过 Fox API 控制逆变器")
        else:
            log.warning("arbitrage.enabled=true 但 FOX_API_KEY 未设置，套利已跳过")

    if config.get("solar", {}).get("enabled"):
        from solar_forecast import SolarForecastClient
        solar_client = SolarForecastClient(config)
        log.info("太阳能预测已启用 (Open-Meteo)")

    was_spike = False
    was_negative = False
    was_buy_high = False
    was_sell_notify = False
    last_sell = None
    last_action = None
    last_daily_summary: str = ""
    last_action_start: datetime | None = None
    last_action_price_kwh: float = 0.0
    last_action_grid_kw: float = 0.0

    mode_str = "DRY RUN" if dry_run else ("LIVE + 套利" if fox else "仅监控")
    log.info(f"{'='*55}")
    log.info(f"  Amber 电价套利监控 — {mode_str}")
    log.info(f"{'='*55}")

    while True:
        loop_start = time.monotonic()
        # ── 热重载配置 ────────────────────────────────────────────────────────
        try:
            config = load_config(config_path)
        except Exception:
            pass  # keep using last good config on parse error
        t = config["thresholds"]
        poll_sec = config["control"]["poll_interval_seconds"]
        if strategy:
            strategy.cfg = config  # propagate updated thresholds to strategy
        try:
            prices = amber.get_current_prices()
            sell = prices.sell.price_kwh
            buy = prices.buy.price_kwh
            is_spike = prices.sell.is_spike

            log.info(prices.summary())
            if state:
                state.update_prices(buy, sell, prices.sell.spike_status)

            # ── 套利决策 ──────────────────────────────────────────────────────
            if fox and strategy:
                try:
                    inverter = fox.get_real_power()
                    solar = solar_client.get_tomorrow() if solar_client else None
                    if solar:
                        log.info(f"太阳能预测: {solar.summary()}")
                    log.info(
                        f"逆变器: SOC={inverter.battery.soc:.0f}%"
                        f" solar={inverter.pv_power_kw:.2f}kW"
                        f" grid={inverter.grid_power_kw:+.2f}kW"
                        f" load={inverter.load_power_kw:.2f}kW"
                    )
                    if state:
                        state.update_inverter(inverter)
                    decision = strategy.decide(prices, inverter, solar)
                    log.info(f"决策: {decision}")
                    if state:
                        state.update_decision(decision.action, decision.reason, strategy._avg_charge_cost)

                    if decision.action != last_action and not (state and state.is_manual_override()):
                        # Record trade for the action we're leaving
                        if state and last_action in (ACTION_FORCE_DISCHARGE, ACTION_FORCE_CHARGE) and last_action_start:
                            duration_sec = (datetime.now() - last_action_start).total_seconds()
                            state.record_trade(last_action, last_action_price_kwh, last_action_grid_kw, duration_sec)
                        _apply_decision(fox, decision, config, dry_run)
                        if not dry_run:
                            notifier.mode_change(decision)
                        last_action = decision.action
                        last_action_start = datetime.now()
                        last_action_price_kwh = sell if decision.action == ACTION_FORCE_DISCHARGE else buy
                        last_action_grid_kw = inverter.grid_power_kw
                except Exception as e:
                    log.error(f"套利执行错误: {e}", exc_info=True)

            if not dry_run:
                # ── Spike 检测 ────────────────────────────────────────────
                if is_spike and not was_spike:
                    notifier.spike_detected(sell)
                elif not is_spike and was_spike:
                    notifier.spike_ended(sell)

                # ── 负电价检测 ─────────────────────────────────────────────
                if buy <= t["negative_price"] and not was_negative:
                    notifier.negative_price(buy)

                # ── 极端高卖出收入（spike_status 未标记时兜底）───────────
                if sell <= -1.00 and not is_spike:
                    notifier.price_alert(sell, buy, f"极端高卖出收入 ${-sell:.4f}/kWh")

                # ── 大幅价格变动 ──────────────────────────────────────────
                sell_delta = abs(sell - last_sell) if last_sell is not None else 0.0
                if last_sell is not None and sell_delta >= t.get("alert_delta", 0.10):
                    direction = "↑" if sell > last_sell else "↓"
                    notifier.price_alert(sell, buy, f"卖出价大幅变动 {direction} ${sell_delta:.4f}/kWh")

                # ── 买入价偏高提醒 ────────────────────────────────────────
                buy_high = t.get("buy_high")
                if buy_high is not None:
                    if buy >= buy_high and not was_buy_high:
                        notifier.buy_high_alert(buy, buy_high)
                    elif buy < buy_high and was_buy_high:
                        notifier.buy_high_ended(buy)

                # ── 卖出价偏高提醒 ────────────────────────────────────────
                sell_notify = t.get("sell_notify")
                if sell_notify is not None:
                    if sell <= -sell_notify and not was_sell_notify:
                        notifier.sell_high_alert(sell, sell_notify)
                    elif sell > -sell_notify and was_sell_notify:
                        notifier.sell_high_ended(sell)

            was_spike = is_spike
            was_negative = (buy <= t["negative_price"])
            was_buy_high = (buy >= t.get("buy_high", float("inf")))
            was_sell_notify = (sell <= -t.get("sell_notify", float("inf")))
            last_sell = sell

            if not dry_run:
                notifier.poll_and_reply(sell, buy, prices.sell.spike_status)

            summary_time = config["notify"].get("daily_summary_time", "21:30")
            now_hm = datetime.now().strftime("%H:%M")
            if now_hm == summary_time and now_hm != last_daily_summary:
                if not dry_run:
                    notifier.daily_summary(sell, buy)
                last_daily_summary = now_hm

        except KeyboardInterrupt:
            log.info("监控停止")
            if fox and last_action != ACTION_SELF_USE and not dry_run:
                log.info("恢复逆变器至 Self Use 模式")
                try:
                    fox.self_use()
                except Exception:
                    pass
            break

        except Exception as e:
            log.error(f"错误: {e}", exc_info=True)
            if not dry_run:
                notifier.error(str(e))

        elapsed = time.monotonic() - loop_start
        time.sleep(max(0, poll_sec - elapsed))


def main():
    parser = argparse.ArgumentParser(description="Amber 电价套利监控")
    parser.add_argument("--dry-run", action="store_true", help="只打印决策，不控制逆变器也不发通知")
    parser.add_argument("--status", action="store_true", help="打印当前状态并退出")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    args = parser.parse_args()

    load_dotenv()
    config = load_config(args.config)

    if args.status:
        fox = None
        if config.get("arbitrage", {}).get("enabled"):
            fox_key = os.getenv("FOX_API_KEY", "")
            if fox_key:
                from fox_client import FoxClient
                fox = FoxClient(fox_key, os.getenv("FOX_DEVICE_SN", ""))
        status_report(AmberClient(os.getenv("AMBER_API_KEY", "")), fox)
        return

    run(config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
