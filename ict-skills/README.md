# ICT MMXM skills

Two Claude skills built from my ICT 2022 Mentorship notes (the MMXM model), one per market:

| Skill | Market | Killzones |
|---|---|---|
| `ict-india/` | Nifty, Bank Nifty, Sensex (NSE/BSE, futures or index options) | 09:30–11:00 and 13:15–14:45 IST (an adaptation, see below) |
| `ict-us-futures/` | ES, NQ, YM and the micros MES, MNQ, MYM (CME) | 08:30–11:00 and 13:30–15:00 ET |

[`NOTES.md`](NOTES.md) is the full transcription of the 15 notebook pages, line by line. It also
lists where the notes contradict each other and which side the skills take.

## What they do

```
levels -> bias --set -> check / watch -> gate -> (you place the order) -> manage -> journal
backtest  (before any of it is trusted with money)
```

- **levels**: PDH/PDL, previous week high/low, session highs/lows (Asia, London, NY / opening range),
  the midnight / 08:30 / 09:30 or 09:15 opens, the dealing range and equilibrium, open 1h FVGs.
- **bias**: suggests a bias from yesterday's candle against the day before. You decide, and
  write it down. The gate won't pass a trade without a written bias.
- **check / watch**: the 2022 model in order: a run on liquidity, then a market structure
  shift with displacement, then a fair value gap, a retrace into it and two confirmation candles. It prints
  the entry, the stop beyond the swept high/low, TP1/TP2 at the next untouched liquidity, the size, and
  the 50%/75% stop-management levels.
- **gate**: PASS or BLOCK against every rule in the notes and the live journal. That means 2 trades a day, no
  afternoon after a morning trade, no Fridays, no CPI, walk away after a profitable Wednesday (US),
  never add to a loser, no second entry at the same level, killzones only, premium/discount.
- **size**: `RPT = account × risk%`, then `contracts = RPT ÷ (stop × point value)`. Lots for India, plus
  options via delta. Risk is capped at 0.5% until you mark yourself profitable (EP-7).
- **backtest**: the same code run over past sessions, with stats by direction and killzone.
- **journal**: the live journal from the notebook (feelings included), plus a review of which
  feelings and habits cost money.

Nothing here places orders. You click.

## Use

Standard-library Python 3.8+, nothing to install.

```bash
cd ict-skills/ict-us-futures
python3 mmxm.py levels NQ
python3 mmxm.py bias NQ --set short --note "swept PDH, draw on PDL"
python3 mmxm.py check NQ
python3 mmxm.py gate
python3 mmxm.py backtest NQ --days 59 --list

cd ../ict-india
python3 mmxm.py check BANKNIFTY
python3 mmxm.py size --entry 56120 --stop 56040 --target 56300 --instrument BANKNIFTY --option
```

Settings: copy `config.example.json` to `ict/config-<market>.json` in the folder you run from, and
set your account size, risk and event dates. State (bias, plans, journal) is written to `ict/`, which is
git-ignored.

As Claude skills, copy the folders into `~/.claude/skills/` (or a project's `.claude/skills/`), or
add this folder as a plugin. Then ask things like "check Bank Nifty", "what's my NQ bias",
"size this trade", "journal it".

Tests run offline, on hand-built sessions that follow the model step by step:

```bash
python3 -m unittest discover -s ict-skills/tests -v
```

## Honest limits

- **Data.** Yahoo's free charts: CME futures are about 10 minutes delayed, Indian indices are the spot
  index (futures trade at a basis, options move by delta). Use them for planning and backtests, then
  take entries from your broker's chart. Any command can read a broker CSV with `--file`.
- **History.** Yahoo keeps about 60 days of 5-minute bars. The notes ask for 6 months of backtesting,
  so get a longer export from your broker for that.
- **Indian killzones** are my mapping of ICT's New York windows onto 09:15–15:30 IST, not something ICT
  taught. Backtest them, and edit `sessions` in `ict-india/profile.json` if other windows test better.
- **Lot sizes** (NIFTY 65, BANKNIFTY 30, SENSEX 20) are from the January 2026 revision. NSE/BSE change
  them twice a year, so check `ict-india/profile.json` against your broker.
- **Mechanical rules approximate discretionary ones.** "Displacement" is a body at least 1.5× the
  recent average. "Liquidity" is session highs/lows, 15m swings and equal highs. Read the
  backtest as a test of *this* rule set.
- Not financial advice. Most intraday traders lose money.

## Editing

`mmxm.py` is the same file in both skill folders, so each folder works when copied alone. Edit
`ict-us-futures/mmxm.py`, then copy it over `ict-india/mmxm.py`. A test fails if the two drift apart.
