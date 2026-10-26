# PulsEdge roadmap

## Waiting on you

These unblock the next steps. Claude will ask for each one when it's needed.

- [ ] **Turn GitHub Actions back on.** Settings → Actions → General → "Allow all actions and reusable workflows", then "Enable workflows" on the Actions tab. Nothing updates while it's off.
- [ ] **Free AI key.** Get a Gemini key at aistudio.google.com and save it as the repository secret `AI_API_KEY`. Without it, calls come from keyword rules and never count towards the track record.
- [ ] **Telegram bot token.** Revoke the old token in @BotFather and make a new one. Save it as the repository secret `TELEGRAM_BOT_TOKEN` (never in chat), and make @pulsedge_signals_bot an admin of @pulsedgein.
- [ ] **Razorpay.** Create an account and finish KYC, then make a ₹499/month and a ₹3,999/year Subscription link (or Payment Page). Set `welcome.html` as the redirect after payment, and send both links. They go in `PAY_LINKS` in `index.html`.
- [ ] **Supabase account** (free), so the terminal can require a login and only members see it. Paid members get added automatically from Razorpay.
- [ ] **Call wording decision.** BUY / SELL calls on named stocks are the most likely to fall under SEBI's Research Analyst rules. Decide before public launch whether to register, get a compliance opinion, or soften the wording.
- [ ] **HQ signing key.** In PulsEdge HQ open Playbook → Access links → Create signing key, back it up, then ask Claude to register it. Until then, links made in HQ won't open.
- [ ] **Business name and address** for the contact page (Razorpay's website review asks for them).
- [ ] **Screen recording** of the reference site, for the scroll-animation redesign.

The full checklist (launch, payments, compliance, growth and routines) lives in PulsEdge HQ.

## Done

- Landing page with watchlist, broker CSV import, signups (Formspree) and GitHub Pages deploy
- Pricing section (founding 15 seats, ₹499/month, ₹3,999/year) with Razorpay-ready buttons, and `welcome.html` for after payment
- Waitlist page and terminal are separate pages; the waitlist no longer links to the terminal
- PULSE terminal (`terminal.html`): status bar, pre-market checklist panel, signal feed with Trade ideas / Watch / RedBox / Filings / My stocks tabs
- Live news pipeline (`pulsedge-bot/news_pipeline.py`): SEBI, RBI, NSE announcements and market news every 15 minutes in market hours, Nifty 500 ticker matching, AI or keyword-rule classification
- Live pre-market panel (`pulsedge-bot/premarket.py`) from CNBC quotes, Yahoo as fallback
- Track record (`track.html`, `pulsedge-bot/track_record.py`): every Watch/Act call on a named stock checked against NSE closes 1 and 5 sessions later
- Free trial and access links on the terminal (`assets/member.js`): 5-session self-serve trial, signed links for 10-session trials, paid, founding and guest plans, NSE holiday calendar, sample-data mode, feedback form
- Terms, Privacy, Refunds & delivery, and Contact pages (needed for Razorpay KYC); free-trial entry in pricing and nav
- Landing page redesign: live product preview with scroll-flattening tilt, live triage numbers, four-step scroll story, real-feed demo, audit trail, track record teaser, FAQ; site-wide IBM Plex Sans with Plex Mono for data
- PulsEdge HQ (private claude.ai page): CRM, access-link issuing, email templates, revenue and GST tracking, launch and compliance checklist
- Telegram signal-card renderer and poster (`pulsedge-bot/pulse_bot.py`), plus a workflow that posts new BUY/SELL signals when `data/feed.json` changes

## Next

1. Members-only terminal: Supabase login, members list, signal data moved out of the public repo, Razorpay webhook that adds paying members
2. Reliable schedule: an outside timer (e.g. cron-job.org) that starts the news workflow every 15 minutes, since GitHub's own schedule fires irregularly
3. Personal Telegram alerts: a bot users message with their holdings (needs a small server and database)
4. Custom domain (pulsedge.in), when you're ready to pay for it
