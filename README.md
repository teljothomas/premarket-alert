# Pre-Market Alert (NSE)

## What it does

Every weekday at 08:45 IST a GitHub Actions workflow checks the signals that usually come before a gap-down open on NSE: GIFT Nifty, India VIX, FII/DII cash-market flows, and your own portfolio stocks. It grades the morning **GREEN / YELLOW / RED** and, for YELLOW or RED, sends you a WhatsApp message through CallMeBot before the 09:15 open. It never places trades. It only tells you what it saw, so you can decide yourself. Everything runs on free tiers.

## Architecture

```
  GitHub Actions  (cron "15 3 * * 1-5" = 08:45 IST, Mon–Fri; or manual run)
        │
        ▼
  python -m src.main ── skips Sat/Sun (IST)
        │
        ├─► fetch_gift_nifty ── Upstox market-quote API (GIFT Nifty)
        │                        └─ fallback: Yahoo Finance ^NSEI (Nifty 50 spot proxy)
        ├─► fetch_vix ───────── nsepython.indiavix()  +  nselib india_vix_data('1W')
        ├─► fetch_fii_dii ───── nselib fii_dii_trading_activity()
        └─► fetch_stocks ────── nsepython.nse_eq(symbol), 0.5 s apart
                                 └─ fallback: Yahoo Finance SYMBOL.NS
        │
        ▼   (a failed source returns None and is skipped, never fatal)
  evaluate_alert ──► GREEN | YELLOW | RED  + reasons
        │
        ▼
  format_message ──► None for GREEN, WhatsApp text otherwise
        │
        ▼
  send_whatsapp ──► CallMeBot API ──► your WhatsApp
        │
        ▼
  keep-alive step: commit last_run.txt (stops GitHub disabling the schedule)
```

### Grading rules

| Signal | Type | Default trigger |
|---|---|---|
| GIFT Nifty change | severe | ≤ −1.2 % |
| GIFT Nifty change | mild | between −1.2 % and −0.5 % |
| India VIX change | severe | ≥ +8 % |
| FII net cash flow | severe | < −₹1,000 Cr |
| Any portfolio stock | mild | < −1.5 % |

- **RED**: 2 or more severe signals.
- **YELLOW**: at least one signal, but not RED.
- **GREEN**: no signals. Nothing is sent.

Example RED message:

```
🔴 *MARKET ALERT — RED* (29-Sep-2026 08:45 IST)

📉 GIFT Nifty: 24,150 (-1.45%)
😨 India VIX: 14.2 (+11.3%)
🏦 FII Net: ₹-2,340 Cr
🏛️ DII Net: ₹1,900 Cr
📊 Portfolio (4 stocks): avg -0.9%

⚠️ *Signals detected:*
  • GIFT Nifty down 1.45% (severe)
  • India VIX spiked 11.3% to 14.2
  • Weak stocks: RELIANCE (-2.1%)

📋 *Suggested action:*
Consider reducing 30–50% exposure AFTER 9:30 AM
IF price stays below VWAP.
❌ Do NOT sell everything at 9:15 open.

_This is an alert, not financial advice._
```

## Setup checklist

### 1. Put the code on GitHub

Push this folder to a new GitHub repository (private or public). The workflow lives in `.github/workflows/premarket.yml` and needs no edits.

### 2. Get an Upstox Analytics Token (recommended)

The token lets the script read live GIFT Nifty. Without it, the script uses Yahoo Finance's Nifty 50 spot as a proxy. Before 09:15 that proxy only shows the previous session's move, so it is a much weaker signal.

1. Open an Upstox account if you don't have one. API access is free for account holders.
2. Sign in at <https://account.upstox.com/developer/apps>.
3. Open the **Analytics Token** section and click **Generate**. This token is read-only (market data only) and long-lived, so you don't need to log in every day.
4. Copy the token. You will store it as a GitHub secret in step 4.

API reference: <https://upstox.com/developer/api-documentation/>. Upstox changes its pages from time to time, so the labels above may differ slightly. If GIFT Nifty keeps falling back to Yahoo while a token is set, see the troubleshooting table.

### 3. Get a CallMeBot API key (free WhatsApp delivery)

1. Follow the steps at <https://www.callmebot.com/blog/free-api-whatsapp-messages/>.
2. Save the CallMeBot phone number shown on that page to your phone's contacts.
3. From WhatsApp, send that contact the activation message given on the page (`I allow callmebot to send me messages`).
4. You'll get a reply with your **API key**.
5. Your `CALLMEBOT_PHONE` is your own WhatsApp number in international format without spaces, e.g. `919876543210`. A leading `+` is optional; the script adds it.

### 4. Add GitHub secrets

In your repository, go to **Settings → Secrets and variables → Actions → Secrets → New repository secret** and add:

| Secret | Value |
|---|---|
| `UPSTOX_ANALYTICS_TOKEN` | token from step 2 (optional: leave it out to use the Yahoo proxy) |
| `CALLMEBOT_API_KEY` | key from step 3 |
| `CALLMEBOT_PHONE` | e.g. `919876543210` |

### 5. Customise `PORTFOLIO_STOCKS`

In the same page, open the **Variables** tab → **New repository variable**:

| Variable | Example |
|---|---|
| `PORTFOLIO_STOCKS` | `RELIANCE,TCS,HDFCBANK,INFY,SBIN` |

Use NSE trading symbols, separated by commas. Case and spaces don't matter. If the variable is missing or empty, the script uses `RELIANCE,TCS,HDFCBANK,INFY`. Each symbol takes about 1–2 s and the stock step is capped at 30 s, so keep the list to about 15 symbols. Symbols that don't fit in the time budget are skipped and logged.

### 6. Allow the workflow to push

The keep-alive step commits `last_run.txt`. The workflow requests `contents: write`. If your organisation or repository restricts this, go to **Settings → Actions → General → Workflow permissions** and choose **Read and write permissions**.

## How to test locally

```bash
cd premarket-alert
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                                   # then edit .env with your values
export $(grep -v '^#' .env | xargs)                    # load the variables into the shell

DRY_RUN=1 FORCE_RUN=1 python -m src.main               # safe: logs the message, sends nothing
python -m src.main                                     # real run: sends WhatsApp if YELLOW/RED

pytest tests/ -v                                       # unit tests, no network needed
```

**Windows PowerShell:** `export` doesn't exist there. Install python-dotenv instead; `src/main.py` loads `.env` automatically when it is available:

```powershell
pip install -r requirements.txt python-dotenv
Copy-Item .env.example .env        # then edit .env
$env:DRY_RUN = "1"; $env:FORCE_RUN = "1"; python -m src.main
```

Useful flags (environment variables):

| Variable | Effect |
|---|---|
| `DRY_RUN=1` | Log the message instead of sending it. CallMeBot variables aren't required. |
| `FORCE_RUN=1` | Run on Saturday/Sunday too. |
| `LOG_LEVEL=DEBUG` | Log raw API responses. |
| `GIFT_NIFTY_INSTRUMENT_KEY` | Override the Upstox instrument key (default `GLOBAL_INDEX\|SGX NIFTY`). |

On a GREEN morning, nothing is sent and the log says `No alert needed`. To see a sample message anyway, temporarily set `GIFT_NIFTY_MILD_THRESHOLD = 5` in `src/config.py` and run with `DRY_RUN=1`.

## How to trigger manually on GitHub

**Actions** tab → **Pre-Market Alert** → **Run workflow**. Two optional checkboxes are available:

- **dry_run**: prints the message in the job log instead of sending it.
- **force_run**: runs even on a weekend.

Open the run and expand **Run pre-market alert** to see the log. The last line starting with `SUMMARY` has the result:

```
SUMMARY 2026-09-29 08:45:12 IST | RED | gift=-1.45% | vix=+11.30% | sent=Y
```

## How to tune thresholds

All thresholds are constants at the top of [`src/config.py`](src/config.py):

```python
GIFT_NIFTY_MILD_THRESHOLD = -0.5      # percent
GIFT_NIFTY_SEVERE_THRESHOLD = -1.2    # percent
VIX_SPIKE_THRESHOLD = 8               # percent change
FII_SELLING_THRESHOLD = -1000         # crore rupees
STOCK_WEAK_THRESHOLD = -1.5           # percent
```

Edit them, run `pytest tests/ -v`, and push. The per-source time limits (`*_TIMEOUT_SECONDS`) and `NOTIFY_ON_DATA_FAILURE` are in the same file.

To change the schedule, edit the `cron` line in `.github/workflows/premarket.yml`. Cron times are in UTC: IST minus 5 h 30 min.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| No WhatsApp received | Check the `SUMMARY` line first. `GREEN … sent=N` means no alert was needed. `WhatsApp send failed` means `CALLMEBOT_API_KEY` or `CALLMEBOT_PHONE` is wrong (country code, no spaces) or the CallMeBot activation wasn't completed. Also make sure you didn't tick **dry_run**. |
| `GIFT Nifty fetch failed` / "falling back to Yahoo" | The script automatically falls back to Yahoo Finance ^NSEI, so the run still works. Check that `UPSTOX_ANALYTICS_TOKEN` is set and hasn't expired. If Upstox answers but returns no data, the default instrument key may not match Upstox's current instruments list. Find the GIFT Nifty key in the instruments file linked from the Upstox API docs and set it as a `GIFT_NIFTY_INSTRUMENT_KEY` repository variable. Also add `GIFT_NIFTY_INSTRUMENT_KEY: ${{ vars.GIFT_NIFTY_INSTRUMENT_KEY }}` to the workflow's `env:` block. |
| Workflow disabled after 60 days | GitHub disables schedules in repositories with no activity. The keep-alive step commits `last_run.txt` on every run to prevent this. If it was disabled anyway, open **Actions → Pre-Market Alert → Enable workflow**. |
| Keep-alive step fails with 403 | The workflow token can't push. See setup step 6. |
| India VIX / FII/DII / stock data "unavailable" | NSE often blocks cloud IP ranges, including GitHub's runners, and sometimes changes its API. The run continues with whatever data it got. Stocks fall back to Yahoo Finance. Missing sources are listed in the log. |
| `Yahoo Finance … 429 Too Many Requests` | Yahoo rate limit. The script retries on a second Yahoo host. Occasional misses are harmless; if it happens often, shorten `PORTFOLIO_STOCKS`. |
| Alert arrives after 09:15 | GitHub can start scheduled runs 5–30 min late under load. Move the cron earlier, e.g. `"0 3 * * 1-5"` (08:30 IST). |
| `Fatal configuration error` and exit code 1 | `CALLMEBOT_API_KEY` or `CALLMEBOT_PHONE` is missing. Add the secrets, or run with `DRY_RUN=1`. |
| Received "PRE-MARKET CHECK INCOMPLETE" | GIFT Nifty couldn't be fetched from any source and nothing else fired, so the day couldn't be graded. Check the market yourself. Set `NOTIFY_ON_DATA_FAILURE = False` in `src/config.py` to turn these off. |

## Assumptions and limitations

- **What 08:45 IST data means.** GIFT Nifty trades from 06:30 IST, so it is the only truly overnight signal. NSE's pre-open session runs 09:00–09:08, so at 08:45 India VIX, FII/DII (published the previous evening) and stock prices all describe the **previous session**. If the run is delayed past 09:08, stocks use today's pre-open price (IEP) when NSE provides it.
- **India VIX change.** The script compares the live VIX value against the one-week history from nselib. Before the open, the live value equals the last settled close, so the second-last row is used as the previous close, as specified. If the market is already trading, the last row is used instead.
- **FII/DII.** NSE publishes one row per category (`FII/FPI`, `DII`) for the latest session. The script merges both into one dict: `fii_net`, `dii_net`, buy/sell values and the date.
- **Holidays.** Only weekends are skipped. On an NSE holiday that falls on a weekday, the script runs on stale data. That is harmless, but you may get an alert.
- **Library exports.** nselib 2.5.x defines `fii_dii_trading_activity` but doesn't export it from `nselib.capital_market`, so the script imports it from the submodule when needed.
- **NSE quote API.** When this was written, NSE's `quote-equity` API behind `nsepython.nse_eq` answered 403 "Access Denied", so stock quotes came from the Yahoo Finance fallback. The script tries NSE first and stops calling it for the rest of a run after the first empty response.
- **Upstox instrument key.** `GLOBAL_INDEX|SGX NIFTY` comes from the project brief and could not be verified without a token. It is configurable (see troubleshooting). The v2 LTP endpoint returns only the last price, so the script derives the previous close from the full-quote endpoint's `net_change`.
- **Time budget.** Each source runs under a hard time limit (GIFT 20 s, VIX 15 s, FII 10 s, stocks 30 s, send 10 s), so a run finishes in under 90 s even if NSE hangs. A local run with real data took about 12 s.
- **Stateless.** Nothing is read from disk between runs. `last_run.txt` is written only by the workflow, for keep-alive.

### Differences from the original brief

- Added `src/utils.py` for shared parsing and timeout helpers, and an empty `tests/__init__.py` so `pytest tests/` can import `src` without extra configuration.
- `UPSTOX_ANALYTICS_TOKEN` is optional (a warning, not a fatal error) because the Yahoo fallback exists. Only the CallMeBot variables are required, and only when not in `DRY_RUN`.
- Stocks fall back to Yahoo Finance `SYMBOL.NS` because NSE's quote API was blocked.
- A short "check incomplete" notice is sent when the primary signal is missing from every source and nothing else fired, so a data outage is never silently reported as GREEN.
- Extra optional inputs: `DRY_RUN`, `FORCE_RUN`, `LOG_LEVEL`, `GIFT_NIFTY_INSTRUMENT_KEY`, and matching workflow_dispatch checkboxes.
- `last_run.txt` stays in `.gitignore` as specified, so the workflow commits it with `git add -f`.

## Costs

**₹0.** GitHub Actions (about 1 minute per weekday, well within the free tier), the Upstox Analytics Token, Yahoo Finance, NSE data and CallMeBot are all free.

## Disclaimer

This project is for personal information only and is **not financial advice**. Market data from unofficial or free sources can be delayed, incomplete or wrong, and the grading rules are simple heuristics. The script never trades. Every decision, and its consequences, is yours. Check prices in your broker's app before acting.
