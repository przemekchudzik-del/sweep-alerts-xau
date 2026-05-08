"""
Sweep+Continuation Alert Bot — multi-instrument na timeframe 1h.

Wspierane: XAUUSD, BTCUSD (rozszerzalne).

Logika identyczna jak wcześniej:
1. Pobiera świece 1h dla każdego instrumentu z listy.
2. Liczy zakres prev 24h (od poprzedniej 00:00 UTC do dziś 00:00 UTC).
3. Sprawdza sweep w sesji azjatyckiej (00–06 UTC).
4. O 07:00 UTC wysyła alert na Telegram, jeśli był sweep ≥ progu.
5. Każdy instrument ma własny próg sweepu zgodnie z backtestem.

Zmienne środowiskowe:
  TWELVE_DATA_API_KEY  — klucz z twelvedata.com
  TELEGRAM_BOT_TOKEN   — token bota
  TELEGRAM_CHAT_ID     — chat ID

Opcjonalne:
  TEST_MODE=1  — wymusi alert dla każdego instrumentu (diagnostyka)
  FORCE_HOUR=N — udaje godzinę N UTC
"""

import os
import sys
import requests
from datetime import datetime, timezone, timedelta

# === LISTA INSTRUMENTÓW ===
INSTRUMENTS = [
    {
        "name": "XAUUSD",
        "twelve_symbol": "XAU/USD",
        "min_sweep_pct": 0.0015,   # 0.15% z backtestu
        "price_decimals": 2,
        "unit_label": "USD/oz",
    },
    {
        "name": "BTCUSD",
        "twelve_symbol": "BTC/USD",
        "min_sweep_pct": 0.0020,   # 0.20% z backtestu
        "price_decimals": 1,
        "unit_label": "USD",
    },
]

# Wspólne parametry
INTERVAL = "1h"
TP_MULT = 0.25
SIGNAL_HOUR_START = 7
SIGNAL_HOUR_END = 10
ASIAN_HOUR_START = 0
ASIAN_HOUR_END = 6
LOOKBACK_BARS = 48


def env(name, required=True, default=None):
    val = os.environ.get(name, default)
    if required and not val:
        print(f"ERROR: missing env var {name}", file=sys.stderr)
        sys.exit(1)
    return val


def fetch_candles(api_key, twelve_symbol, n=LOOKBACK_BARS):
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": twelve_symbol,
        "interval": INTERVAL,
        "outputsize": n,
        "apikey": api_key,
        "timezone": "UTC",
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    if data.get("status") == "error":
        raise RuntimeError(f"Twelve Data error ({twelve_symbol}): {data.get('message')}")
    values = data.get("values", [])
    if not values:
        raise RuntimeError(f"Twelve Data zwrocila pusta liste swiec ({twelve_symbol})")

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


def detect_sweep(candles, now_utc, min_sweep_pct):
    today = now_utc.date()
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

    sweep_up_max = None
    sweep_dn_min = None
    for c in asian_candles:
        if c["high"] > prev_high:
            ext = (c["high"] - prev_high) / prev_high
            if ext >= min_sweep_pct:
                if sweep_up_max is None or c["high"] > sweep_up_max:
                    sweep_up_max = c["high"]
        if c["low"] < prev_low:
            ext = (prev_low - c["low"]) / prev_low
            if ext >= min_sweep_pct:
                if sweep_dn_min is None or c["low"] < sweep_dn_min:
                    sweep_dn_min = c["low"]

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
    return None


def build_trade_plan(sweep, current_price):
    prev_range = sweep["prev_high"] - sweep["prev_low"]
    if sweep["type"] == "UP":
        direction = "LONG"
        # Wariant C: SL = entry - 1.5 * sweep_strength
        sweep_strength = sweep["asian_extreme"] - sweep["prev_high"]
        sl = current_price - 1.5 * sweep_strength
        tp = sweep["asian_extreme"] + TP_MULT * prev_range
        risk = current_price - sl
        reward = tp - current_price
    else:
        direction = "SHORT"
        sweep_strength = sweep["prev_low"] - sweep["asian_extreme"]
        sl = current_price + 1.5 * sweep_strength
        tp = sweep["asian_extreme"] - TP_MULT * prev_range
        risk = sl - current_price
        reward = current_price - tp

    rr = reward / risk if risk > 0 else 0
    return {
        "direction": direction,
        "entry": current_price,
        "sl": sl,
        "tp": tp,
        "risk_per_unit": risk,
        "reward_per_unit": reward,
        "rr": rr,
    }

    rr = reward / risk if risk > 0 else 0
    return {
        "direction": direction,
        "entry": current_price,
        "sl": sl,
        "tp": tp,
        "risk_per_unit": risk,
        "reward_per_unit": reward,
        "rr": rr,
    }


def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(url, data={
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }, timeout=15)
    if r.status_code != 200:
        print(f"Telegram ERROR: {r.status_code} {r.text}", file=sys.stderr)
        return False
    return True


def format_alert(inst, sweep, plan, current_price, now_utc):
    arrow = "📈" if sweep["type"] == "UP" else "📉"
    prev_label = "high" if sweep["type"] == "UP" else "low"
    dec = inst["price_decimals"]
    fmt = f"{{:.{dec}f}}"
    return f"""🔔 SWEEP ALERT — {inst["name"]}

{arrow} Sweep {sweep["type"]} w sesji azjatyckiej
Asian extreme: {fmt.format(sweep["asian_extreme"])}
Sweep o {sweep["extension_pct"]:.2f}% ponad prev_{prev_label}

📊 Setup {plan["direction"]} (London open)
Entry (current price): {fmt.format(plan["entry"])}
SL: {fmt.format(plan["sl"])}  (-{fmt.format(plan["risk_per_unit"])} {inst["unit_label"]})
TP: {fmt.format(plan["tp"])}  (+{fmt.format(plan["reward_per_unit"])} {inst["unit_label"]})
R:R: {plan["rr"]:.2f} : 1

📐 Konteksty
prev_high: {fmt.format(sweep["prev_high"])}
prev_low:  {fmt.format(sweep["prev_low"])}
prev_range: {fmt.format(sweep["prev_high"] - sweep["prev_low"])} {inst["unit_label"]}

⏰ Max hold: 48h od wejścia
🕐 Czas alertu: {now_utc.strftime("%Y-%m-%d %H:%M UTC")}

To jest sygnał z mechanicznego setupu — zweryfikuj kontekst zanim wejdziesz."""


def format_no_signal(inst, sweep_info, now_utc):
    if sweep_info is None:
        body = "Brak sweepu w sesji azjatyckiej (cena pozostała w prev_24h range)."
    elif sweep_info.get("both_sides"):
        body = "Sweep w OBIE strony (niejednoznaczny dzień, sygnał pominięty)."
    elif sweep_info.get("error"):
        body = f"Brak danych: {sweep_info['error']}"
    else:
        body = "Nieznany stan."
    return f"Test {inst['name']} — {now_utc.strftime('%Y-%m-%d %H:%M UTC')}\n\n{body}"


def process_instrument(inst, api_key, tg_token, tg_chat, now_utc, test_mode):
    """Przetwarza jeden instrument. Zwraca True jeśli wszystko OK."""
    print(f"\n--- {inst['name']} ({inst['twelve_symbol']}) ---")
    try:
        candles = fetch_candles(api_key, inst["twelve_symbol"])
        print(f"  Pobrano {len(candles)} swiec, ostatnia: {candles[-1]['dt']}")
    except Exception as e:
        msg = f"⚠️ {inst['name']}: błąd pobierania danych: {e}"
        send_telegram(tg_token, tg_chat, msg)
        return False

    sweep = detect_sweep(candles, now_utc, inst["min_sweep_pct"])

    if test_mode:
        if sweep and "type" in sweep:
            current = candles[-1]["close"]
            plan = build_trade_plan(sweep, current)
            msg = "🧪 TEST MODE — sygnał wykryty\n\n" + format_alert(inst, sweep, plan, current, now_utc)
        else:
            msg = "🧪 TEST MODE\n\n" + format_no_signal(inst, sweep, now_utc)
        send_telegram(tg_token, tg_chat, msg)
        print(f"  Test alert wyslany")
        return True

  if not sweep or "type" not in sweep:
        print(f"  Brak sweepu: {sweep}")
        return True

    if now_utc.hour != SIGNAL_HOUR_START:
        print(f"  Sweep wykryty, ale godzina ({now_utc.hour}) nie jest 07:00 UTC. Pomijam.")
        return True

    current = candles[-1]["close"]
    plan = build_trade_plan(sweep, current)

    # Sanity check: jeśli R:R poniżej 0.3, cena już odpłynęła - nie handluj
    if plan["rr"] < 0.3:
        print(f"  Sweep wykryty, ale R:R={plan['rr']:.2f} - cena za daleko od entry, pomijam.")
        return True

    # Sanity check: czy cena jest sensownie blisko entry (nie przeleciała już w stronę TP)
    if sweep["type"] == "UP":
        # Cena nie może być już bliżej TP niż entry
        progress_to_tp = (current - sweep["asian_extreme"]) / (plan["tp"] - sweep["asian_extreme"]) if plan["tp"] != sweep["asian_extreme"] else 0
    else:
        progress_to_tp = (sweep["asian_extreme"] - current) / (sweep["asian_extreme"] - plan["tp"]) if plan["tp"] != sweep["asian_extreme"] else 0

    if progress_to_tp > 0.3:  # cena już zrobiła >30% drogi do TP
        print(f"  Cena zaszła już {progress_to_tp*100:.0f}% drogi do TP - za późno, pomijam.")
        return True

    msg = format_alert(inst, sweep, plan, current, now_utc)
    if send_telegram(tg_token, tg_chat, msg):
        print(f"  Alert {inst['name']} wyslany")
        return True
    return False


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
    print(f"Instruments: {[i['name'] for i in INSTRUMENTS]}")

    if not test_mode and not (SIGNAL_HOUR_START <= now_utc.hour <= SIGNAL_HOUR_END):
        print(f"Poza oknem sygnału ({SIGNAL_HOUR_START}-{SIGNAL_HOUR_END} UTC), kończę")
        return 0

    all_ok = True
    for inst in INSTRUMENTS:
        ok = process_instrument(inst, api_key, tg_token, tg_chat, now_utc, test_mode)
        all_ok = all_ok and ok

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
