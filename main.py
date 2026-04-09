"""
Amber Electric Price Monitor
发现价格异动时发送 Telegram 通知

Usage:
  python main.py           # 开始监控
  python main.py --dry-run # 只打印，不发通知
  python main.py --status  # 打印当前价格并退出
"""

import argparse
import logging
import os
import sys
import time
import yaml
from datetime import datetime
from dotenv import load_dotenv

from amber_client import AmberClient

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def status_report(amber: AmberClient) -> None:
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
    print()


def run(config: dict, dry_run: bool = False) -> None:
    from notifier import Notifier

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    amber_key = os.getenv("AMBER_API_KEY", "")

    amber = AmberClient(amber_key)
    notifier = Notifier(config, bot_token=bot_token, chat_id=chat_id)

    t = config["thresholds"]
    ctrl = config["control"]
    poll_sec = ctrl["poll_interval_seconds"]

    # 状态追踪
    was_spike = False
    was_negative = False
    last_sell: float | None = None
    last_buy: float = 0.0
    last_daily_summary: str = ""

    mode_str = "DRY RUN" if dry_run else "LIVE"
    log.info(f"{'='*55}")
    log.info(f"  Amber 价格监控 — {mode_str}")
    log.info(f"  Spike阈值: ${t['sell_high']:.2f} | 极端Spike: ${t['sell_extreme']:.2f}")
    log.info(f"  负电价阈值: ${t['negative_price']:.2f} | 轮询间隔: {poll_sec}s")
    log.info(f"{'='*55}")

    while True:
        loop_start = time.monotonic()
        try:
            prices = amber.get_current_prices()
            sell = prices.sell.price_kwh
            buy = prices.buy.price_kwh
            is_spike = prices.sell.is_spike

            log.info(prices.summary())

            if not dry_run:
                # ── Spike 检测 ────────────────────────────────────────────
                if is_spike and not was_spike:
                    notifier.spike_detected(sell)
                elif not is_spike and was_spike:
                    notifier.spike_ended(sell)

                # ── 负电价检测 ─────────────────────────────────────────────
                if buy <= t["negative_price"] and not was_negative:
                    notifier.negative_price(buy)

                # ── 极端高价提醒（即使 spike_status 未标记）────────────────
                if sell >= t["sell_extreme"] and not is_spike:
                    notifier.price_alert(sell, buy, f"极端高卖出价 ${sell:.4f}/kWh")

                # ── 大幅价格变动提醒 ──────────────────────────────────────
                sell_delta = abs(sell - last_sell) if last_sell is not None else 0.0
                if last_sell is not None and sell_delta >= t.get("alert_delta", 0.10):
                    direction = "↑" if sell > last_sell else "↓"
                    notifier.price_alert(sell, buy, f"卖出价大幅变动 {direction} ${sell_delta:.4f}/kWh")

            was_spike = is_spike
            was_negative = (buy <= t["negative_price"])
            last_sell = sell
            last_buy = buy

            # ── 每日总结 ──────────────────────────────────────────────────
            summary_time = config["notify"].get("daily_summary_time", "21:30")
            now_hm = datetime.now().strftime("%H:%M")
            if now_hm == summary_time and now_hm != last_daily_summary:
                if not dry_run:
                    notifier.daily_summary(sell, buy)
                last_daily_summary = now_hm

        except KeyboardInterrupt:
            log.info("监控停止")
            break
        except Exception as e:
            log.error(f"错误: {e}", exc_info=True)
            if not dry_run:
                notifier.error(str(e))

        elapsed = time.monotonic() - loop_start
        time.sleep(max(0, poll_sec - elapsed))


def main():
    parser = argparse.ArgumentParser(description="Amber 电价监控 + Telegram 通知")
    parser.add_argument("--dry-run", action="store_true", help="只打印日志，不发通知")
    parser.add_argument("--status", action="store_true", help="打印当前价格并退出")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    args = parser.parse_args()

    load_dotenv()
    config = load_config(args.config)

    if args.status:
        status_report(AmberClient(os.getenv("AMBER_API_KEY", "")))
        return

    run(config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
