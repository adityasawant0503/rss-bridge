---
name: ict-india
description: >-
  ICT 2022 Mentorship model (MMXM) adapted to the Indian index market: Nifty, Bank Nifty and Sensex
  (futures or index options on NSE/BSE). Built from the user's own mentorship notes and live journal.
  Marks the liquidity (previous day high/low, the 09:15-09:30 opening range, session highs/lows,
  equal highs/lows), helps commit a written daily bias, then watches the AM (09:30-11:00 IST) and PM
  (13:15-14:45 IST) windows for the sequence: run on liquidity -> market structure shift with
  displacement -> fair value gap -> retrace into the FVG -> two confirmation candles. Sizes in lots
  (futures, or options via delta), manages with the 50%/75% stop rule, enforces the rules from the
  notes and journal (2 trades a day, no adding to a loser, no repeat entries at the same level, don't
  wait for expiry, don't trade for others), backtests the model and keeps the live journal. Use when
  the user says "ICT", "MMXM", "2022 model", "killzone", "FVG", "liquidity sweep", "MSS", "Bank Nifty
  setup", "Nifty setup", "Sensex setup", "check banknifty", "daily bias", "lots for this trade",
  "journal this trade", or asks to backtest ICT on Indian indices.
argument-hint: "[levels|bias|check|watch|backtest|size|gate|journal] [NIFTY|BANKNIFTY|SENSEX]"
---

# ict-india

The user's ICT 2022 Mentorship notes, applied to Nifty, Bank Nifty and Sensex. The full line-by-line
transcription is in `../NOTES.md`. Each rule below cites its page.

**What is ICT and what is adapted:** the model (sweep → MSS → FVG → retrace → confirm → target the
next liquidity, sizing, management, psychology) is straight from the notes. **The time windows are
not.** ICT's killzones are New York times, so they have to be mapped onto 09:15–15:30 IST. This skill
uses these windows. They're starting points to test with `backtest`, so say so if the user asks:

| Window | IST | Why |
|---|---|---|
| Opening range | 09:15–09:30 | Judas window. Its high and low become liquidity. *(p.11: "avoid the opening ranges"; p.12: "the move at 9:30 is usually the opposite")* |
| AM killzone | 09:30–11:00 | First expansion of the day |
| Lunch | 11:30–13:00 | No trades |
| PM killzone | 13:15–14:45 | European/London open (12:30 IST in summer, 13:30 in winter) |
| Flat by | 15:15 | Before the broker's intraday square-off |

This skill **never places an order** and is not investment advice. The user decides and clicks. Say
once, when you first show a plan, that most intraday F&O traders lose money (SEBI's own studies say
so). If the user mentions selling signals or calls on PulsEdge, flag that publishing BUY/SELL calls
on named instruments raises SEBI Research Analyst questions. Their roadmap already lists this as open.

## The tool

`mmxm.py` in this folder, standard-library Python 3.8+. State lives in `ict/` in the working folder:
`config-india.json`, `bias.json`, `plan-india.json`, `journal.jsonl`.

```bash
python3 mmxm.py levels BANKNIFTY                   # PDH/PDL, PWH/PWL, day open, session H/L, 1h FVGs
python3 mmxm.py bias BANKNIFTY                     # suggests a bias from yesterday vs the day before
python3 mmxm.py bias BANKNIFTY --set long --note "swept PDL at open, draw on PDH"
python3 mmxm.py check BANKNIFTY                    # where the setup stands right now
python3 mmxm.py watch BANKNIFTY --every 60
python3 mmxm.py gate                               # PASS/BLOCK the saved plan
python3 mmxm.py size --entry 56120 --stop 56040 --target 56300 --instrument BANKNIFTY           # futures lots
python3 mmxm.py size --entry 56120 --stop 56040 --target 56300 --instrument BANKNIFTY --option  # option lots via delta
python3 mmxm.py backtest BANKNIFTY --days 59 --list
python3 mmxm.py journal add --symbol BANKNIFTY --side long --entry 56120 --stop 56040 --qty 2 --emotions anxious
python3 mmxm.py journal review
```

Data: Yahoo's spot index charts (^NSEI, ^NSEBANK, ^BSESN), unofficial and they can lag. Futures
trade at a premium to spot and options move by delta and lose time value, so **levels come from the
spot chart and the order goes on the futures or option the user trades**. Shift the levels by the
basis, or run the tool on a broker CSV of the futures itself (`--file`, columns
`time,open,high,low,close`; Zerodha/Upstox/TradingView exports work once renamed).

Lot sizes live in `profile.json` (NIFTY 65, BANKNIFTY 30, SENSEX 20, from the January 2026
revision). NSE/BSE revise them twice a year, so check them against the broker before sizing real
money. Expiries: Nifty weekly on Tuesday, Sensex weekly on Thursday, Bank Nifty monthly only.

## The day, step by step

### Before 09:15
1. `levels`: PDH/PDL, PWH/PWL, open 1h FVGs. Note GIFT Nifty and the overnight US move (DXY, US
   yields; p.6 "interest rates run the price"). Those aren't in the tool, so ask the user.
2. `bias`: the user decides and **writes it down** with `bias --set` *(p.11)*. `none` is a fine
   answer *(p.15)*. On a day with no clear bias, their own journal says what happens (p.2:
   "Bankex: market against overall bias… holding due to loss").
3. Events: RBI policy, the Budget, US CPI/FOMC overnight → `events` in the config *(p.6)*.

### 09:15–09:30: watch, don't trade
4. The opening range builds liquidity on both sides. This is the PO3 Judas window *(p.4 AMD,
   p.11 EP-9/EP-10)*.

### AM killzone 09:30–11:00 (PM 13:15–14:45)
5. `check`/`watch` walks the model: **sweep** of a pool opposite to the bias (opening range
   high/low, PDH/PDL, 15m swing, equal highs/lows) → **MSS**, a close through the short-term
   swing with a displacement candle → **FVG** in that leg → retrace into it → **two candles** whose
   bodies hold the gap → enter. Stop beyond the swept high/low. TP1 = the nearest untouched
   liquidity at least 1R away, TP2 = the next one. *(p.7, p.8, p.9, p.11, p.12, p.13, p.14)*
6. `gate` before every order. It returns **BLOCK** if any of these hold:
   - no written bias, or the plan goes against it
   - it's outside the windows
   - 2 trades or 2 losses have already happened today
   - it's the afternoon after a morning trade (p.7)
   - it's a Friday (p.6, switch off with `avoid_fridays: false`)
   - it's an event day
   - it's the same level as an earlier entry (p.2: "do not take multiple entries at same level
     even if right")
   - **it adds to an open position that isn't at break-even** (p.2: "added quantity… holding in
     loss, waiting for money")
   - the R:R is poor, or the entry is on the wrong side of equilibrium

   On expiry days it warns that options are flat by 15:15 (p.2: "do not wait for expiry to expire").

### Managing
7. At 50% to TP1, cut the stop distance by 25%. At 75%, move it to break-even *(p.13, EP-41)*.
   Book at the target, don't wait for more (p.1: "waiting for more targets", "not booking profits
   at high").
8. Journal while it's live, feelings included (p.1–2: the "Live Journal").

## Sizing

`RPT = account × risk%`. Futures: `lots = RPT ÷ (stop points × lot size)`. Options:
`lots = RPT ÷ (stop points × delta × lot size)`, an approximation. If the user gives a premium
stop instead, size on that (`--entry`/`--stop` in premium, `--option` off). Risk is capped at 0.5%
until `"profitable": true` *(p.12)*. `size_factor: 0.75` applies "lower size by 1/4" *(p.1)*. The
journal's "entered with all profits" (p.2) is exactly what fixed RPT prevents: never size off the
day's gains.

## Your own trades, through the ICT structure

`trades.py` reads Aditya's real tradebook and splits every rupee of P&L along the same lines the
model uses. Put the broker files in `ict/dhan-2025/` (git-ignored), then:

```bash
python3 trades.py report ict/dhan-2025/*.xlsx ict/dhan-2025/*.csv --months 2025-06,2025-08,2025-09,2025-10,2025-11
python3 trades.py report ict/dhan-2025/*.csv --bars ict/banknifty-5m.csv --json ict/dhan-2025/report.json
```

- It reads Excel/CSV tradebooks **and contract-note PDFs**, including password-locked ones, in bulk. A whole
  zip of them is unlocked with one password, so nobody has to open each note
  (`DHAN_PDF_PASSWORD=... python3 trades.py report notes.zip`). Lines that look like trades but can't be read
  are listed, never guessed. The PDF layout parser is checked against a synthetic NSE-style note only, so
  confirm it on the first real note.
- Fills are paired into round trips (flat → position → flat per contract). P&L is gross, so check it
  against the P&L statement's net total.
- Each trade is tagged with its ICT window (opening range, AM killzone, lunch, PM killzone, close),
  hour, weekday, days to expiry (read from the contract name), underlying, buy/sell CE/PE, index direction,
  holding time, and its number in the day.
- **Rule replay**: every rule from the notes is applied to the trades Aditya actually took, to show what each
  would have blocked and whether that saved or cost money. That's how the notes and the real P&L get
  combined into one rule set: keep the rules that saved money, question the ones that cost it.
- With `--bars` (index candles for those dates), it also checks whether each entry came after a
  liquidity sweep or during a live MMXM setup in the same direction.
- Only aggregates go into notes or memory. The raw statements belong to Shreyas's account (from a
  previous venture), so never copy their personal details anywhere.

## Backtest before trusting it

The notes ask for 6 months of backtesting *(p.10)*. Yahoo gives about 59 sessions of 5m bars. For more, use a
broker CSV with `--file`. Run variants: `--bias both` vs `--bias auto`, `--entry-mode limit`,
`--dr-filter extreme`. Since the Indian windows are an adaptation, also try other windows by
editing `sessions` in `profile.json`. Report the results honestly. Under 30 trades is too small a sample.

## How to talk to the user

- Use ICT vocabulary, keep it short, and answer in the user's own terms (Bank Nifty points, lots, ₹).
- Their journal names their failure modes: anxiety, not breathing, panic-booking or not booking,
  adding quantity in a loss, entering with all profits, holding against bias, waiting for expiry,
  trading for others. When a request matches one, quote the line from their notes once, kindly,
  and move on.
- Never invent prices. If the fetch fails, say so and ask for a CSV.
