#!/usr/bin/env python3
"""
ORB Trading Alert Bot
Sends timed alerts + responds to messages on Telegram.
Fires scheduled alerts Mon–Fri (CT). Responds to messages any time.

Scheduled alerts (all CT):
  Mon/Wed/Fri:
    08:20 AM — Pre-market brief + unusual options reminder
    08:35 AM — Opening range locked (first 5-min candle high/low)
    08:42 AM — Breakout entry window check
    02:30 PM — Hard close reminder
  Tue/Thu:
    08:20 AM — Unusual options screener alert (no ORB trade)

Interactive commands:
  QQQ / SPY / <any ticker>  — instant quote
  /brief                    — run morning briefing now
  /trade                    — log entry, get stop reminder
  /win <amount>             — log a win
  /loss <amount>            — log a loss
  /pass                     — log a pass (no trade)
  /help                     — show all commands
"""

import os
import time
import requests
import yfinance as yf
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler

# ── Config ─────────────────────────────────────────────────────────────────────
TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "8737927277:AAGQexxm09r-xJlOHPX5HkJGqDWIxrRNeuI")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8770807452")
CT      = ZoneInfo("America/Chicago")


# ── Helpers ────────────────────────────────────────────────────────────────────

def now_ct() -> str:
    return datetime.now(CT).strftime("%Y-%m-%d %H:%M:%S CT")


def send(text: str) -> None:
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        r.raise_for_status()
        print(f"[{now_ct()}] Sent: {text[:80].strip()}...")
    except Exception as e:
        print(f"[{now_ct()}] Send error: {e}")


def is_trading_day() -> bool:
    return datetime.now(CT).weekday() in (0, 2, 4)


def get_quote(ticker: str, premarket: bool = False) -> dict:
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="2d", interval="1m", prepost=premarket)
        if hist.empty:
            return {"price": "N/A", "pct": "N/A", "arrow": ""}

        hist.index = hist.index.tz_convert(CT)
        today = datetime.now(CT).date()
        today_bars = hist[hist.index.date == today]
        prev_bars  = hist[hist.index.date < today]

        latest    = today_bars["Close"].iloc[-1] if not today_bars.empty else hist["Close"].iloc[-1]
        prev_close = prev_bars["Close"].iloc[-1]  if not prev_bars.empty  else latest

        pct   = ((latest - prev_close) / prev_close) * 100
        arrow = "▲" if pct >= 0 else "▼"

        return {
            "price": f"${latest:.2f}",
            "pct":   f"{arrow} {abs(pct):.2f}%",
            "arrow": arrow,
        }
    except Exception as e:
        print(f"[{now_ct()}] Quote error ({ticker}): {e}")
        return {"price": "N/A", "pct": "N/A", "arrow": ""}


def get_opening_range(ticker: str) -> dict:
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="1d", interval="1m", prepost=False)
        if hist.empty:
            return {"high": "N/A", "low": "N/A"}

        hist.index = hist.index.tz_convert(CT)
        today      = datetime.now(CT).date()
        first_5    = hist[hist.index.date == today].head(5)

        if first_5.empty:
            return {"high": "N/A", "low": "N/A"}

        return {
            "high": f"${first_5['High'].max():.2f}",
            "low":  f"${first_5['Low'].min():.2f}",
        }
    except Exception as e:
        print(f"[{now_ct()}] ORB error ({ticker}): {e}")
        return {"high": "N/A", "low": "N/A"}


# ── Scheduled alerts ───────────────────────────────────────────────────────────

def morning_briefing(force: bool = False) -> None:
    if not force and not is_trading_day():
        return

    day = datetime.now(CT).strftime("%A %b %-d")
    qqq = get_quote("QQQ", premarket=True)
    spy = get_quote("SPY", premarket=True)

    send(
        f"🌅 <b>ORB Morning Brief — {day}</b>\n\n"
        f"<b>QQQ</b>  {qqq['price']}   {qqq['pct']}\n"
        f"<b>SPY</b>  {spy['price']}   {spy['pct']}\n\n"
        f"📊 <b>Unusual Options:</b> Open Robinhood → Screeners\n"
        f"Run <i>High options volume &amp; IV</i>. Flag names NOT already up 15%+.\n\n"
        f"⏱ <b>Timeline (CT):</b>\n"
        f"  8:30  Market opens\n"
        f"  8:35  First candle locks → ORB set\n"
        f"  8:36–42  Breakout watch\n"
        f"  8:42  Entry decision\n"
        f"  2:30 PM  Hard close 🔴\n\n"
        f"<i>1 trade max • ~80% capital • ATM call/put only</i>"
    )


def range_lock() -> None:
    if not is_trading_day():
        return

    qqq     = get_quote("QQQ")
    spy     = get_quote("SPY")
    qqq_orb = get_opening_range("QQQ")
    spy_orb = get_opening_range("SPY")

    send(
        f"🔔 <b>Opening Range Locked — 8:35 AM CT</b>\n\n"
        f"<b>QQQ</b>  {qqq['price']}  ({qqq['pct']})\n"
        f"  High: {qqq_orb['high']}   Low: {qqq_orb['low']}\n\n"
        f"<b>SPY</b>  {spy['price']}  ({spy['pct']})\n"
        f"  High: {spy_orb['high']}   Low: {spy_orb['low']}\n\n"
        f"👀 Watch for breakout above or breakdown below over next 7 min.\n"
        f"Entry window: <b>8:36–8:42 AM CT</b>"
    )


def breakout_check() -> None:
    if not is_trading_day():
        return

    qqq     = get_quote("QQQ")
    spy     = get_quote("SPY")
    qqq_orb = get_opening_range("QQQ")
    spy_orb = get_opening_range("SPY")

    send(
        f"⚡ <b>Breakout Window — 8:42 AM CT</b>\n\n"
        f"<b>QQQ</b>  {qqq['price']}  ({qqq['pct']})\n"
        f"  ORB: {qqq_orb['low']} ↔ {qqq_orb['high']}\n\n"
        f"<b>SPY</b>  {spy['price']}  ({spy['pct']})\n"
        f"  ORB: {spy_orb['low']} ↔ {spy_orb['high']}\n\n"
        f"✅ Break above → <b>ATM CALL</b> on cleaner mover\n"
        f"✅ Break below → <b>ATM PUT</b>\n"
        f"❌ Choppy / inside range → <b>PASS</b>\n\n"
        f"<i>Stop at -50% immediately. Target +100%. Stop orders open 8:45 AM CT.</i>"
    )


def hard_close() -> None:
    if not is_trading_day():
        return

    qqq = get_quote("QQQ")
    spy = get_quote("SPY")

    send(
        f"🔴 <b>HARD CLOSE — 2:30 PM CT</b>\n\n"
        f"<b>QQQ</b>  {qqq['price']}  {qqq['pct']}\n"
        f"<b>SPY</b>  {spy['price']}  {spy['pct']}\n\n"
        f"<b>EXIT ALL POSITIONS NOW. No exceptions.</b>\n\n"
        f"Reply with your result — /win, /loss, or /pass"
    )


def screener_alert() -> None:
    """8:20 AM CT Tue/Thu — Unusual options scan, no ORB trade."""
    day = datetime.now(CT).strftime("%A %b %-d")
    qqq = get_quote("QQQ", premarket=True)
    spy = get_quote("SPY", premarket=True)

    send(
        f"🔍 <b>Unusual Options Scan — {day}</b>\n\n"
        f"<b>QQQ</b>  {qqq['price']}   {qqq['pct']}\n"
        f"<b>SPY</b>  {spy['price']}   {spy['pct']}\n\n"
        f"📊 Open Robinhood → Screeners → <i>High options volume &amp; IV</i>\n\n"
        f"<b>What to look for:</b>\n"
        f"• High relative options volume (unusual activity, not normal flow)\n"
        f"• IV spike — someone's positioning for a big move\n"
        f"• Stock NOT already up 15%+ today — catch the move, don't chase it\n"
        f"• Low-premium contract that fits the budget\n\n"
        f"<b>Today is Tue/Thu — no ORB trade.</b>\n"
        f"Pure screener day. If a setup looks clean and fresh, flag it as a watchlist "
        f"item for the next ORB session. No FOMO — pass if it's extended."
    )


# ── Message handler ────────────────────────────────────────────────────────────

def handle_message(text: str) -> None:
    t = text.strip()
    tl = t.lower()

    # /help or /start
    if tl in ("/start", "/help", "help"):
        send(
            "🤖 <b>ORB Bot — Commands</b>\n\n"
            "<b>Quotes</b>\n"
            "  QQQ · SPY · AAPL (any ticker) — instant price\n\n"
            "<b>Trade day</b>\n"
            "  /brief — run morning briefing now\n"
            "  /trade — log entry + get stop reminder\n"
            "  /win 200 — log a win ($200)\n"
            "  /loss 80 — log a loss ($80)\n"
            "  /pass — log no-trade\n\n"
            "<b>Scheduled alerts fire Mon/Wed/Fri at:</b>\n"
            "  8:20 AM · 8:35 AM · 8:42 AM · 2:30 PM (CT)"
        )
        return

    # /brief — force morning briefing
    if tl == "/brief":
        morning_briefing(force=True)
        return

    # /trade — entry acknowledgement
    if tl.startswith("/trade") or "entered" in tl:
        send(
            "✅ <b>Trade logged.</b>\n\n"
            "Reminders:\n"
            "• Set stop at -50% once orders open (8:45 AM CT)\n"
            "• Target +100%\n"
            "• Hard close at 2:30 PM CT — no exceptions\n\n"
            "Good luck 📈"
        )
        return

    # /win <amount>
    if tl.startswith("/win"):
        parts = t.split()
        amount = parts[1].lstrip("$+") if len(parts) > 1 else "?"
        send(
            f"💚 <b>Win logged: +${amount}</b>\n\n"
            f"Clean execution. Bank it and move on — next session Wednesday."
        )
        return

    # /loss <amount>
    if tl.startswith("/loss"):
        parts = t.split()
        amount = parts[1].lstrip("$-") if len(parts) > 1 else "?"
        send(
            f"🔴 <b>Loss logged: -${amount}</b>\n\n"
            f"Did you follow the rules?\n"
            f"If yes — that's a good trade. The process is right, outcome isn't always.\n"
            f"If no — what broke down? Note it and fix it Wednesday."
        )
        return

    # /pass or no trade
    if tl in ("/pass", "pass", "no trade", "no setup"):
        send(
            "⏭ <b>Pass logged.</b>\n\n"
            "No trade is a trade. Protecting capital when setup isn't clean "
            "is exactly the discipline that keeps the account healthy."
        )
        return

    # Try it as a ticker (1–5 uppercase letters)
    ticker_candidate = t.upper().strip().lstrip("/")
    if ticker_candidate.isalpha() and 1 <= len(ticker_candidate) <= 5:
        quote = get_quote(ticker_candidate)
        if quote["price"] != "N/A":
            send(f"📊 <b>{ticker_candidate}</b>   {quote['price']}   {quote['pct']}")
        else:
            send(f"❓ Couldn't fetch data for <b>{ticker_candidate}</b>. Check the symbol and try again.")
        return

    # Fallback — acknowledge note
    send(f"📝 Noted: \"{t}\"")


# ── Message polling loop ───────────────────────────────────────────────────────

def poll() -> None:
    """Long-poll Telegram for incoming messages."""
    offset = None
    print(f"[{now_ct()}] Polling for messages...")

    while True:
        try:
            params: dict = {"timeout": 30, "allowed_updates": ["message"]}
            if offset is not None:
                params["offset"] = offset

            r = requests.get(
                f"https://api.telegram.org/bot{TOKEN}/getUpdates",
                params=params,
                timeout=35,
            )
            data = r.json()

            if data.get("ok"):
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    msg    = update.get("message", {})
                    text   = msg.get("text", "").strip()
                    if text:
                        print(f"[{now_ct()}] Received: {text}")
                        handle_message(text)

        except Exception as e:
            print(f"[{now_ct()}] Poll error: {e}")
            time.sleep(5)


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    scheduler = BackgroundScheduler(timezone="America/Chicago")

    # Mon/Wed/Fri — ORB + screener
    scheduler.add_job(morning_briefing, "cron", day_of_week="mon,wed,fri", hour=8,  minute=20)
    scheduler.add_job(range_lock,       "cron", day_of_week="mon,wed,fri", hour=8,  minute=35)
    scheduler.add_job(breakout_check,   "cron", day_of_week="mon,wed,fri", hour=8,  minute=42)
    scheduler.add_job(hard_close,       "cron", day_of_week="mon,wed,fri", hour=14, minute=30)

    # Tue/Thu — screener only, no ORB
    scheduler.add_job(screener_alert,   "cron", day_of_week="tue,thu",     hour=8,  minute=20)

    scheduler.start()
    print(f"[{now_ct()}] Scheduler started.")

    send(
        "🤖 <b>ORB Trading Bot is online!</b>\n\n"
        "<b>Mon / Wed / Fri (ORB days):</b>\n"
        "  8:20 AM  Morning brief\n"
        "  8:35 AM  Opening range locked\n"
        "  8:42 AM  Breakout check\n"
        "  2:30 PM  Hard close\n\n"
        "<b>Tue / Thu (screener days):</b>\n"
        "  8:20 AM  Unusual options scan alert\n\n"
        "Send /help to see what I respond to.\n\n"
        "Good trading, Ravi 📈"
    )

    # Blocking poll loop (main thread)
    poll()
