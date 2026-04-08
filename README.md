# Hormuz Alert Bot

A real-time Telegram alert system for high-impact events affecting the
Strait of Hormuz — the world's most critical oil transit chokepoint.

---

## How it works

A lightweight Python process polls Reuters and AP every 5 minutes. Each
article is matched against a tiered keyword list defined in `config.yaml`.
Only articles implying an actual change in status trigger an alert — static
situation reporting is ignored by design.

```
Reuters RSS  ─┐
              ├─▶  classify  ─▶  deduplicate  ─▶  Telegram
AP RSS       ─┘
```

**Alert tiers:**

| Tier | Examples | Notifies |
|---|---|---|
| 🚨 CRITICAL | Strait reopens, tanker seized, ceasefire collapses, mine detected | Yes |
| ⚠️ HIGH IMPACT | Ceasefire announced, sanctions, oil surges, carrier suspends | Yes |
| 📡 UPDATE | Any other Hormuz mention | Silent (logged only) |

All behaviour — feeds, keywords, tiers, intervals — is controlled via
`config.yaml`. No code changes needed for tuning.

---

## Stack

- Python 3.11+
- `feedparser` — RSS ingestion
- `requests` — Telegram Bot API
- `pyyaml` — config parsing
- `uv` — dependency management
- Railway — deployment (see hosting note in [`docs/architecture.md`](docs/architecture.md))

---

## Project structure

```
hormuz-alert-bot/
├── main.py              # Bot engine — poll, classify, alert
├── config.yaml          # All behaviour lives here — edit this, not main.py
├── pyproject.toml       # Dependencies (uv)
├── railway.toml         # Deployment config
├── .env.example         # Environment variable template
├── .gitignore
├── docs/
   └── architecture.md  # Source decisions, roadmap, AIS pipeline spec
```

---

## Setup

See **[SETUP.md](SETUP.md)** for the full step-by-step guide covering:
- Creating a Telegram bot via @BotFather
- Local development on macOS
- Deployment to Railway

Short version:

```bash
# 1. Install dependencies
uv sync

# 2. Set secrets
cp .env.example .env
# edit .env with your TELEGRAM_TOKEN and TELEGRAM_CHAT_ID

# 3. Run
python main.py
```

---

## Configuration

`config.yaml` is the only file you need to edit. It controls:

- `topic` — label shown in every Telegram alert
- `check_interval_minutes` — how often to poll feeds
- `alert_cooldown_hours` — minimum gap between alerts for the same story
- `tiers` — keyword lists per severity level, each with `notify: true/false`
- `feeds` — list of RSS URLs to monitor

To silence a tier: set `notify: false`. To add a keyword: append to the
list. To add a feed: append a URL. No Python knowledge required.

This bot is intentionally generic — swap `config.yaml` to monitor any
topic (Red Sea, Taiwan Strait, Gaza ceasefire) with zero code changes.

---

## Source rationale

We use Reuters and AP exclusively. Both are wire services with 24/7
regional correspondents and editorial discipline — they don't publish
until a report is confirmed.   
General news sites (BBC, Al Jazeera, Google
News) were evaluated and removed: they republish wire copy with additional
latency, producing duplicate alerts without adding signal.

Full reasoning in [`docs/architecture.md`](docs/architecture.md).

---

## Roadmap

**Phase 2 — UKMTO via X/Twitter RSS**
The UK Maritime Trade Operations centre (@UK_MTO) is the authoritative
military maritime security source for the Gulf region. Their posts are
faster and more operationally precise than any news publication. Phase 2
adds their feed via a self-hosted RSSHub instance on Fly.io.

**Phase 3 — AIS real-time stream**
Replace news-derived alerts with ground truth: actual vessel movement
data through the strait via the `aisstream.io` WebSocket API. A gate
line across the narrowest point of the strait detects inbound/outbound
transits by MMSI. A rolling anomaly detector alerts on sustained spikes
or drops in transit counts — independent of what any government is saying.

Full architecture spec, tech stack, and implementation plan:
[`docs/architecture.md`](docs/architecture.md)

---

## Contributing

Issues and PRs welcome. If you're adding a new data source, please
document the rationale in `docs/architecture.md` — why this source,
what it adds that existing sources don't cover, and any known limitations.

---

## Disclaimer

This project is for informational purposes only. Do not use it as a
sole basis for navigation, trading, or operational decisions.
