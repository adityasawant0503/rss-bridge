# PulsEdge roadmap

## Waiting on you

These unblock the next steps. Claude will ask for each one when it's needed.

- [ ] **News data (tonight).** A CSV with `time, headline, verdict, section, tickers, category, horizon, reason, source, url`, or JSON with per-stock `impacts` (format in `data/README.md`). Goes in `data/feed.json`.
- [ ] **Nifty 500 list.** `ind_nifty500list.csv` from niftyindices.com, for `data/universe.json`.
- [ ] **Telegram bot token.** Message @BotFather, send `/newbot`, then add the bot as an admin of the channel. Save the token as the repository secret `TELEGRAM_BOT_TOKEN`. Never paste it in chat.
- [ ] **Anthropic API key**, for the automated news pipeline. Create it at console.anthropic.com and save it as the repository secret `ANTHROPIC_API_KEY`.
- [ ] **Verdict wording decision.** Keep ACT / WATCH / IGNORE, or soften it before public launch because of SEBI's Research Analyst rules.

## Done

- Landing page with watchlist, broker CSV import, signups (Formspree) and GitHub Pages deploy
- Terminal page (`terminal.html`): news → stock impact stream, impact detail, sector heat, impact tracker, watchlist shared with the site
- Telegram card renderer and poster (`pulsedge-bot/pulse_bot.py`), plus a workflow that posts new ACT events when `data/feed.json` changes

## Next

1. Live news pipeline: scheduled GitHub Action that collects SEBI/RBI/BSE/NSE and newswire headlines, classifies them with Claude into per-stock impacts, and writes `data/feed.json`
2. Personal Telegram alerts: a bot users message with their holdings (needs a small server and database)
3. Custom domain (pulsedge.in), when you're ready to pay for it
