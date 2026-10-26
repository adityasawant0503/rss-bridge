# PulsEdge data

Three files drive the site. Each has a filled-in `*.sample.json` next to it,
which is used until the real file exists. Push a real file to `master` and the
site, the terminal and the Telegram bot switch to it within a couple of minutes.

| File             | Used by                                   | Sample                    |
|------------------|-------------------------------------------|---------------------------|
| `feed.json`      | Terminal signal feed, landing page feed, Telegram bot | `feed.sample.json` |
| `premarket.json` | Terminal pre-market panel                 | `premarket.sample.json`   |
| `universe.json`  | Stock list with names and sectors         | `universe.sample.json`    |
| `track.json`     | Track record page (`track.html`), written by `pulsedge-bot/track_record.py` | none: the page shows an empty state |
| `calendar.json`  | NSE trading holidays; trials count trading sessions with it | built into `assets/member.js` |
| `keys.json`      | Public keys allowed to sign access links (one per PulsEdge HQ device) | none |
| `revoked.json`   | Access-link ids that no longer work         | none |

## `feed.json`: signals

```json
{ "updated": "2026-10-20T10:37:30+05:30", "items": [ { ... }, { ... } ] }
```

Each item is one news signal. Only `headline` and `time` are required.

| Field        | Example / values                                          |
|--------------|-----------------------------------------------------------|
| `id`         | `"powermech-2026-10-20-order"`, stable and unique. Stops the bot posting twice. |
| `time`       | `"2026-10-20T09:57:18+05:30"`                              |
| `headline`   | `"Power Mech Projects discloses new order win"`            |
| `source`     | `"NSE Announcements"`, `"RedBox India"`, `"FinancialJuice"` |
| `call`       | `buy`, `sell`, `watch` or `ignore`                         |
| `horizon`    | `intraday`, `swing` or `positional`                        |
| `direction`  | `up`, `down` or `mixed` (worked out from tickers if left out) |
| `latency`    | Seconds from news to analysis, `2.9`                       |
| `tickers`    | `[{"symbol": "BPCL", "direction": "down"}]`, or just `["TCS"]` |
| `sectors`    | `["OMCs", "Paints"]`                                       |
| `impact`     | 0–100                                                      |
| `confidence` | 0–100                                                      |
| `category`   | `"Order Win"`, `"Commodity"`, `"Government Policy"`        |
| `action`     | The 🎯 line: `"Buy only above the first 15-min high"`      |
| `reason`     | List of bullet points                                      |
| `risks`      | List of bullet points                                      |
| `original`   | The source text as published                               |
| `url`        | Link to the filing or article                              |
| `after`      | `{"symbol": "POWERMECH", "from": 2710.5, "m15": 1.2, "h1": 2.1, "close": 2.8, "status": "played out"}` |

Tabs in the terminal: **Trade ideas** = `buy`/`sell`, **Watch** = `watch`,
**RedBox** = source contains "RedBox", **Filings** = NSE/BSE announcements,
**My stocks** = tickers in the visitor's watchlist.

The Telegram bot posts every new `buy` or `sell` signal once.

Older items in the `verdict` / `impacts` format still work: `act` becomes
`buy` (or `sell` when the direction is down).

## `premarket.json`: pre-market panel

See `premarket.sample.json` for every field. In short:

- `updated`, `sentiment` ("Mildly bearish"), `breadth` (`{"up": 2, "down": 3}`)
- `checklist`: items with `title`, `dir` (`up`/`down`/`flat`), `value`, `detail` (lines)
- `summary`, `global_cues`, `india_triggers` (bullets)
- `focus` (`[{symbol, note}]`), `sector_tags` (`[{label, tone: positive|negative|watch}]`)
- `key_risk`, `also` (`[{name, value, change}]`, change in %)

Visitors' checklist ticks are saved per day in their own browser.

## `universe.json`: stock list

Download `ind_nifty500list.csv` from niftyindices.com and run:

```
python pulsedge-bot/universe_from_nse.py ind_nifty500list.csv
```

## Sending data by hand

A spreadsheet works. Use the field names above as column headers, put
multiple tickers in one cell like `ONGC OIL -BPCL -HINDPETRO` (a leading `-`
means negative), and send it as CSV.

## Trials and access links

The terminal (`terminal.html`) opens for people with a free trial or an access link; everyone else sees
the sample data and a sign-up card. The logic is in `assets/member.js`.

- **Free trial:** a visitor enters their email and gets 5 NSE trading sessions (about a week) in that
  browser. The email goes to Formspree with `source: "trial"`.
- **Access links:** `terminal.html#pass=…`, made in PulsEdge HQ (or `pulsedge-bot/issue_pass.js`) and
  signed with a private key that never leaves the device that made it. Plans: `trial7` and `trial14`
  (5 or 10 trading sessions from a start date), `monthly`, `yearly`, `founding` and `comp` (valid until
  a date). A link only opens if its key's public half is in `keys.json` and its id isn't in `revoked.json`.
- Weekends and the holidays in `calendar.json` don't count. A trial ends when trading opens on the day
  after its last session. Update `calendar.json` every December from NSE's holiday circular.
- This is a front-end gate for the beta: the data files themselves are public. Real logins come later.
