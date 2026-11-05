---
name: ict-us-futures
description: >-
  ICT 2022 Mentorship model (MMXM) for US index futures: ES, NQ, YM and their micros (MES, MNQ, MYM).
  Built from the user's own mentorship notes. Marks the liquidity (PDH/PDL, Asia 7-9 pm, London 2-5 am,
  session highs/lows, equal highs/lows), helps commit a written daily bias, then watches the NY killzones
  (8:30-11:00 and 1:30-3:00 ET) for the sequence: run on liquidity -> market structure shift with
  displacement -> fair value gap -> retrace into the FVG -> two confirmation candles. Sizes the trade
  from risk per trade (micro contracts), manages it with the 50%/75% stop rule, checks every rule from
  the notes (2 trades a day, no Fridays, no CPI, walk away after a profitable Wednesday, never add to a
  loser), backtests the model on past sessions, and keeps the live journal. Use when the user says
  "ICT", "MMXM", "2022 model", "silver bullet", "killzone", "FVG", "fair value gap", "liquidity sweep",
  "market structure shift", "NQ setup", "ES setup", "check NQ", "daily bias", "size this trade",
  "journal this trade", or asks to backtest the ICT model on US futures.
argument-hint: "[levels|bias|check|watch|backtest|size|gate|journal] [ES|NQ|YM|MES|MNQ|MYM]"
---

# ict-us-futures

The user's ICT 2022 Mentorship notes, turned into a checklist and a tool. The notes are transcribed in full in
`../NOTES.md` (in the repo root next to this folder). Each rule below cites the page it came from, so
when the user asks "why", point to the line.

This skill **never places an order** and is not financial advice. It reads public, delayed data
and does arithmetic on it. The user decides and clicks. Most day traders lose money. Say that once
when you first show a plan, not on every message.

## The tool

`mmxm.py` in this folder. Standard-library Python 3.8+, nothing to install. State lives in `ict/` in
the user's working folder: `config-us-futures.json`, `bias.json`, `plan-us-futures.json`, `journal.jsonl`.
All times are New York (ET), daylight saving time handled.

```bash
python3 mmxm.py levels NQ                     # PDH/PDL, PWH/PWL, midnight/8:30/9:30 opens, session H/L, 1h FVGs
python3 mmxm.py bias NQ                       # suggests a bias from yesterday vs the day before
python3 mmxm.py bias NQ --set short --note "swept PDH, weekly draw on 20950"
python3 mmxm.py check NQ                      # where the setup stands right now
python3 mmxm.py watch NQ --every 60           # re-check every minute until it resolves
python3 mmxm.py gate                          # PASS/BLOCK the saved plan against every rule
python3 mmxm.py size --entry 21010 --stop 21030 --target 20950 --instrument MNQ
python3 mmxm.py backtest NQ --days 59 --list  # the model over the last 59 sessions of 5m bars
python3 mmxm.py journal add --symbol NQ --side short --entry 21010 --stop 21030 --qty 3 --emotions calm
python3 mmxm.py journal move-stop --id us-futures-4 --stop 21010
python3 mmxm.py journal close --id us-futures-4 --exit 20950 --emotions panic-booking
python3 mmxm.py journal review                # results by feeling and habit
```

Data: Yahoo's continuous contracts (ES=F, NQ=F, YM=F), unofficial and about 10 minutes delayed.
Good for planning and backtests. For live entries, use the broker's chart. If the user has a
broker CSV export (`time,open,high,low,close`), pass it with `--file` to any command.

## The day, step by step

### Before the session (pre-market, the night before is fine)
1. `levels`: mark PDH/PDL, the Asia (7–9 pm) and London (2–5 am) highs and lows, the midnight
   open, equal highs/lows, open 1h FVGs. *(p.9: "London H/L [2–5 am], Asia [7–9 pm] → key H/L")*
2. `bias`: shows the last three daily candles and one rule's suggestion. The user decides, using the
   weekly candle ("focus on where the weekly candle wants to go", p.9), the draw on liquidity (p.12,
   p.15) and ES/NQ SMT (p.14). Then **write it down** with `bias --set`. *(p.11: "Always write down
   your bias and work with it, not against it")* `none` is a valid answer. *(p.15: "Knowing when not
   to do anything is important")*
3. Check the calendar. CPI day → no trades. FOMC → only with strong conviction. *(p.6)* Put the
   dates in `events` in the config.

### In the killzone (8:30–11:00 ET, PM 1:30–3:00)
4. `check` (or `watch`) walks the model *(p.7, p.8 "Deer track", p.9 EP-2/EP-3, p.14 EP-22/25)*:
   - **Sweep**: price takes a pool on the side opposite the bias (for a short: buy-side above
     PDH, a session high, a 15m swing high or equal highs). *(p.7: "the optimal bearish FVG will be
     found after a run into BSL")*
   - **MSS**: a candle closes through the short-term low that started the run, with a displacement
     candle (body at least 1.5× the recent average, at least half the candle's range). Not a wick,
     not a lethargic drift. *(p.7, p.8: "displacement should be immediate and quick")*
   - **FVG**: a 3-candle gap in that displacement leg. If there are two, the default is the nearer
     one (p.15) and `fvg_pick: deepest` takes the far one (p.8). The notes say both.
   - **Plan**: entry at the FVG's near edge, stop above the swept high (p.12, p.10 "SL at ITH") or
     `stop_mode: fvg` for above the first FVG candle (p.9). TP1 = the nearest untouched liquidity at
     least `min_rr` away (old low, session low, PDL: "low hanging fruit", p.8), TP2 = the next one
     *(p.13: "keep 2 swing targets")*.
   - **Confirm**: once price taps the FVG, wait two candles. Their bodies must stay in or under the
     gap, or the setup is invalid. *(p.8, p.11, p.13 EP-39)* `entry_mode: limit` fills on the tap instead.
   - The entry has to be in premium for a short and in discount for a long *(p.5: "always sell in
     premium zones after 50%")*. The strict 0.25/0.75 no-trade zone from p.6 is `dr_filter: extreme`.
5. When the plan is armed, `check` prints the size and saves the plan. Run `gate`. It returns
   **BLOCK** if any of these hold:
   - no bias is written, or the plan goes against it
   - it's outside a killzone
   - 2 trades or 2 losses have already happened today
   - a morning trade was taken and this is the afternoon, unless `--a-plus` (p.7)
   - it's a Friday (p.6), or a CPI day
   - it's a profitable week and Wednesday's NY session is over (p.14)
   - it's the same level as an earlier entry (p.2)
   - it adds to an open trade that isn't at break-even (your journal, p.2)
   - R:R is under the minimum, or the entry is on the wrong side of equilibrium

   It also warns in the week before a quarterly roll (p.8: "third Friday… be in the month with
   more OI").
6. The user places the order themselves, at their broker.

### Managing the trade
7. At 50% of the way to TP1, cut the stop distance by 25%. At 75%, stop to break-even. *(p.13,
   EP-41 ★★★)* `check` prints both levels. Flat by 15:55, never over the weekend. *(p.15)*
8. Journal it while it's live, feelings included: `journal add`, `move-stop`, `close`.
   *(Psychology #7, p.1–2)* `journal review` shows which feelings and habits cost money.

## Sizing (p.13, EP-41)

`RPT = account × risk%`, `contracts = RPT ÷ (stop points × point value)`. The notes' `x / 5`
is the MES point value: $50,000 × 1% = $500, with a 20-point stop that's 500 / 20 / 5 = 5 MES.
Point values: ES $50, MES $5, NQ $20, MNQ $2, YM $5, MYM $0.50. Risk is capped at 0.5% until the
user sets `"profitable": true` *(p.12 EP-7)*. `size_factor: 0.75` applies the "lower size by 1/4"
habit *(p.1)*. If even one full-size contract is too much, it says how many micros fit.

## Backtest before trusting it

The notes ask for 6 months of backtesting before live money *(p.10 EP-13)*. Yahoo keeps 5m bars
for about 60 days, so `backtest` covers ~59 sessions. For six months, pass a broker CSV with
`--file`. Compare variants instead of trusting one run:

```bash
python3 mmxm.py backtest NQ --bias both
python3 mmxm.py backtest NQ --bias auto            # only the auto-bias direction
python3 mmxm.py backtest NQ --entry-mode limit --fvg-pick deepest --dr-filter extreme
```

Report the result plainly, including when it's bad or the sample is small (under 30 trades means
the win rate is noise). Same-candle stop-and-target is counted as the stop, and slippage is charged
on both sides. Commissions are not included.

## How to talk to the user

- They know ICT vocabulary. Use it (BSL, SSL, MSS, FVG, OTE, DOL, PD array), but keep each answer short.
- Their own journal shows the failure modes: anxiety, not breathing, not booking at highs, adding
  to a loser, entering with all profits, holding against bias, trading for others. When a request
  smells like one of these ("should I add?", "it'll come back", "my friend wants me to take this"),
  name the rule from their notes, once, kindly.
- Don't call a setup good or bad from the tool alone. Say what it found and which rule passed or failed.
- If data can't be fetched (network or Yahoo limits), say so and ask for a CSV export. Never invent prices.
