# PulsEdge feed data

The website reads `data/feed.json`. When that file is missing or has no items,
the feed shows sample headlines instead. Add the file, push to `master`, and the
site switches to your data within a couple of minutes. Open pages re-check it
every two minutes.

`feed.example.json` in this folder is a filled-in example. Copy it to
`feed.json` to try it out.

## Format

```json
{
  "updated": "2026-10-20T16:30:00+05:30",
  "items": [ ... ],
  "digest": { ... }
}
```

| Field     | Required | Meaning                                                   |
|-----------|----------|-----------------------------------------------------------|
| `updated` | no       | When the file was generated (ISO 8601). Shown in the feed header in IST. |
| `items`   | yes      | One entry per headline, any order. The site sorts newest first and keeps the latest 300. |
| `digest`  | no       | Numbers for the "Daily digest" card. Without it the card shows the sample. |

### Each item

| Field      | Required | Values / example                                   |
|------------|----------|----------------------------------------------------|
| `headline` | yes      | `"TCS: board approves Q2 results"`                 |
| `time`     | yes      | ISO 8601 with offset, `"2026-10-20T10:42:00+05:30"` |
| `verdict`  | yes      | `act`, `watch` or `ignore`                         |
| `section`  | yes      | `trading`, `news` or `macro`                       |
| `tickers`  | no       | NSE symbols it affects, `["TCS"]`. This is what matches a visitor's holdings. Leave empty for market-wide items. |
| `category` | no       | Short label, `"Earnings"`                          |
| `affected` | no       | Who it touches when there's no single stock, `"Banks, NBFCs"` |
| `horizon`  | no       | `days`, `weeks`, `months`, `quarter`, `multi-quarter`. Defaults to `skip` for ignored items. |
| `reason`   | no       | One sentence on why this verdict. Shown when a visitor taps the headline. |
| `source`   | no       | `"NSE"`, `"BSE"`, `"SEBI"`, `"RBI"`, a newswire name |
| `url`      | no       | Link to the original filing or article (`http`/`https` only) |
| `id`       | no       | Stable unique id. Keeps visitors' agree/disagree votes attached to the right headline across updates. |

Unknown `verdict` values are shown as `ignore`; unknown `section` values as `news`.

### Digest

| Field     | Meaning                                         |
|-----------|-------------------------------------------------|
| `date`    | Trading day, `"2026-10-20"`                      |
| `act`, `watch`, `ignored` | Counts for the day                 |
| `reasons` | Up to 6 `{ "label": "...", "count": 0 }` rows explaining what was ignored |

## Sending data by hand

If you are collecting headlines in a spreadsheet for now, use these columns and
send the sheet as CSV; it converts straight into this format:

`time, headline, verdict, section, tickers, category, horizon, reason, source, url`

Put multiple tickers in one cell separated by spaces, e.g. `HDFCBANK ICICIBANK`.
