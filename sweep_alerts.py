"""
Sweep+Continuation Alert Bot — XAUUSD na timeframe 1h.

Logika:
1. Pobiera świece 1h z Twelve Data (XAU/USD).
2. Liczy zakres poprzednich 24h (prev_high, prev_low).
3. Sprawdza czy w sesji azjatyckiej (00–06 UTC) doszło do sweepu (>= 0.15%).
4. Jeśli aktualna godzina to 07:00 UTC i sweep miał miejsce — wysyła alert na Telegram
   z propozycją wejścia (entry, SL, TP, R:R).

Zmienne środowiskowe wymagane:
  TWELVE_DATA_API_KEY  — klucz z twelvedata.com
  TELEGRAM_BOT_TOKEN   — token bota z @BotFather
  TELEGRAM_CHAT_ID     — twoje chat ID

Opcjonalne:
  TEST_MODE=1          — wyśle testowy alert niezależnie od warunków
  FORCE_HOUR=7         — udaje że jest dana godzina UTC (do testów)
"""

import os
import sys
import json
import requests
from datetime import datetime, timezone, timedelta

# === KONFIG ===
SYMBOL = "XAU/USD"
SYMBOL_DISPLAY = "XAUUSD"
INTERVAL = "1h"
MIN_SWEEP_PCT = 0.0015   # 0.15% (z naszego backtestu dla XAU)
TP_MULT = 0.25           # TP = asian_ext + 0.25 * prev_range
SIGNAL_HOUR_START = 7
SIGNAL_HOUR_END = 10
ASIAN_HOUR_START = 0
ASIAN_HOUR_END = 6
LOOKBACK_BARS = 48       # bezpieczny zapas: 24h prev + 6h Asia + 1h sygnal + bufor


def env(name, required=True, default=None):
    val = os.environ.get(name, default)
    if required and not val:
        print(f"ERROR: missing env var {name}", file=sys.stderr)
        sys.exit(1)
    return val


def fetch_candles(api_key, symbol=SYMBOL, interval=INTERVAL, n=LOOKBACK_BARS):
    """Pobiera ostatnie n świec z Twelve Data."""
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": n,
        "apikey": api_key,
        "timezone": "UTC",
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    if data.get("status") == "error":
        raise RuntimeError(f"Twelve Data error: {data.get('message')}")
    values = data.get("values", [])
    if not values:
        raise RuntimeError("Twelve Data zwrocila pusta liste swiec")

    # Twelve Data zwraca od najnowszych do najstarszych — odwracamy
    candles = []
    for v in reversed(values):
        candles.append({
            "dt": datetime.strptime(v["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc),
            "open": float(v["open"]),
            "high": float(v["high"]),
            "low": float(v["low"]),
            "close": float(v["close"]),
        })
    return candles


def detect_sweep(candles, now_utc):
    """Zwraca dict opisujacy sweep w obecnym dniu (UTC) albo None."""
    today = now_utc.date()

    # Filtruj: poprzedni dzień (24h przed dzisiejszą 00:00 UTC) i sesja azjatycka dziś
    yesterday = today - timedelta(days=1)
    prev_24h_candles = [c for c in candles if c["dt"].date() == yesterday]
    asian_candles = [
        c for c in candles
        if c["dt"].date() == today
        and ASIAN_HOUR_START <= c["dt"].hour <= ASIAN_HOUR_END
    ]

    if len(prev_24h_candles) < 12:
        return {"error": f"za malo swiec prev_24h ({len(prev_24h_candles)})"}
    if len(asian_candles) < 4:
        return {"error": f"za malo swiec sesji azjatyckiej ({len(asian_candles)})"}

    prev_high = max(c["high"] for c in prev_24h_candles)
    prev_low = min(c["low"] for c in prev_24h_candles)

    # Szukamy najmocniejszego sweepu w sesji azjatyckiej
    sweep_up_max = None
    sweep_dn_min = None
    for c in asian_candles:
        if c["high"] > prev_high:
            ext = (c["high"] - prev_high) / prev_high
            if ext >= MIN_SWEEP_PCT:
                if sweep_up_max is None or c["high"] > sweep_up_max:
                    sweep_up_max = c["high"]
        if c["low"] < prev_low:
            ext = (prev_low - c["low"]) / prev_low
            if ext >= MIN_SWEEP_PCT:
                if sweep_dn_min is None or c["low"] < sweep_dn_min:
                    sweep_dn_min = c["low"]

    # Jezeli sweepy w obie strony — odrzucamy (niejednoznaczny dzien)
    if sweep_up_max is not None and sweep_dn_min is not None:
        return {"both_sides": True, "prev_high": prev_high, "prev_low": prev_low}

    if sweep_up_max:
        return {
            "type": "UP",
            "asian_extreme": sweep_up_max,
            "prev_high": prev_high,
            "prev_low": prev_low,
            "extension_pct": (sweep_up_max - prev_high) / prev_high * 100,
        }
    if sweep_dn_min:
        return {
            "type": "DOWN",
            "asian_extreme": sweep_dn_min,
            "prev_high": prev_high,
            "prev_low": prev_low,
            "extension_pct": (prev_low - sweep_dn_min) / prev_low * 100,
        }
    return None  # brak sweepu


def build_trade_plan(sweep, current_price):
    """Liczy entry/SL/TP z parametrów sweepu."""
    prev_range = sweep["prev_high"] - sweep["prev_low"]
    if sweep["type"] == "UP":
        direction = "LONG"
        sl = sweep["prev_low"]
        tp = sweep["asian_extreme"] + TP_MULT * prev_range
        risk = current_price - sl
        reward = tp - current_price
    else:
        direction = "SHORT"
        sl = sweep["prev_high"]
        tp = sweep["asian_extreme"] - TP_MULT * prev_range
        risk = sl - current_price
        reward = current_price - tp

    rr = reward / risk if risk > 0 else 0
    return {
        "direction": direction,
        "entry": current_price,
        "sl": sl,
        "tp": tp,
        "risk_usd_per_oz": risk,
        "reward_usd_per_oz": reward,
        "rr": rr,
    }


def send_telegram(token, chat_id, text):
    """Wysyła wiadomość na Telegram."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(url, data={
        "chat_id": chat_id,
        "text": text,
       "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }, timeout=15)
    if r.status_code != 200:
        print(f"Telegram ERROR: {r.status_code} {r.text}", file=sys.stderr)
        return False
    return True


def format_alert(sweep, plan, current_price, now_utc):
    """Buduje treść wiadomości Markdown."""
    arrow = "📈" if sweep["type"] == "UP" else "📉"
    return f"""
🔔 *SWEEP ALERT — {SYMBOL_DISPLAY}*

{arrow} *Sweep {sweep["type"]}* w sesji azjatyckiej
Asian extreme: `{sweep["asian_extreme"]:.2f}`
Sweep o `{sweep["extension_pct"]:.2f}%` ponad prev_{("high" if sweep["type"]=="UP" else "low")}

📊 *Setup {plan["direction"]}* (London open)
Entry (current price): `{plan["entry"]:.2f}`
SL: `{plan["sl"]:.2f}`  (-{plan["risk_usd_per_oz"]:.2f} USD/oz)
TP: `{plan["tp"]:.2f}`  (+{plan["reward_usd_per_oz"]:.2f} USD/oz)
R:R: `{plan["rr"]:.2f} : 1`

📐 *Konteksty*
prev_high: `{sweep["prev_high"]:.2f}`
prev_low:  `{sweep["prev_low"]:.2f}`
prev_range: `{sweep["prev_high"] - sweep["prev_low"]:.2f}` USD

⏰ Max hold: 48h od wejścia
🕐 Czas alertu: {now_utc.strftime("%Y-%m-%d %H:%M UTC")}

_To jest sygnał z mechanicznego setupu — zweryfikuj kontekst rynkowy zanim wejdziesz._
""".strip()


def format_no_signal(sweep_info, now_utc):
    """Diagnostyczna wiadomość gdy brak sweepu (wysyłana tylko w trybie testowym)."""
    if sweep_info is None:
        body = "Brak sweepu w sesji azjatyckiej (cena pozostała w prev_24h range)."
    elif sweep_info.get("both_sides"):
        body = "Sweep w OBIE strony (niejednoznaczny dzień, sygnał pominięty)."
    elif sweep_info.get("error"):
        body = f"Brak danych: {sweep_info['error']}"
    else:
        body = "Nieznany stan."
    return f"_Test sweep alerts — {now_utc.strftime('%Y-%m-%d %H:%M UTC')}_\n\n{body}"


def main():
    api_key = env("TWELVE_DATA_API_KEY")
    tg_token = env("TELEGRAM_BOT_TOKEN")
    tg_chat = env("TELEGRAM_CHAT_ID")
    test_mode = os.environ.get("TEST_MODE") == "1"
    force_hour = os.environ.get("FORCE_HOUR")

    now_utc = datetime.now(timezone.utc)
    if force_hour:
        now_utc = now_utc.replace(hour=int(force_hour), minute=0, second=0, microsecond=0)

    print(f"[{now_utc.isoformat()}] start, hour={now_utc.hour}, test_mode={test_mode}")

    # Tylko w godzinach 07:00–10:00 UTC szukamy sygnału (chyba że TEST_MODE)
    if not test_mode and not (SIGNAL_HOUR_START <= now_utc.hour <= SIGNAL_HOUR_END):
        print(f"Poza oknem sygnału ({SIGNAL_HOUR_START}-{SIGNAL_HOUR_END} UTC), kończę")
        return 0

    # 1. Pobierz świeczki
    try:
        candles = fetch_candles(api_key)
        print(f"Pobrano {len(candles)} swiec, ostatnia: {candles[-1]['dt']}")
    except Exception as e:
        msg = f"⚠️ Błąd pobierania danych: `{e}`"
        send_telegram(tg_token, tg_chat, msg)
        return 1

    # 2. Wykryj sweep
    sweep = detect_sweep(candles, now_utc)

    # 3. Tryb testowy — wyślij info bez względu na rezultat
    if test_mode:
        if sweep and "type" in sweep:
            current = candles[-1]["close"]
            plan = build_trade_plan(sweep, current)
            msg = "🧪 *TEST MODE — sygnał wykryty*\n\n" + format_alert(sweep, plan, current, now_utc)
        else:
            msg = "🧪 *TEST MODE*\n\n" + format_no_signal(sweep, now_utc)
        send_telegram(tg_token, tg_chat, msg)
        print("Test alert wyslany")
        return 0

    # 4. Tryb normalny — alert tylko gdy sweep istnieje
    if not sweep or "type" not in sweep:
        print(f"Brak sweepu: {sweep}")
        return 0

    # Wysyłamy alert TYLKO w pierwszej godzinie okna (07:00 UTC)
    # — żeby nie spamować przez 4h jeśli skrypt odpala się co godzinę
    if now_utc.hour != SIGNAL_HOUR_START:
        print(f"Sweep wykryty, ale godzina ({now_utc.hour}) nie jest 07:00 UTC. Pomijam alert.")
        return 0

    current = candles[-1]["close"]
    plan = build_trade_plan(sweep, current)
    msg = format_alert(sweep, plan, current, now_utc)

    if send_telegram(tg_token, tg_chat, msg):
        print("Alert wyslany pomyslnie")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
