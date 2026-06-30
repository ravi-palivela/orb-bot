#!/usr/bin/env python3
"""
ORB Trading Alert Bot
Sends timed alerts to Telegram for QQQ/SPY Opening Range Breakout strategy.
Fires Mon/Wed/Fri only. All times in CT (America/Chicago).

Alerts:
  08:20 AM — Pre-market brief + unusual options reminder
  08:35 AM — Opening range locked (first 5-min candle high/low)
  08:42 AM — Breakout entry window check
  02:30 PM — Hard close reminder

Deploy on Railway (free tier) as a worker process. Runs 24/7.
"""

import os
import requests
import yfinance as yf
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.blocking import BlockingScheduler

# ── Config ─────────────────────────────────────────────────────────────────────
TOKEN   = os.environ.get("TELEGRAM_TOKEN", "8737927277:AAGQexxm09r-xJlOHPX5HkJGqDWIxrRNeuI")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8770807452")
CT      = ZoneInfo("America/Chicago")

# ── Helpers ────────────────────────────────────────────────────────────────────

def send(text: str) -> None:
    """Send a Telegram message."""
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        r.raise_for_status()
        print(f"[{now_ct()}] Sent: {text[:60]}...")
    except Exception as e:
        print(f"[{now_ct()}] Telegram error: {e}")


def now_ct() -> str:
    return datetime.now(CT).strftime("%Y-%m-%d %H:%M:%S CT")


def is_trading_day() -> bool:
    """True on Mon (0), Wed (2), Fri (4)."""
    return datetime.now(CT).weekday() in (0, 2, 4)


def get_quote(ticker: str, premarket: bool = False) -> dict:
    """
    Fetch latest price + % change vs. previous close.
    premarket=True uses pre/post-market data.
    Returns dict with keys: price, pct, arrow.
    """
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="2d", interval="1m", prepost=premarket)
        if hist.empty:
            return {"price": "N/A", "pct": "N/A", "arrow": ""}

        # Convert index to CT for date comparison
        hist.index = hist.index.tz_convert(CT)
        today = datetime.now(CT).date()
        today_bars = hist[hist.index.date == today]

        latest_price = today_bars["Close"].iloc[-1] if not today_bars.empty else hist["Close"].iloc[-1]

        # Previous close: last bar from yesterday
        prev_bars = hist[hist.index.date < today]
        prev_close = prev_bars["Close"].iloc[-1] if not prev_bars.empty else latest_price

        pct = ((latest_price - prev_close) / prev_close) * 100
        arrow = "▲" if pct >= 0 else "▼"

        return {
            "price": f"${latest_price:.2f}",
            "pct":   f"{arrow} {abs(pct):.2f}%",
            "arrow": arrow,
        }
    except Exception as e:
        print(f"[{now_ct()}] Quote error ({ticker}): {e}")
        return {"price": "N/A", "pct": "N/A", "arrow": ""}


def get_opening_range(ticker: str) -> dict:
    """
    High and low of the first 5 one-minute candles of the regular session.
    Call at or after 8:35 AM CT (9:35 AM ET).
    """
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="1d", interval="1m", prepost=False)
        if hist.empty:
            return {"high": "N/A", "low": "N/A"}

        hist.index = hist.index.tz_convert(CT)
        today = datetime.now(CT).date()
        today_bars = hist[hist.index.date == today].head(5)

        if today_bars.empty:
            return {"high": "N/A", "low": "N/A"}

        return {
            "high": f"${today_bars['High'].max():.2f}",
            "low":  f"${today_bars['Low'].min():.2f}",
        }
    except Exception as e:
        print(f"[{now_ct()}] ORB error ({ticker}): {e}")
        return {"high": "N/A", "low": "N/A"}


# ── Alerts ─────────────────────────────────────────────────────────────────────

def morning_briefing() -> None:
    """8:20 AM CT — Pre-market data + day setup."""
    if not is_trading_day():
        return

    day = datetime.now(CT).strftime("%A %b %-d")
    qqq = get_quote("QQQ", premarket=True)
    spy = get_quote("SPY", premarket=True)

    msg = (
        f"🌅 <b>ORB Morning Brief — {day}</b>\n\n"
        f"<b>QQQ</b>  {qqq['price']}   {qqq['pct']}\n"
        f"<b>SPY</b>  {spy['price']}   {spy['pct']}\n\n"
        f"📊 <b>Unusual Options:</b> Open Robinhood → Screeners\n"
        f"Run <i>High options volume &amp; IV</i> scan. Flag top names NOT already up 15%+. "
        f"Catch the move, don't chase it.\n\n"
        f"⏱ <b>Today's timeline (all CT):</b>\n"
        f"  8:30 AM  Market opens\n"
        f"  8:35 AM  First candle locks → ORB set\n"
        f"  8:36–42  Watch for breakout\n"
        f"  8:42 AM  Entry decision\n"
        f"  2:30 PM  Hard close 🔴\n\n"
        f"<i>1 trade max • ~80% capital • ATM call/put only</i>"
    )
    send(msg)


def range_lock() -> None:
    """8:35 AM CT — Opening range high/low locked."""
    if not is_trading_day():
        return

    qqq      = get_quote("QQQ")
    spy      = get_quote("SPY")
    qqq_orb  = get_opening_range("QQQ")
    spy_orb  = get_opening_range("SPY")

    msg = (
        f"🔔 <b>Opening Range Locked — 8:35 AM CT</b>\n\n"
        f"<b>QQQ</b>  {qqq['price']}  ({qqq['pct']})\n"
        f"  High: {qqq_orb['high']}   Low: {qqq_orb['low']}\n\n"
        f"<b>SPY</b>  {spy['price']}  ({spy['pct']})\n"
        f"  High: {spy_orb['high']}   Low: {spy_orb['low']}\n\n"
        f"👀 Watch for breakout <b>above</b> or breakdown <b>below</b> the range.\n"
        f"Entry window: <b>8:36–8:42 AM CT</b>"
    )
    send(msg)


def breakout_check() -> None:
    """8:42 AM CT — Is there a clean breakout?"""
    if not is_trading_day():
        return

    qqq     = get_quote("QQQ")
    spy     = get_quote("SPY")
    qqq_orb = get_opening_range("QQQ")
    spy_orb = get_opening_range("SPY")

    msg = (
        f"⚡ <b>Breakout Window — 8:42 AM CT</b>\n\n"
        f"<b>QQQ</b>  {qqq['price']}  ({qqq['pct']})\n"
        f"  ORB: {qqq_orb['low']} ↔ {qqq_orb['high']}\n\n"
        f"<b>SPY</b>  {spy['price']}  ({spy['pct']})\n"
        f"  ORB: {spy_orb['low']} ↔ {spy_orb['high']}\n\n"
        f"✅ Break above range → <b>ATM CALL</b> on cleaner mover\n"
        f"✅ Break below range → <b>ATM PUT</b>\n"
        f"❌ Choppy / inside range → <b>PASS</b> — no trade is a trade\n\n"
        f"<i>Stop at -50% immediately. Target +100%. "
        f"Stop orders open at 8:45 AM CT.</i>"
    )
    send(msg)


def hard_close() -> None:
    """2:30 PM CT — Exit all positions. No exceptions."""
    if not is_trading_day():
        return

    qqq = get_quote("QQQ")
    spy = get_quote("SPY")

    msg = (
        f"🔴 <b>HARD CLOSE — 2:30 PM CT</b>\n\n"
        f"<b>QQQ</b>  {qqq['price']}  {qqq['pct']}\n"
        f"<b>SPY</b>  {spy['price']}  {spy['pct']}\n\n"
        f"<b>EXIT ALL POSITIONS NOW. No exceptions.</b>\n\n"
        f"Reply with your result — win / loss / pass — to log the day."
    )
    send(msg)


# ── Scheduler ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone="America/Chicago")

    scheduler.add_job(morning_briefing, "cron", day_of_week="mon,wed,fri", hour=8,  minute=20)
    scheduler.add_job(range_lock,       "cron", day_of_week="mon,wed,fri", hour=8,  minute=35)
    scheduler.add_job(breakout_check,   "cron", day_of_week="mon,wed,fri", hour=8,  minute=42)
    scheduler.add_job(hard_close,       "cron", day_of_week="mon,wed,fri", hour=14, minute=30)

    print(f"[{now_ct()}] ORB Bot started. Waiting for scheduled alerts...")

    # Announce bot is live
    send(
        "🤖 <b>ORB Trading Bot is online!</b>\n\n"
        "Alerts scheduled for Mon / Wed / Fri:\n"
        "  8:20 AM  Morning brief\n"
        "  8:35 AM  Opening range locked\n"
        "  8:42 AM  Breakout check\n"
        "  2:30 PM  Hard close\n\n"
        "Good trading, Ravi 📈"
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped.")
