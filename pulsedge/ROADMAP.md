# PulsEdge roadmap

## Waiting on you

These unblock the next steps. Claude will ask for each one when it's needed.

- [ ] **News signals (tonight).** CSV or JSON in the signal format in `data/README.md` (call, horizon, tickers, impact, confidence, action…). Goes in `data/feed.json`.
- [ ] **Pre-market data.** The morning checklist values (GIFT Nifty, US close, Asia, DXY/USDINR, Brent, VIX, FII/DII) for `data/premarket.json`.
- [ ] **Nifty 500 list.** `ind_nifty500list.csv` from niftyindices.com, for `data/universe.json`.
- [ ] **Telegram bot token.** Message @BotFather, send `/newbot`, then add the bot as an admin of the channel. Save the token as the repository secret `TELEGRAM_BOT_TOKEN`. Never paste it in chat.
- [ ] **Anthropic API key**, for the automated news pipeline. Create it at console.anthropic.com and save it as the repository secret `ANTHROPIC_API_KEY`.
- [ ] **Call wording decision.** BUY / SELL calls on named stocks are the most likely to fall under SEBI's Research Analyst rules. Decide before public launch whether to register, get a compliance opinion, or soften the wording.

## Done

- Landing page with watchlist, broker CSV import, signups (Formspree) and GitHub Pages deploy
- PULSE terminal (`terminal.html`): status bar, pre-market checklist panel, signal feed with Trade ideas / Watch / RedBox / Filings / My stocks tabs
- Telegram signal-card renderer and poster (`pulsedge-bot/pulse_bot.py`), plus a workflow that posts new BUY/SELL signals when `data/feed.json` changes

## Next

1. Live news pipeline: scheduled GitHub Action that collects SEBI/RBI/BSE/NSE and newswire headlines, classifies them with Claude into per-stock impacts, and writes `data/feed.json`
2. Personal Telegram alerts: a bot users message with their holdings (needs a small server and database)
3. Custom domain (pulsedge.in), when you're ready to pay for it
