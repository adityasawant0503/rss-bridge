# Memory: ICT trading research

Read this first when picking the work back up. Last updated 12 Nov 2026.

## Current mode (12 Nov 2026): paper trading and research only

- **No real-money trading.** On 12 Nov 2026 Aditya decided to stop trading with real money, to work on
  trading psychology, and to use paper trading to look for an edge. Don't suggest going live, real-money
  sizing or a go-live date. If Aditya asks to trade real money, remind them of this decision first.
- **Daily (weekdays):** the "Morning Fade plan" scheduled task (10:05 IST) runs, from the repo root with
  `ICT_DIR=<repo>/ict` (the engine reads `ict/` relative to the working folder), `optbt.py today SENSEX`
  and `NIFTY`, pushes the paper plan and runs `optbt.py archive`. Aditya sends chart screenshots at 10:15
  and at the close; Claude reads the levels off them and logs paper trades with `mmxm.py journal`
  (git-ignored `ict/journal.jsonl`), tagging rule breaks and feelings.
- **Morning Fade** (`ict-india/optbt.py`): fade the last 5 sessions' move with an at-the-money weekly
  option at least 4 days from expiry, bought at 10:15; stop -20%, target +40%; pyramid one extra lot at
  +15% and move the stop for both to their average; max 2 lots; out by the close; one trade a day.
  The model prices options with Black-Scholes from India VIX, so real premiums must be checked.
- **Intraday archive:** `optbt.py archive` merges every 5m (Yahoo serves 60 days) and 1m (7 days) bar for
  Nifty, Sensex, Bank Nifty and India VIX into `ict/market/archive/`, in the format
  `mmxm.py backtest --file` reads. Started 12 Nov 2026 with 5m data from 17 Aug 2026.
- **Research:** (1) paper-test the Morning Fade and compare real premiums with the model.
  (2) **Morning sweep-and-reclaim** (`ict-india/sweep.py`), written from Aditya's Nifty shorts of 11 and
  13 Nov: sweep of the opening range (09:15-09:30) or the previous day's high/low, a 5m close back inside
  within 30 minutes (entries 09:30-11:00), stop at the sweep extreme plus 0 / 0.05% / 0.10%, target 2R,
  out at 15:10. Rules and the pass bar were fixed before testing (13 Nov). On Aug-Oct data only the
  opening-range version without a buffer passed, on 2 of 3 indices, and its Nifty stops are often 10-20
  points (maybe too tight for options). All six versions are forward-tested from 16 Nov: the 10:05 task
  runs `sweep.py score` (log in `ict/research/`, git-ignored) and on Fridays `sweep.py summary`. Decide
  after 2-3 months; don't tune the rules in between. (The strict 2022 model finds about one setup in 60
  days.) (3) Later: check whether fade days that also show a sweep are the bigger days.
  (4) **Variants side by side** (`ict-india/variants.py`, 17 Nov 2026), from patterns in Aditya's own
  trades. In 2025 (260 index-option round trips), trades with the opening gap made money (PF 2.65), while
  trades against the gap or on flat opens lost on most days. The early-morning edge (before 10:00, +4.6L)
  rests on 20 Oct 2025 alone; without the best 2 days it is negative. Three versions: `fade` (no
  pyramid), `fade-gap` (fade only when the gap of at least 0.1% agrees), `gap` (follow the gap). Each is
  scored per day with the model at 10:15 and with real bhavcopy prices bought at the open (the open is noisy:
  the real column isn't the 10:15 trade). None met the bar set before the test. Out-by-11:15 versions were
  worse and dropped. Forward from 18 Nov: the 10:05 task runs `variants.py today` and `score`, and
  `summary` on Fridays. The paper trade stays the Morning Fade with the pyramid.
  (5) **What the 17-20 Nov research found:** at the index level the 5-day fade is about +4 bp a day (not
  significant) and smaller than option decay; negative-RR exits, liquidity raids (10 years, daily and hourly),
  opening-flush reversals, OI walls and 149 combined morning rules showed no intraday edge that held in both
  halves of the data. The consistent effect is multi-day trend: buying strength beats drift, and trend filters
  halve drawdowns. Aditya wants high-accuracy, negative-RR trading; any such idea must beat the blind-direction /
  same-distance baseline after costs before it counts.
  (6) **Momentum paper portfolio** (`ict-india/momentum.py`, from 30 Nov 2026): each month-end, the 10 Nifty 50
  stocks with the best 12-month return excluding the latest month, equal weight; cash (6%/yr) when Nifty is below
  its 200-day average. Backtest Dec 2017 - Nov 2026 on today's members (survivorship-biased): +21.2%/yr, worst
  fall -15%, vs Nifty +10.7%, -29%; +2.6%/yr over the same list's equal weight in both halves. Tax not modelled.
  The 10:05 task runs `momentum.py rebalance`, which acts only on the first run after a month-end. Update
  `MEMBERS` when NSE changes the Nifty 50 (March, September). Paper only, like everything else.
- **PulsEdge link-up (13 Nov 2026):** Aditya keeps the PulsEdge terminal (their own repo
  `adityasawant0503/pulsedge`, public; GitHub Pages) open next to this chat. A "PulsEdge check before the
  plan" scheduled task (09:50 IST, weekdays) pushes its pre-market sentiment; `ict-india/pulse.py` reads
  `pulsedge/data/premarket.json` from a read-only clone and the 10:05 task logs it next to the fade's
  direction (`ict/research/premarket-log.jsonl`) to test later whether agreement days are better. It
  never changes the plan. Aditya's terminal links carry an owner pass: never store or repeat them.
- **Backup (14 Nov 2026):** `ict-india/backup.py push` mirrors `ict/journal.jsonl`, `config-india.json`,
  `research/` and `market/archive/` into Aditya's private repo `adityasawant0503/ict-research` (clone at
  `/home/user/ict-research`); the 10:05 task runs it daily. On a fresh machine run
  `backup.py restore` before anything else. `ict/dhan-2025/` and `ict/pdf/` are never backed up.
- **Reminders on the phone (16 Nov 2026):** Aditya wants every Claude reminder on their iPhone, not just as
  Claude app pushes. The phone's Reminders app can't be reached from here, so they get an .ics calendar
  file (alerts in the iPhone Calendar app). Whenever a scheduled task is added, changed or paused, send
  an updated `claude-reminders.ics` covering all active tasks. The Torrent options reminders were left
  out pending Aditya's decision to keep or pause them (they conflict with the paper-only decision).
- Results, P&L and anything derived from the statements stay out of this repo.

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

- **Market data:** Yahoo works from the `rss-bridge` cloud environment (`mmxm.YAHOO_UA = "Mozilla/5.0"`;
  a full browser user agent gets HTTP 429). Yahoo only keeps about 60 days of 5m bars, so the archive
  above has to grow day by day to reach the 6 months the notes ask for.
- **Expiry holidays (fixed 17 Nov 2026):** `optbt.weekly_expiry` moves an expiry that falls on a holiday to
  the trading day before, using `pulsedge/data/calendar.json`. The plan printed NIFTY 24 NOV on 17 Nov, but
  that day is a holiday and the real contract is 23 NOV. The calendar only lists 2026: add NSE's 2027 list
  in December, or plans from January will ignore holidays again. Backtests before 2026 ignore holidays.
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
- **What Aditya said about them (26 Oct 2026, unverified):** about **₹5–6 lakh a month**, with typical
  trading days of ₹30k–₹80k profit and about 12 losing trades in total. Aditya also mentioned "5–6
  minutes", possibly the typical holding time (to confirm). Check all of this against the data and
  don't repeat it as fact before then.
- **Source:** the statements came from a former business partner's email, not Aditya's. Keep raw files in
  the git-ignored `ict/` folder. At Aditya's request (2 Nov 2026), no names, account IDs or other personal
  details from them are kept anywhere, and no results from them go into this repo (it may be public).
  Totals live in Aditya's private Notion memory ("2025 trade review").
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
- **Aim (29 Oct 2026):** combine the real P&L with the ICT notes into one strategy that fits Aditya, keeping
  the ICT structure as the framework.
- **Tool ready:** `ict-india/trades.py report <files>` reads Dhan Excel/CSV tradebooks. It builds round
  trips, tags them by ICT window, hour, weekday, days to expiry, instrument, CE/PE, direction and holding
  time, and replays the notes' rules on the real trades. `--bars` adds sweep/MMXM checks. It's tested on
  synthetic Dhan-style files only; the real column names are unknown until the files arrive, so the
  header detection may need a tweak.
- **Contract notes (30 Oct 2026):** Aditya worried that unlocking each password-locked note would be tedious.
  `trades.py` now unlocks and reads them in bulk (a zip plus one password, via pdftotext/pypdf). The
  easiest route is still Dhan's single tradebook Excel export for the whole period. Screenshots are only
  good for checking monthly totals, not for the trade-by-trade analysis.
- **Network:** this cloud environment blocks Yahoo, Dhan, NSE and Stooq (checked 29 Oct 2026). Aditya needs
  to allow them in the environment's network settings, or the index bars have to come as files.
- **Reminder:** a scheduled task in the original session fires on 27 Oct 2026 at 18:30 IST to ask
  Aditya for the files.
