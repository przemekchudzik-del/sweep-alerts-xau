# Sweep+Continuation Alert Bot — XAUUSD 1h

Mechaniczny detektor sygnałów Sweep+Continuation na złocie. Sprawdza co godzinę
warunki setupu i wysyła alert na Telegram, gdy o 07:00 UTC po sweepie sesji
azjatyckiej rynek otwiera London z aktywnym sygnałem.

**Setup źródłowy:** dokument `metodologia_btc_v3_1_z_przykladami.pdf`,
sekcja 3 (Sweep+Continuation), parametry XAU.

---

## Co robi skrypt

1. Co godzinę (cron GitHub Actions) pobiera świece 1h XAU/USD z Twelve Data.
2. Liczy `prev_24h_high` i `prev_24h_low` z poprzedniego dnia (00:00–24:00 UTC).
3. Sprawdza czy w sesji azjatyckiej (00:00–06:00 UTC dziś) doszło do sweepu
   ≥ 0.15% ponad poprzednie ekstremum.
4. Tylko o **07:00 UTC** (pierwsza godzina po sesji azjatyckiej) wysyła alert
   na Telegram z propozycją zlecenia (entry, SL, TP, R:R).
5. W innych godzinach kończy bez akcji — żeby nie spamować i nie liczyć
   wielokrotnie tego samego dnia.

**Skrypt NIE otwiera pozycji.** To jest alerting, nie auto-trading.
Zlecenie składasz ręcznie u brokera po otrzymaniu alertu.

---

## Wdrożenie krok po kroku

### Krok 1 — utwórz repo GitHub (5 min)

1. Wejdź na [github.com](https://github.com), zaloguj się
2. Kliknij **New repository**
3. Nazwa np. `sweep-alerts-xau` (lub inna)
4. **Private repository** — (rekomendowane, choć kod nie zawiera sekretów)
5. Nie inicjalizuj README ani .gitignore (zaraz wgramy własne pliki)
6. Kliknij **Create repository**

### Krok 2 — wgraj pliki (5 min)

Skopiuj cztery pliki do swojego repo:

```
sweep-alerts-xau/
├── sweep_alerts.py
├── .github/
│   └── workflows/
│       └── sweep-alerts.yml
├── README.md       ← ten plik
└── .gitignore      ← (opcjonalnie, dobry zwyczaj)
```

Możesz to zrobić przez:
- **GitHub web UI** — Add file → Upload files → przeciągnij wszystkie pliki
- albo **git clone + push** jeśli umiesz

### Krok 3 — zarejestruj się na Twelve Data i pobierz klucz API (3 min)

1. Wejdź na [twelvedata.com](https://twelvedata.com)
2. **Sign up** — email + hasło
3. Po zalogowaniu **Dashboard** → znajdź **API key** (długi ciąg liter/cyfr)
4. Skopiuj go — będzie potrzebny w kroku 5

Free tier: 800 zapytań / dzień, 8 / minutę. Skrypt zużywa ~24/dzień (raz
na godzinę), więc z ogromnym zapasem.

### Krok 4 — wygeneruj nowy token Telegram (jeśli jeszcze nie zrobione)

1. W Telegramie otwórz `@BotFather`, wpisz `/mybots`
2. Wybierz swojego bota → **API Token** → **Revoke current token**
3. Skopiuj nowy token (stary uznaj za spalony)

Zacznij też **chat z Twoim botem na Telegramie** — wyślij `/start` lub jakąkolwiek
wiadomość. Bot musi "wiedzieć" że istniejesz, inaczej nie może wysyłać Ci
wiadomości.

### Krok 5 — dodaj sekrety do GitHub Actions

W swoim repo na GitHub:

1. **Settings** (zakładka u góry repo)
2. **Secrets and variables** → **Actions**
3. Kliknij **New repository secret** trzy razy:

| Nazwa sekretu | Wartość |
|---|---|
| `TWELVE_DATA_API_KEY` | klucz z Twelve Data (krok 3) |
| `TELEGRAM_BOT_TOKEN`  | nowy token z BotFather (krok 4) |
| `TELEGRAM_CHAT_ID`    | `1228596808` (twoje chat ID) |

Sekrety są zaszyfrowane i niewidoczne w logach. Nawet Ty sam nie zobaczysz
ich po zapisaniu (możesz je tylko nadpisać).

### Krok 6 — włącz GitHub Actions

1. W repo wejdź w zakładkę **Actions**
2. Jeśli pojawi się komunikat "Workflows aren't being run on this repository"
   → kliknij **I understand my workflows, go ahead and enable them**
3. Z lewej strony powinno być **Sweep Alerts XAUUSD** — kliknij

### Krok 7 — wyślij testowy alert (3 min)

W zakładce Actions, w Sweep Alerts XAUUSD:

1. Kliknij **Run workflow** (po prawej stronie)
2. **Test mode** → wpisz `true`
3. **Force hour UTC** → zostaw puste (lub wpisz `7` żeby symulować 07:00 UTC)
4. Kliknij zielony **Run workflow**

Po ~30 sekundach powinieneś dostać wiadomość na Telegram. Może to być:
- ✅ `TEST MODE — sygnał wykryty` z poziomami trade'u (jeśli akurat dziś był sweep)
- ✅ `TEST MODE — Brak sweepu...` (jeśli dziś nie było sweepu)
- ❌ `Błąd pobierania danych...` (jeśli klucz API nieprawidłowy)

Jeśli nic nie dostałeś:
- Sprawdź logi w **Actions** → wybierz uruchomienie → kliknij job
- Najczęstszy błąd: **chat z botem nie jest zainicjowany** — wyślij botowi
  `/start` na Telegramie i spróbuj jeszcze raz.

### Krok 8 — gotowe

Cron uruchomi się automatycznie co godzinę. Będziesz dostawać alert tylko
o 07:00 UTC (= 09:00 CEST latem, 08:00 CET zimą), kiedy mechaniczny setup
faktycznie się aktywuje.

Statystycznie ~70 alertów / rok = średnio 1 co ~5 dni.

---

## Format alertu

```
🔔 SWEEP ALERT — XAUUSD

📈 Sweep UP w sesji azjatyckiej
Asian extreme: 4087.20
Sweep o 1.27% ponad prev_high

📊 Setup LONG (London open)
Entry (current price): 4083.60
SL: 3981.60  (-102.00 USD/oz)
TP: 4100.75  (+17.15 USD/oz)
R:R: 0.17 : 1

📐 Konteksty
prev_high: 4035.80
prev_low:  3981.60
prev_range: 54.20 USD

⏰ Max hold: 48h od wejścia
🕐 Czas alertu: 2025-11-10 07:00 UTC
```

---

## Twoja rola po otrzymaniu alertu

1. **Otwórz wykres XAUUSD 1h** u brokera. Zweryfikuj że wskazane poziomy
   wyglądają sensownie — czasem feed danych Twelve Data odbiega od brokera
   o kilka tickerów.
2. **Zdecyduj sizing** — ile USD chcesz ryzykować. Ryzyko per trade
   wskazane jest jako "USD/oz" — pomnóż przez liczbę uncji w pozycji.
3. **Złóż zlecenie** market lub limit na cenie wskazanej jako Entry,
   z SL i TP zgodnie z alertem.
4. **Nie ruszaj poziomów** w trakcie trade'u. Max hold 48h.
5. **Zapisz w dzienniku** — data, kierunek, parametry, wynik, czas trwania.

Po 30+ trade'ach porównaj realne wyniki z backtestem (sekcja 7.4 PDF).

---

## Zatrzymanie / wstrzymanie

- **Tymczasowo:** w Actions wyłącz workflow (settings → disable workflow)
- **Stałe:** usuń plik `.github/workflows/sweep-alerts.yml`
- **Zatrzymanie alertów ale skrypt działa:** wyłącz cron przez zmianę
  `cron: '5 * * * *'` na `cron: '5 25 13 1 *'` (raz w roku 25 stycznia)

---

## Co jeśli coś przestanie działać

**Najczęstsze problemy:**

| Objaw | Przyczyna | Naprawa |
|---|---|---|
| Brak alertów wcale | Cron nie działa po 60 dniach bezczynności repo | Otwórz repo → wykonaj jakikolwiek commit |
| `Błąd pobierania danych` | Limit Twelve Data wyczerpany | Sprawdź dashboard, ew. upgrade plan |
| Token Telegram nieautoryzowany | Token został revoked | Wygeneruj nowy w BotFather, zaktualizuj sekret |
| Alert wysyła błędne ceny | Świeca jeszcze nie zamknięta | Cron jest `5 * * * *` (5 min po godz.) — powinno być OK |

**Logi:** wszystko widoczne w GitHub Actions → wybierz uruchomienie → Job →
"Run sweep detection" → rozwiń.

---

## Zmiana parametrów

Wszystkie parametry na początku `sweep_alerts.py`:

```python
SYMBOL = "XAU/USD"
MIN_SWEEP_PCT = 0.0015     # 0.15% — z backtestu dla XAU
TP_MULT = 0.25             # TP = asian_ext + 0.25 * prev_range
SIGNAL_HOUR_START = 7      # godzina alertu (UTC)
SIGNAL_HOUR_END = 10       # górna granica okna sygnału
ASIAN_HOUR_START = 0
ASIAN_HOUR_END = 6
```

Po zmianie zrób commit/push, GitHub Actions automatycznie podchwyci nową wersję.

---

## Dodanie kolejnych instrumentów (gdy będziesz gotów)

Po 2-3 miesiącach paper tradingu na samym XAU, gdy będziesz wiedział że setup
działa real-time, możesz dodać EUR/XAG/BTC. Modyfikacje:

1. W `sweep_alerts.py` dodaj listę instrumentów z parametrami
2. Pętla po liście — pobierz dane, wykryj sweep, wyślij alerty osobno
3. Każdy instrument ma własny `MIN_SWEEP_PCT` (patrz tabela 6 w PDF)

Mogę napisać tę wersję gdy będziesz gotów.
