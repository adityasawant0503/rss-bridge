# Memory: ICT trading research

Read this first when picking the work back up. Last updated 26 Oct 2026.

## Aditya's background

- Aditya Sawant trades Indian index derivatives (Bank Nifty, Nifty, Sensex, Bankex) through **Dhan**.
- About three years ago Aditya studied ICT's YouTube mentorships, mainly the **2022 Mentorship (MMXM)**, plus
  Justin Werlein on psychology and Ali Khan's "ICT Bible". Their handwritten notes (15 pages) are
  transcribed in [`NOTES.md`](NOTES.md).
- Their live-journal pages name their own failure modes: anxiety, not breathing, not booking profits
  at highs, adding quantity while in a loss, entering with all profits, holding against bias, waiting
  for expiry, trading for others.
- Aditya also runs PulsEdge (Indian market news/signals) in this same repo. That project is separate from this one.
- Working style: likes visual explanations (infographics) and plain language. They're happy for Claude
  to pick sensible defaults ("do what is best") and explain them afterwards.

## What exists

| Thing | Where |
|---|---|
| Two Claude skills: `ict-india/`, `ict-us-futures/` | branch `claude/relaxed-heisenberg-becpg7` of `adityasawant0503/rss-bridge`, folder `ict-skills/` (not merged to master) |
| Shared engine `mmxm.py` (levels, bias, check/watch, backtest, size, gate, journal) | identical copy in each skill folder, with a test that keeps them in sync |
| Line-by-line transcription of the notebook, plus where the notes conflict | `NOTES.md` |
| 30 offline tests on hand-built sessions | `tests/test_mmxm.py`, run `python3 -m unittest discover -s ict-skills/tests` |
| Infographic "MMXM Playbook" (private to Aditya) | https://claude.ai/artifact/KkvzwqyKSmzxB4qSWxwMMS |
| Personal state (bias, plans, journal) | `ict/`, git-ignored |

Before this work, we reviewed `github.com/Jakeschincariol/day-trader-skill`: 11 MIT-licensed day-trading
skills for US stocks, a read-only check found no risky code, and it isn't ICT. It was used as a
structural reference only.

## Decisions (and why)

- **Two markets only for now:** Indian indices and US index futures (Aditya's choice, 26 Oct 2026).
- **Indian killzones are an adaptation, not ICT's:** the 09:15–09:30 opening range is the Judas window
  (no trades), AM 09:30–11:00, lunch off, PM 13:15–14:45, flat by 15:15. These need backtesting.
- **US killzones:** NY AM 08:30–11:00 and PM 13:30–15:00 ET, from the notes. In IST that's
  18:00–20:30 in summer and 19:00–21:30 in winter.
- **Where the notes conflict, the defaults are:**
  - the nearer of two FVGs (`fvg_pick`)
  - stop above the swept high (`stop_mode: swing`)
  - wait 2 confirmation candles (`entry_mode: confirm`)
  - the dealing-range filter blocks the wrong side of 50% and only warns inside 0.25–0.75 (`dr_filter: half`)
  - 0.5% risk until Aditya marks themselves profitable, then 1%
- **Sizing:** EP-41's "x / 5" is the MES point value. In general, contracts = RPT ÷ (stop × point value).
  India uses lots, and options via delta.
- **The gate blocks adding to an open position unless its stop is at break-even.** This comes straight
  from the journal ("added quantity", "holding in loss").

## Known gaps

- **The skills have never run on real market data.** The build sandbox couldn't reach Yahoo. The first
  real backtest is still to do.
- Yahoo only keeps about 60 days of 5m bars. The notes ask for 6 months of backtesting, so it needs a broker export.
- Lot sizes in `ict-india/profile.json` (NIFTY 65, BANKNIFTY 30, SENSEX 20) came from memory of the
  January 2026 revision and need checking against Dhan.
- **Moving to its own repo is blocked.** Creating a GitHub repo from the session failed with a 403. Waiting for
  Aditya to create an empty private repo (suggested name `ict-mmxm-skills`). Then push `ict-skills/` there
  and remove it from the rss-bridge branch.
- PulsEdge has an open SEBI Research Analyst wording question (see `pulsedge/ROADMAP.md`). Don't publish
  these setups as calls there until it's settled.

## Next: Dhan 2025 trade review

- **Waiting on:** Aditya's Dhan trade book and contract notes for **June, August, September, October and
  November 2025** (July not included).
- **What Aditya said about them (26 Oct 2026, unverified):** "highly profitable", roughly "56" overall
  (the unit isn't confirmed: ₹56k? 56%?), with about 12 losing trades and everything else profitable.
  Confirm against the data and don't repeat it as fact before then.
- **Goal:** tally every trade, find the traits that made those months work, compare them with the MMXM
  rules, then tune `ict-india` (windows, filters, sizing) to what actually worked.
- **Plan:**
  1. Parse the tradebook export (Excel/CSV). Pair buys and sells into round trips (FIFO per contract)
     and take charges from the contract notes (PDF, usually password-protected with the PAN).
  2. Work out P&L per trade, per day and per month, with win rate, average win and loss, and the largest loss.
  3. Slice the results by instrument, CE/PE or futures, direction, entry hour, weekday, expiry day or not,
     holding time, premium bucket and size.
  4. Check entries against the killzones and, where 5m index history for those dates can be
     obtained (Yahoo doesn't go back that far, so try the Dhan historical-data API or a chart export),
     against sweep → MSS → FVG.
- **Reminder:** a scheduled task in the original session fires on 27 Oct 2026 at 18:30 IST to ask
  Aditya for the files. Claude can also pull the contract notes from Aditya's Gmail if they agree.
