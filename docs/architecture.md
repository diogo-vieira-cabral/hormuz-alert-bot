# Architecture & Roadmap

This document covers the technical decisions behind the current system,
why certain sources and approaches were chosen or rejected, and the
planned phases for extending the bot into a proper real-time data pipeline.

---

## Current System (Phase 1)

### What it does

A lightweight Python process that polls two RSS feeds every 5 minutes,
classifies articles against a tiered keyword list defined in `config.yaml`,
and sends a Telegram alert when a match is found. Runs as a persistent
background worker on Railway.

### Architecture

```
Reuters RSS  ─┐
              ├─▶  main.py (poll → classify → deduplicate) ─▶  Telegram Bot API
AP RSS       ─┘
```

State is in-memory only. No database. On restart, the bot re-seeds seen
articles from current feed contents to avoid replaying old news. This is
intentional — the bot is a notification system, not a data store.

### Source decisions

**Kept:**
- **Reuters World News** (`feeds.reuters.com/reuters/worldNews`)
  Wire service with 24/7 regional correspondents. Editorially disciplined —
  does not publish until confirmed. Typically under 5 minutes from event to feed.
- **AP Top News** (`feeds.apnews.com/rss/apf-topnews`)
  Independent sourcing from Reuters. Catches events where one wire is slower
  than the other. Both together give near-complete coverage of major events.

**Removed:**
- **Google News (3 feeds)** — aggregates and republishes wire copy with
  additional latency. Added duplicate alerts without adding signal.
- **Al Jazeera, BBC** — secondary publishers. By the time a story appears
  here, Reuters or AP have already published it. Pure delay.
- **oilprice.com, offshore-energy.biz** — trade press. Slow update cycles,
  high noise, editorial opinion mixed with news. Wrong tool for alerts.

**Keyword philosophy:**
Keywords must signal *change*, not static situation. "hormuz" matches
"the strait remains closed today" — which is not an alert-worthy event.
"reopens", "seized", "ceasefire collapses" only match when something
actually changes. This distinction eliminates the majority of noise.

---

## Phase 2 — UKMTO via X/Twitter RSS (Planned)

### What UKMTO is

The United Kingdom Maritime Trade Operations centre is the authoritative
military maritime security authority for the Indian Ocean / Gulf region.
When they post, it is verified and operationally significant. During the
2026 crisis they have been issuing warnings and advisories faster than
any news publication.

### The access problem

UKMTO publishes via their website (PDF advisories, no RSS) and their
X/Twitter account (@UK_MTO). Twitter/X killed public RSS access in 2023.

### Approach: RSSHub

[RSSHub](https://github.com/DIYgod/RSSHub) is an open-source RSS feed
generator that can produce an RSS feed from any X account. It works by
scraping the public timeline. The feed URL for @UK_MTO would be:

```
https://rsshub.app/twitter/user/UK_MTO
```

**Option A — Public RSSHub instance (`rsshub.app`)**
- Zero setup, free
- Unreliable: rate-limited, frequently down, no SLA
- Acceptable for low-stakes use, not for a production alert system

**Option B — Self-hosted RSSHub on Fly.io**
- Fly.io has a genuine permanent free tier (unlike Railway's credit system)
- Deploy RSSHub as a Docker container: `flyctl launch --image diygod/rsshub`
- Your bot points to your own instance — stable, under your control
- Setup time: ~30 minutes

### Hosting note on Railway

Railway operates on a credit system, not a true free tier. A lightweight
Python process consuming ~0.1 vCPU and ~50MB RAM burns approximately
$0.50–$1.00 of credit per week. The $5 free credit lasts roughly 5–10 weeks.

**Recommended long-term hosting:**
- **Fly.io** — permanent free tier for small apps, better fit for persistent workers
- **Oracle Cloud Free Tier** — permanent, 2 ARM VMs, generous compute
- Both are documented in `SETUP.md` once migration is needed

### Implementation plan

1. Deploy RSSHub on Fly.io (or use public instance for testing)
2. Add UKMTO feed URL to `config.yaml` feeds list — no code changes needed
3. Add UKMTO-specific keywords to CRITICAL tier:
   - "warning", "attack", "boarding", "hijack" (UKMTO standard terminology)
4. Monitor for a week and tune

---

## Phase 3 — AIS Real-Time Stream (Planned)

### Why AIS matters

News articles report *about* events. AIS data *is* the event — actual vessel
movement through the strait in real time. A sustained rise in daily transits
from 3 to 40 means the strait is reopening, regardless of what any government
is saying. This is ground truth.

### Ship identity — the primary key problem (solved)

Each AIS transmission includes:
- **MMSI** (Maritime Mobile Service Identity) — 9-digit unique vessel ID,
  permanent, assigned by the flag state authority. This is the primary key.
- **IMO number** — separate permanent identifier issued at construction
- **Vessel name, callsign, type, dimensions** — supplementary fields

MMSI is reliable for deduplication. A transit detected twice from the same
MMSI within a short window is the same ship, not two events. This was
validated by the open-source Raspberry Pi tracker built during the 2026
crisis (reference: dev.to/yasumorishima).

### Data source: aisstream.io

[aisstream.io](https://aisstream.io) provides a free WebSocket API that
aggregates terrestrial AIS receiver data globally. No paid tier required
for this use case.

**Limitation:** terrestrial receivers have limited open-water coverage.
Mid-strait coverage is partial — vessels far from shore may not appear.
Additionally, vessels in a war zone deliberately disable AIS to avoid
targeting. Transit counts are therefore a **lower bound** — the real
number is always ≥ what we observe. The trend signal remains valid.

### Gate line concept

A gate line is a virtual line segment drawn across the narrowest point
of the strait (approximately 26.5°N, 56.3°E to 26.2°N, 56.5°E). The
pipeline detects when a vessel's position crosses this line — direction
of crossing (inbound/outbound) determined by bearing.

```
         Persian Gulf
              │
    ──────────┼──────────  ← gate line (~26.4°N)
              │
         Gulf of Oman
```

### Pipeline architecture

```
aisstream.io WebSocket
        │
        ▼
  Stream Collector
  - Filter: bounding box around strait (26.0–27.0°N, 55.8–57.0°E)
  - Filter: vessel types (tanker, cargo, bulk carrier — exclude military/pleasure)
  - Filter: speed > 2 knots (exclude anchored vessels)
  - Deduplicate: MMSI + 30-min window
        │
        ▼
  Gate Line Detector
  - Input: vessel position sequence per MMSI
  - Logic: detect crossing of gate line segment
  - Output: transit event {mmsi, vessel_name, type, direction, timestamp}
        │
        ▼
  Time-Series Store (SQLite, local file)
  - Table: transits(mmsi, vessel_name, vessel_type, direction, crossed_at)
  - Table: hourly_counts(hour_utc, inbound, outbound, total)
        │
        ▼
  Anomaly Detector
  - Baseline: rolling 24h average transit count
  - Alert trigger: current hour count > 3x baseline (reopening signal)
  - Alert trigger: current hour count = 0 for 4+ consecutive hours (closure signal)
        │
        ▼
  Telegram Alert (same bot infrastructure as Phase 1)
```

### Tech stack

| Component | Choice | Reason |
|---|---|---|
| WebSocket client | `websockets` (Python async) | Native async, minimal deps |
| Geospatial math | `shapely` | Line crossing detection |
| Storage | SQLite via `sqlite3` (stdlib) | Zero ops, sufficient for this volume |
| Anomaly detection | Rolling window, stdlib only | No ML needed — simple thresholds work |
| Orchestration | Single async Python process | Keeps deployment identical to Phase 1 |

### Data volume estimate

At normal traffic (~60 vessels/day through the strait), AIS messages
for the bounding box are roughly 500–2,000 messages/hour. During a
crisis with most vessels anchored, significantly less. SQLite handles
this without issue. No streaming infrastructure (Kafka, Flink, etc.)
is needed or appropriate at this scale — that would be over-engineering.

### What makes this a data engineering project

- Real-time stream ingestion via WebSocket
- Geospatial filtering and event detection (gate line crossing)
- Time-series storage with a defined schema
- Anomaly detection against a rolling baseline
- Event-driven alerting from derived data, not raw text

These are four distinct engineering concerns implemented cleanly and
composably. The fact that it runs on a Raspberry Pi or a free cloud
instance is a feature, not a limitation — it demonstrates efficiency.

### Implementation order (when ready to build)

1. `ais_collector.py` — WebSocket connection, bounding box filter, raw position logging
2. Validate MMSI deduplication works correctly against live data (1–2 days of observation)
3. `gate_detector.py` — gate line crossing logic, unit tested
4. SQLite schema and writer
5. `anomaly.py` — rolling baseline and threshold alerting
6. Wire into existing Telegram alert infrastructure
7. Deploy alongside Phase 1 bot (same Railway/Fly.io project, second process)
