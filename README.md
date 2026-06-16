# EU Regulatory Early-Warning Monitor (multi-source)

Aggregates three official, no-auth EU sources, scores each new item against your
watchlist with the Anthropic API (relevance 0-100, tier, plain-language summary,
suggested owner), de-duplicates, and posts the relevant ones to **Slack or
Microsoft Teams**.

## Tailored for a multinational tech / consumer-electronics company

The watchlist is organised **by product line**, not as one flat list. Three
**device** lines carry the device-specific frameworks and all route to Hardware
regulatory; two **cross-cutting** lines catch items that are primarily about data
or security regardless of device and route to the specialist team. The scorer
picks the single best-matching line per item.

| Product line (key) | Covers | Routes to |
|--------------------|--------|-----------|
| `mobile_phones` | RED + common charger, smartphone ecodesign/energy label, batteries, EMC/LVD, GPSR, WEEE/RoHS | Regulatory |
| `visual_displays` | Electronic Displays ecodesign (EU 2019/2021) + energy label, the live displays review, ESPR/DPP, standby, smart-TV RED | Regulatory |
| `digital_appliances` | Fridge/washer/dishwasher/dryer ecodesign + energy labels, ESPR/DPP, right-to-repair, smart-appliance RED | Regulatory |
| `network_devices` | RED, EMC/LVD, EECC + BEREC, spectrum, 5G security toolbox, CRA/NIS2, EMF limits | Regulatory |
| `medical_devices` | MDR (2017/745), IVDR (2017/746), EUDAMED/UDI, SaMD↔AI Act, MDCG guidance, notified bodies, PMS/vigilance | Medical |
| `multimedia_services` | AVMSD + 2026 review, smart-TV prominence, content accessibility, European Accessibility Act, DSM Copyright, VSP | Data Privacy |
| `data_and_ai` | GDPR, AI Act, Data Act, DGA, ePrivacy, DSA, DMA | Data Privacy |
| `product_security` | Cyber Resilience Act, NIS2, RED 3.3(d/e/f), RED→CRA transition, Cybersecurity Act | Security |

So a phone's energy-label item lands on `mobile_phones` (→ Regulatory), while a
phone-relevant AI Act item lands on `data_and_ai` (→ Data Privacy). A smart-TV
*device* rule (ecodesign, energy label) lands on `visual_displays` (→ Regulatory), while a
smart-TV *content/service* rule (AVMSD prominence, content accessibility) lands on
`multimedia_services` (→ Data Privacy). The EU regulates TVs and monitors/signage
as one "electronic displays" category, so they share the `visual_displays` line.
Everything still posts to **one shared channel** — the product-line tag and owner
appear on each alert card so the right team self-triages.

To retune: edit the `product_lines` section of `config.yaml` — add/remove
frameworks, rename owners, or add a whole new device line. No code changes
needed. The legacy flat `watchlist:` + `owners:` format still works too.

> **Medical-device coverage note.** MDR/IVDR legislation and amendments are
> published in EUR-Lex, so the `CELLAR` source catches them, and the Have Your
> Say / OEIL sources catch related proposals (e.g. the 2026 MDR/IVDR
> simplification proposal). However, a lot of operational medical-device
> material lives *outside* EUR-Lex — MDCG guidance documents, EUDAMED
> announcements, and notified-body updates on the Commission health pages. Those
> are not currently polled. If medical devices are a major line for you, consider
> adding the Commission health-DG MDCG guidance page and the EUDAMED news feed as
> extra sources later; the scoring/notify pipeline would reuse unchanged.

## The three sources — and which stage of the lifecycle each covers

| Source | Code | Lifecycle stage caught | Access method |
|--------|------|------------------------|---------------|
| **Have Your Say** | `HYS` | **Earliest** — consultations, calls for evidence, roadmaps | Frontend JSON service, with RSS fallback |
| **Legislative Observatory (OEIL)** | `OEIL` | **Middle** — procedures moving through Parliament/Council | Search RSS (discover) + procedure-file (watch) |
| **EUR-Lex / CELLAR** | `CELLAR` | **Final** — published & adopted legal acts | CELLAR SPARQL endpoint |

Together they give true early warning: you see a file as a consultation, again as
it advances through readings, and finally as published law — each routed to a
suggested owner with a tier.

## Files
| File | Purpose |
|------|---------|
| `eu_reg_watch.py` | orchestrator: assemble sources → score → dedup → notify |
| `sources.py` | the three pluggable sources |
| `config.sample.yaml` | copy to `config.yaml` and edit |
| `.github/workflows/watch.yml` | scheduled GitHub Actions run |

## Setup
```bash
pip install requests pyyaml feedparser
cp config.sample.yaml config.yaml
# edit config.yaml: profile, watchlist, owners, source toggles, webhook(s)
export ANTHROPIC_API_KEY=sk-ant-...
python eu_reg_watch.py --dry-run --lookback-days 7   # poll+list, no spend, no posts
python eu_reg_watch.py --lookback-days 7             # full run
```
Dry run requires outbound access to `publications.europa.eu`,
`have-your-say.ec.europa.eu`, and `oeil.secure.europarl.europa.eu`.

## Configuring OEIL (two modes, use either or both)
- **Discover** — on the OEIL site, build a search (filter by your subjects /
  procedure types / stage), then copy the **RSS** link from the results page into
  `oeil.search_rss`. Newly active or updated matching procedures get scored.
- **Watch** — list specific procedure references (e.g. `2023/0212(COD)`) in
  `oeil.watch_references` to follow named files. A file **re-posts only when its
  stage advances** (1st reading → 2nd reading → adopted), never on every run.

## How tiering works
The model uses each item's source + stage hint to assign:
- 🔴 **ACTIVE** — published / in force / concrete deadline (mostly CELLAR)
- 🟠 **PIPELINE** — in readings or adopted-not-yet-applying (mostly OEIL)
- 🟡 **HORIZON** — consultation / call for evidence (mostly HYS)

An item posts only if `relevance >= relevance_threshold` **and** it matched at
least one watchlist topic.

## Scheduling
Run more often than the lookback window so nothing slips through a gap; the
SQLite store makes overlap safe (no duplicate posts). Daily with
`--lookback-days 3` gives two days of overlap. See `.github/workflows/watch.yml`;
persist `seen.sqlite` between runs (cache/artifact) so dedup survives.

## Resilience notes
- Each source is isolated: if one endpoint is down, the run logs a warning and
  continues with the others.
- HYS falls back from its JSON service to RSS automatically if the JSON shape
  changes or is unavailable.
- All HTTP calls retry with exponential backoff on 429/503 (CELLAR rate-limit
  guidance: single connection, backoff).
- Scoring runs on **Sonnet**, the appropriate default for classification + short
  summaries at this volume. Reserve a heavier model only if you later add deep
  full-text impact analysis of high-tier acts.

## Important caveat
This is an early-warning and triage aid, **not legal advice or a compliance system
of record**. LLM relevance scores and summaries — and OEIL/HYS stages parsed from
public pages — should be reviewed by your legal/compliance owner before any action.
The unofficial HYS JSON endpoint and OEIL page structure can change; the RSS
fallbacks and isolated-source design limit the blast radius if they do.
