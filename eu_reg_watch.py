#!/usr/bin/env python3
"""
EU Regulatory Early-Warning Monitor (multi-source)
--------------------------------------------------
Aggregates three official, no-auth EU sources, scores each new item against your
watchlist with the Anthropic API, de-duplicates, and posts relevant items to
Slack / Microsoft Teams.

Sources
  CELLAR  - published / adopted legal acts (EUR-Lex)
  HYS     - Commission consultations & calls for evidence (earliest stage)
  OEIL    - European Parliament Legislative Observatory procedure tracking

Run on a schedule. Config in config.yaml (see config.sample.yaml).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import time
from typing import Any

import requests
import yaml

from sources import Act, CellarSource, HaveYourSaySource, OeilSource

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-sonnet-4-6"  # right default: classify + summarise, cheap & fast


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #
def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS seen (
               uid TEXT PRIMARY KEY,
               source TEXT,
               first_seen TEXT,
               relevance INTEGER,
               tier TEXT,
               posted INTEGER DEFAULT 0
           )"""
    )
    conn.commit()
    return conn


def is_new(conn: sqlite3.Connection, uid: str) -> bool:
    return conn.execute("SELECT 1 FROM seen WHERE uid = ?", (uid,)).fetchone() is None


def mark_seen(conn: sqlite3.Connection, act: Act, posted: bool) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO seen (uid, source, first_seen, relevance, tier, posted) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (act.uid, act.source, dt.datetime.utcnow().isoformat(),
         act.relevance, act.tier, int(posted)),
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
SCORING_SYSTEM = """You are a regulatory analyst for a Korean technology company \
operating in the EU. For each EU item you receive - which may be a published legal \
act, an open public consultation, or a legislative procedure in progress - judge how \
relevant it is to the company given its watchlist, and return strict JSON only."""

SCORING_TEMPLATE = """Company profile:
{profile}

This company organises its EU regulatory exposure into PRODUCT LINES. Each line
lists the EU frameworks that govern it and the internal owner responsible.

Product lines and their frameworks:
{product_lines}

Source of this item: {source}
Stage hint: {stage}

Your task: decide whether the item below is relevant to ANY product line, which
line(s) it touches, how relevant it is, and which owner should act.

Tier definitions (assign based on how close to applying, using the stage hint):
- HORIZON: consultation, call for evidence, or early preparatory procedure (1-3 yrs out)
- PIPELINE: procedure in Parliament/Council readings, adopted-but-not-yet-in-force
- ACTIVE: published act in force or with a concrete compliance/application deadline

Item under review:
- Title: {title}
- Date: {date}
- Extra context: {extra}

Return ONLY this JSON object, no prose, no markdown fences:
{{"relevance": <integer 0-100>,
  "product_line": "<the single best-matching product-line KEY from the list above, or 'none'>",
  "tier": "<HORIZON|PIPELINE|ACTIVE>",
  "topics": "<comma-separated specific frameworks/topics matched, or 'none'>",
  "summary": "<2 sentence plain-language summary of what it is and why it matters to this product line>",
  "owner": "<the owner of the matched product line, copied exactly; if none, use {default_owner}>"}}"""


def _render_product_lines(cfg: dict) -> tuple[str, dict]:
    """Build the prompt text for product lines and a key->owner lookup.
    Falls back to the legacy flat `watchlist` if `product_lines` is absent."""
    lines = cfg.get("product_lines")
    owner_by_key: dict[str, str] = {}
    if not lines:
        # Backward compatibility: synthesise a single group from a flat watchlist.
        wl = cfg.get("watchlist", [])
        owners = cfg.get("owners", [])
        text = "general (key: general)\n  owner: " + (owners[0] if owners else "Compliance")
        text += "\n  frameworks:\n" + "\n".join(f"    - {w}" for w in wl)
        owner_by_key["general"] = owners[0] if owners else "Compliance"
        return text, owner_by_key
    blocks = []
    for key, grp in lines.items():
        owner = grp.get("owner", cfg.get("default_owner", "Compliance"))
        owner_by_key[key] = owner
        fw = "\n".join(f"    - {f}" for f in grp.get("frameworks", []))
        blocks.append(f"{grp.get('label', key)} (key: {key})\n  owner: {owner}\n  frameworks:\n{fw}")
    return "\n\n".join(blocks), owner_by_key


def score_act(act: Act, cfg: dict, api_key: str) -> Act:
    pl_text, owner_by_key = _render_product_lines(cfg)
    prompt = SCORING_TEMPLATE.format(
        profile=cfg["company_profile"],
        product_lines=pl_text,
        default_owner=cfg.get("default_owner", "Compliance"),
        source=act.source,
        stage=act.stage or "n/a",
        title=act.title,
        date=act.date,
        extra=json.dumps(act.extra, ensure_ascii=False)[:800],
    )
    body = {
        "model": cfg.get("model", ANTHROPIC_MODEL),
        "max_tokens": 600,
        "system": SCORING_SYSTEM,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    r = requests.post(ANTHROPIC_URL, headers=headers, data=json.dumps(body), timeout=60)
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json().get("content", [])
                   if b.get("type") == "text").strip()
    text = text.replace("```json", "").replace("```", "").strip()
    try:
        parsed = json.loads(text)
        act.relevance = int(parsed.get("relevance", 0))
        act.tier = parsed.get("tier")
        act.topics = parsed.get("topics")
        act.summary = parsed.get("summary")
        act.product_line = parsed.get("product_line")
        # Trust the configured owner mapping over the model's free-text owner,
        # so routing stays consistent with the config. A 'none'/blank product
        # line falls back to the configured default owner.
        key = (act.product_line or "").strip()
        if key and key.lower() != "none" and key in owner_by_key:
            act.owner = owner_by_key[key]
        else:
            act.owner = cfg.get("default_owner", "Compliance")
    except (json.JSONDecodeError, ValueError) as e:
        print(f"[warn] could not parse scoring for {act.uid}: {e}", file=sys.stderr)
        act.relevance = 0
    return act


# --------------------------------------------------------------------------- #
# Notification
# --------------------------------------------------------------------------- #
TIER_EMOJI = {"ACTIVE": "\U0001F534", "PIPELINE": "\U0001F7E0", "HORIZON": "\U0001F7E1"}
SOURCE_LABEL = {"CELLAR": "EUR-Lex (published)",
                "HYS": "Have Your Say (consultation)",
                "OEIL": "Leg. Observatory (procedure)"}


def post_slack(webhook: str, act: Act) -> None:
    emoji = TIER_EMOJI.get(act.tier, "\u26AA")
    payload = {"blocks": [
        {"type": "header",
         "text": {"type": "plain_text",
                  "text": f"{emoji} {act.tier} - {act.relevance} - {SOURCE_LABEL.get(act.source, act.source)}"}},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": f"*<{act.url}|{act.title}>*\n{act.summary}"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Product line:*\n{act.product_line or 'n/a'}"},
            {"type": "mrkdwn", "text": f"*Stage:*\n{act.stage or 'n/a'}"},
            {"type": "mrkdwn", "text": f"*Date:*\n{act.date or 'n/a'}"},
            {"type": "mrkdwn", "text": f"*Topics:*\n{act.topics}"},
            {"type": "mrkdwn", "text": f"*Suggested owner:*\n{act.owner}"},
        ]},
    ]}
    requests.post(webhook, json=payload, timeout=30).raise_for_status()


def post_teams(webhook: str, act: Act) -> None:
    emoji = TIER_EMOJI.get(act.tier, "\u26AA")
    payload = {
        "@type": "MessageCard", "@context": "http://schema.org/extensions",
        "summary": f"{act.tier} EU item: {act.title}",
        "themeColor": {"ACTIVE": "D70000", "PIPELINE": "E8821E",
                       "HORIZON": "E8C61E"}.get(act.tier, "808080"),
        "title": f"{emoji} {act.tier} - relevance {act.relevance} - {SOURCE_LABEL.get(act.source, act.source)}",
        "sections": [{
            "activityTitle": act.title, "text": act.summary,
            "facts": [
                {"name": "Product line", "value": act.product_line or "n/a"},
                {"name": "Stage", "value": act.stage or "n/a"},
                {"name": "Date", "value": act.date or "n/a"},
                {"name": "Topics", "value": act.topics or "none"},
                {"name": "Suggested owner", "value": act.owner or "unassigned"},
            ]}],
        "potentialAction": [{"@type": "OpenUri", "name": "Open source",
                             "targets": [{"os": "default", "uri": act.url}]}],
    }
    requests.post(webhook, json=payload, timeout=30).raise_for_status()


def notify(cfg: dict, act: Act) -> None:
    ch = cfg.get("notify", {})
    if ch.get("slack_webhook"):
        post_slack(ch["slack_webhook"], act)
    if ch.get("teams_webhook"):
        post_teams(ch["teams_webhook"], act)


# --------------------------------------------------------------------------- #
# Source assembly
# --------------------------------------------------------------------------- #
def build_sources(cfg: dict) -> list:
    enabled = cfg.get("sources", {})
    contact = cfg.get("contact_email", "compliance@example.com")
    out = []
    if enabled.get("cellar", True):
        out.append(CellarSource(query_limit=cfg.get("query_limit", 400), contact=contact))
    if enabled.get("have_your_say", True):
        out.append(HaveYourSaySource(page_size=cfg.get("hys_page_size", 50)))
    if enabled.get("oeil", True):
        oc = cfg.get("oeil", {})
        out.append(OeilSource(search_rss=oc.get("search_rss") or None,
                              watch_references=oc.get("watch_references", [])))
    return out


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run(cfg_path: str, lookback_days: int, dry_run: bool) -> None:
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key and not dry_run:
        sys.exit("ANTHROPIC_API_KEY not set")

    conn = init_db(cfg.get("db_path", "seen.sqlite"))
    since = (dt.date.today() - dt.timedelta(days=lookback_days)).isoformat()
    threshold = int(cfg.get("relevance_threshold", 60))

    all_acts = []
    for src in build_sources(cfg):
        try:
            got = src.fetch(since)
            print(f"[info] {src.name}: {len(got)} items since {since}")
            all_acts.extend(got)
        except Exception as e:
            print(f"[warn] source {src.name} failed: {e}", file=sys.stderr)

    new_acts = [a for a in all_acts if is_new(conn, a.uid)]
    print(f"[info] {len(new_acts)} new items across all sources")

    posted = 0
    for act in new_acts:
        if dry_run:
            print(f"  [{act.source}] {act.stage:>22} | {act.title[:70]}")
            continue
        try:
            score_act(act, cfg, api_key)
        except requests.RequestException as e:
            print(f"[warn] scoring failed for {act.uid}: {e}", file=sys.stderr)
            continue
        relevant = (act.relevance or 0) >= threshold and act.topics not in (None, "none", "")
        if relevant:
            try:
                notify(cfg, act)
                posted += 1
                print(f"  posted [{act.source}] {act.tier} {act.relevance} | {act.title[:55]}")
            except requests.RequestException as e:
                print(f"[warn] notify failed for {act.uid}: {e}", file=sys.stderr)
        mark_seen(conn, act, posted=relevant)
        time.sleep(cfg.get("score_delay_seconds", 0.5))

    print(f"[done] {len(new_acts)} new, {posted} posted")


def main() -> None:
    p = argparse.ArgumentParser(description="EU regulatory early-warning monitor (multi-source)")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--lookback-days", type=int, default=7)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    run(args.config, args.lookback_days, args.dry_run)


if __name__ == "__main__":
    main()
