"""
Notification module — Telegram bot.
"""

import logging
import requests
from datetime import date

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, config: dict, bot_token: str = "", chat_id: str = ""):
        self.cfg = config.get("notify", {})
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._today = date.today()
        self._daily_spike_count: int = 0
        self._daily_negative_count: int = 0
        self._last_update_id: int = 0
        self._delete_webhook()

    # ── Public methods ────────────────────────────────────────────────────────

    @staticmethod
    def _fmt_sell(sell_price: float) -> str:
        """Display sell price from user's perspective (positive = money received)."""
        if sell_price < 0:
            return f"太阳能卖出 `${abs(sell_price):.4f}/kWh`"
        return f"卖出 `${sell_price:.4f}/kWh`"

    def spike_detected(self, sell_price: float):
        if not self.cfg.get("on_spike_detected"):
            return
        self._daily_spike_count += 1
        msg = (
            f"⚡️ *电价Spike!*\n"
            f"{self._fmt_sell(sell_price)}\n"
            f"建议: 考虑放电套利"
        )
        self._send(msg)

    def spike_ended(self, sell_price: float):
        if not self.cfg.get("on_spike_detected"):
            return
        msg = (
            f"✅ *Spike结束*\n"
            f"当前{self._fmt_sell(sell_price)}"
        )
        self._send(msg)

    def negative_price(self, buy_price: float):
        if not self.cfg.get("on_negative_price"):
            return
        self._daily_negative_count += 1
        msg = (
            f"💰 *负电价!*\n"
            f"买入价: `${buy_price:.4f}/kWh`\n"
            f"建议: 电网在倒贴钱，可以充电"
        )
        self._send(msg)

    def price_alert(self, sell_price: float, buy_price: float, reason: str):
        """Generic price alert for significant changes."""
        msg = (
            f"📢 *价格提醒*\n"
            f"{reason}\n"
            f"买入: `${buy_price:.4f}/kWh` | {self._fmt_sell(sell_price)}"
        )
        self._send(msg)

    def daily_summary(self, sell_price: float, buy_price: float):
        if not self.cfg.get("on_daily_summary"):
            return
        self._reset_if_new_day()
        msg = (
            f"📊 *今日电价总结* ({date.today()})\n"
            f"当前买入: `${buy_price:.4f}/kWh`\n"
            f"当前{self._fmt_sell(sell_price)}\n"
            f"今日Spike次数: {self._daily_spike_count}\n"
            f"今日负电价次数: {self._daily_negative_count}"
        )
        self._send(msg)
        self._daily_spike_count = 0
        self._daily_negative_count = 0

    def buy_high_alert(self, buy_price: float, threshold: float):
        msg = (
            f"🔴 *买入价偏高*\n"
            f"买入: `${buy_price:.4f}/kWh`（阈值 ${threshold:.2f}）\n"
            f"建议: 减少用电"
        )
        self._send(msg)

    def buy_high_ended(self, buy_price: float):
        msg = f"🟢 *买入价恢复正常*\n当前买入: `${buy_price:.4f}/kWh`"
        self._send(msg)

    def sell_high_alert(self, sell_price: float, threshold: float):
        msg = (
            f"☀️ *卖出价偏高*\n"
            f"{self._fmt_sell(sell_price)}（阈值 ${threshold:.2f}）\n"
            f"建议: 适合太阳能卖电"
        )
        self._send(msg)

    def sell_high_ended(self, sell_price: float):
        msg = f"🟢 *卖出价回落*\n当前{self._fmt_sell(sell_price)}"
        self._send(msg)

    def current_prices(self, sell_price: float, buy_price: float, spike_status: str):
        """Reply with current buy/sell prices on demand."""
        spike_tag = ""
        if spike_status in ("spike", "extremelyHigh"):
            spike_tag = "\n⚡️ *当前处于Spike状态！*"
        neg_tag = " _(负电价)_" if buy_price < 0 else ""
        msg = (
            f"💡 *当前电价*\n"
            f"买入: `${buy_price:.4f}/kWh`{neg_tag}\n"
            f"{self._fmt_sell(sell_price)}"
            f"{spike_tag}"
        )
        self._send(msg)

    def poll_and_reply(self, sell_price: float, buy_price: float, spike_status: str):
        """Poll Telegram for new messages and reply with current prices."""
        if not self.bot_token:
            return
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
            r = requests.get(
                url,
                params={"offset": self._last_update_id + 1, "timeout": 0},
                timeout=5,
            )
            r.raise_for_status()
            updates = r.json().get("result", [])
        except Exception as e:
            log.warning(f"Telegram getUpdates failed: {e}")
            return

        for update in updates:
            self._last_update_id = update["update_id"]
            message = update.get("message") or update.get("edited_message")
            if not message:
                continue
            # Reply to the sender's chat
            reply_chat_id = str(message["chat"]["id"])
            spike_tag = ""
            if spike_status in ("spike", "extremelyHigh"):
                spike_tag = "\n⚡️ *当前处于Spike状态！*"
            neg_tag = " _(负电价)_" if buy_price < 0 else ""
            msg = (
                f"💡 *当前电价*\n"
                f"买入: `${buy_price:.4f}/kWh`{neg_tag}\n"
                f"{self._fmt_sell(sell_price)}"
                f"{spike_tag}"
            )
            self._send_to(msg, reply_chat_id)
            log.info(f"Replied to message from chat_id={reply_chat_id}")

    def error(self, error_msg: str):
        if not self.cfg.get("on_error"):
            return
        msg = f"❌ *系统错误*\n`{error_msg}`"
        self._send(msg)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _delete_webhook(self):
        """Delete any existing webhook so getUpdates polling works."""
        if not self.bot_token:
            return
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/deleteWebhook"
            r = requests.post(url, timeout=5)
            result = r.json()
            if result.get("result"):
                log.info("Telegram webhook deleted (polling mode active)")
            else:
                log.info(f"deleteWebhook: {result.get('description', result)}")
        except Exception as e:
            log.warning(f"Could not delete Telegram webhook: {e}")

    def _reset_if_new_day(self):
        today = date.today()
        if today != self._today:
            self._daily_spike_count = 0
            self._daily_negative_count = 0
            self._today = today

    def _send(self, message: str):
        log.info(f"[NOTIFY] {message}")
        if self.bot_token and self.chat_id:
            self._send_to(message, self.chat_id)

    def _send_to(self, message: str, chat_id: str):
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            r = requests.post(
                url,
                json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
                timeout=5,
            )
            r.raise_for_status()
        except Exception as e:
            log.warning(f"Telegram notification failed: {e}")
