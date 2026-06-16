#!/usr/bin/env python3
"""
sources.py — pluggable data sources for the EU regulatory monitor.

Each source yields a list of `Act` objects with a `stage` hint so the scorer and
the dedup layer can treat early-stage (consultation), in-pipeline (procedure),
and published (CELLAR) items uniformly.

Sources
-------
1. CellarSource      — published / adopted legal acts (EUR-Lex CELLAR SPARQL)
2. HaveYourSaySource — Commission consultations & calls for evidence (earliest stage)
3. OeilSource        — European Parliament Legislative Observatory procedure tracking

All three are read-only and require no credentials.
"""

from __future__ import annotations

import datetime as dt
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Iterable
from xml.etree import ElementTree as ET

import feedparser
import requests

USER_AGENT = "eu-reg-watch/2.0 (compliance monitoring)"

SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
HYS_BASE = "https://have-your-say.ec.europa.eu"
# Frontend JSON service backing the Have Your Say "latest" listing.
HYS_API = f"{HYS_BASE}/api/allInitiatives"
OEIL_SEARCH = "https://oeil.secure.europarl.europa.eu/oeil/search/search.do"


@dataclass
class Act:
    # Identity / dedup key
    uid: str                      # globally-unique within its source namespace
    source: str                   # "CELLAR" | "HYS" | "OEIL"
    title: str
    date: str
    url: str
    # Source-specific context handed to the scorer
    stage: str = ""               # e.g. "published", "consultation", "1st reading"
    extra: dict = field(default_factory=dict)
    # Filled by scorer
    relevance: int | None = None
    tier: str | None = None
    summary: str | None = None
    owner: str | None = None
    topics: str | None = None
    product_line: str | None = None   # which product-line group(s) it matched


def _retrying_get(url: str, *, params=None, headers=None, max_retries=4, timeout=90):
    delay = 2.0
    hdr = {"User-Agent": USER_AGENT}
    if headers:
        hdr.update(headers)
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.get(url, params=params, headers=hdr, timeout=timeout)
            if r.status_code in (429, 503):
                raise requests.HTTPError(f"throttled {r.status_code}")
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if attempt == max_retries:
                raise
            print(f"[warn] GET {url} attempt {attempt} failed ({e}); backoff {delay}s",
                  file=sys.stderr)
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


# --------------------------------------------------------------------------- #
# 1. CELLAR (published acts)  — unchanged query logic, wrapped as a source
# --------------------------------------------------------------------------- #
class CellarSource:
    name = "CELLAR"

    def __init__(self, query_limit: int = 400, contact: str = "compliance@example.com"):
        self.query_limit = query_limit
        self.contact = contact

    def _query(self, since: str) -> str:
        return f"""
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT DISTINCT ?celex ?title ?date ?type WHERE {{
  ?work cdm:resource_legal_id_celex ?celex .
  ?work cdm:work_date_document ?date .
  ?expr cdm:expression_belongs_to_work ?work ;
        cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> ;
        cdm:expression_title ?title .
  OPTIONAL {{ ?work cdm:work_has_resource-type ?type . }}
  FILTER (?date >= "{since}"^^<http://www.w3.org/2001/XMLSchema#date>)
}}
ORDER BY DESC(?date)
LIMIT {self.query_limit}
"""

    def fetch(self, since: str) -> list[Act]:
        r = _retrying_get(
            SPARQL_ENDPOINT,
            params={"query": self._query(since), "format": "application/sparql-results+json"},
            headers={"Accept": "application/sparql-results+json"},
        )
        rows = r.json().get("results", {}).get("bindings", [])
        acts: list[Act] = []
        for row in rows:
            celex = row.get("celex", {}).get("value", "")
            if not celex:
                continue
            type_uri = row.get("type", {}).get("value", "")
            doc_type = type_uri.rsplit("/", 1)[-1] if type_uri else "UNKNOWN"
            acts.append(Act(
                uid=f"CELLAR:{celex}",
                source=self.name,
                title=row.get("title", {}).get("value", "(no title)"),
                date=row.get("date", {}).get("value", ""),
                url=f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}",
                stage="published",
                extra={"celex": celex, "doc_type": doc_type},
            ))
        return acts


# --------------------------------------------------------------------------- #
# 2. Have Your Say (consultations / calls for evidence — earliest stage)
# --------------------------------------------------------------------------- #
class HaveYourSaySource:
    """
    Pulls the latest Commission initiatives open for feedback.

    Primary path: the frontend JSON service (api/allInitiatives), which returns
    structured records (title, stage, feedback dates, topic). If the JSON shape
    changes or is unreachable, falls back to the public RSS of latest initiatives.
    """
    name = "HYS"

    # Map HYS feedback-stage labels to our internal stage vocabulary.
    STAGE_MAP = {
        "OPC": "public consultation",
        "OPC_LAUNCHED": "public consultation",
        "CFE": "call for evidence",
        "ROADMAP": "call for evidence",
        "ADOPTED": "adopted",
    }

    def __init__(self, page_size: int = 50):
        self.page_size = page_size

    def _from_json(self, since: str) -> list[Act]:
        params = {
            "language": "en",
            "size": self.page_size,
            "page": 0,
            "sort": "publicationDate,DESC",
        }
        r = _retrying_get(HYS_API, params=params,
                          headers={"Accept": "application/json"})
        data = r.json()
        # The service nests records under a few possible keys across versions.
        records = (data.get("_embedded", {}) or {}).get("initiativeResultDtoes") \
            or data.get("initiatives") or data.get("content") or []
        since_d = _parse_date(since)
        acts: list[Act] = []
        for rec in records:
            pub = (rec.get("publicationDate") or rec.get("feedbackStartDate") or "")[:10]
            if pub and _parse_date(pub) < since_d:
                continue
            ini_id = str(rec.get("id") or rec.get("initiativeId") or rec.get("shortTitle", ""))
            title = rec.get("shortTitle") or rec.get("title") or "(no title)"
            raw_stage = (rec.get("stage") or rec.get("currentStage")
                         or rec.get("frontEndStage") or "")
            stage = self.STAGE_MAP.get(str(raw_stage).upper(), str(raw_stage).lower() or "feedback")
            topic = rec.get("topic") or rec.get("policyArea") or ""
            acts.append(Act(
                uid=f"HYS:{ini_id}",
                source=self.name,
                title=title,
                date=pub,
                url=f"{HYS_BASE}/en/initiatives/{ini_id}",
                stage=stage,
                extra={"topic": topic,
                       "feedback_end": (rec.get("feedbackEndDate") or "")[:10]},
            ))
        return acts

    def _from_rss(self, since: str) -> list[Act]:
        # Public latest-initiatives feed; resilient fallback.
        feed_url = f"{HYS_BASE}/api/feeds/initiatives/rss"
        r = _retrying_get(feed_url, headers={"Accept": "application/rss+xml"})
        parsed = feedparser.parse(r.content)
        since_d = _parse_date(since)
        acts: list[Act] = []
        for e in parsed.entries:
            pub = _entry_date(e)
            if pub and _parse_date(pub) < since_d:
                continue
            uid = e.get("id") or e.get("link") or e.get("title", "")
            acts.append(Act(
                uid=f"HYS:{_slug(uid)}",
                source=self.name,
                title=e.get("title", "(no title)"),
                date=pub or "",
                url=e.get("link", HYS_BASE),
                stage="feedback",
                extra={"summary_raw": e.get("summary", "")[:500]},
            ))
        return acts

    def fetch(self, since: str) -> list[Act]:
        try:
            acts = self._from_json(since)
            if acts:
                return acts
            print("[info] HYS JSON returned 0 rows; trying RSS fallback", file=sys.stderr)
        except (requests.RequestException, ValueError, KeyError) as e:
            print(f"[warn] HYS JSON failed ({e}); trying RSS fallback", file=sys.stderr)
        try:
            return self._from_rss(since)
        except requests.RequestException as e:
            print(f"[warn] HYS RSS also failed ({e}); skipping source", file=sys.stderr)
            return []


# --------------------------------------------------------------------------- #
# 3. OEIL (Legislative Observatory — procedure status tracking)
# --------------------------------------------------------------------------- #
class OeilSource:
    """
    Two modes:

    A) DISCOVER (default): consume an OEIL search RSS feed (you build the search
       on the OEIL site, copy its RSS link into config) to catch newly-active or
       newly-updated procedures matching your saved filter.

    B) WATCH: for an explicit list of procedure references (e.g. "2023/0212(COD)"),
       fetch each procedure file and report its current stage. Use this to follow
       specific files you already care about as they move through Parliament/Council.

    Stage changes are surfaced to the dedup layer via a composite uid that
    includes the stage, so a procedure re-posts when (and only when) its stage
    advances.
    """
    name = "OEIL"

    PROC_FILE = "https://oeil.secure.europarl.europa.eu/oeil/en/procedure-file"

    def __init__(self, search_rss: str | None = None,
                 watch_references: Iterable[str] | None = None):
        self.search_rss = search_rss
        self.watch_references = list(watch_references or [])

    # --- mode A ---
    def _discover(self, since: str) -> list[Act]:
        if not self.search_rss:
            return []
        r = _retrying_get(self.search_rss, headers={"Accept": "application/rss+xml"})
        parsed = feedparser.parse(r.content)
        since_d = _parse_date(since)
        acts: list[Act] = []
        for e in parsed.entries:
            pub = _entry_date(e)
            if pub and _parse_date(pub) < since_d:
                continue
            ref = _extract_proc_ref(e.get("title", "") + " " + e.get("link", ""))
            stage = _extract_stage(e.get("summary", "")) or "updated"
            base_id = ref or _slug(e.get("link", e.get("title", "")))
            acts.append(Act(
                uid=f"OEIL:{base_id}:{_slug(stage)}",
                source=self.name,
                title=e.get("title", "(no title)"),
                date=pub or "",
                url=e.get("link", OEIL_SEARCH),
                stage=stage,
                extra={"procedure_ref": ref or ""},
            ))
        return acts

    # --- mode B ---
    def _watch(self) -> list[Act]:
        acts: list[Act] = []
        for ref in self.watch_references:
            try:
                r = _retrying_get(self.PROC_FILE, params={"reference": ref})
            except requests.RequestException as e:
                print(f"[warn] OEIL procedure {ref} fetch failed ({e})", file=sys.stderr)
                continue
            html = r.text
            stage = _extract_stage(html) or "in progress"
            title = _extract_title(html) or ref
            acts.append(Act(
                uid=f"OEIL:{ref}:{_slug(stage)}",
                source=self.name,
                title=title,
                date=dt.date.today().isoformat(),
                url=f"{self.PROC_FILE}?reference={ref}",
                stage=stage,
                extra={"procedure_ref": ref},
            ))
        return acts

    def fetch(self, since: str) -> list[Act]:
        return self._discover(since) + self._watch()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _parse_date(s: str) -> dt.date:
    s = (s or "")[:10]
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        return dt.date(1970, 1, 1)


def _entry_date(e) -> str:
    for key in ("published_parsed", "updated_parsed"):
        t = e.get(key)
        if t:
            return time.strftime("%Y-%m-%d", t)
    return ""


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s or "").strip("-")[:80] or "x"


_PROC_RE = re.compile(r"\b(\d{4}/\d{3,4}\([A-Z]{2,4}\))")


def _extract_proc_ref(text: str) -> str | None:
    m = _PROC_RE.search(text or "")
    return m.group(1) if m else None


# Common OEIL stage phrases, ordered; first match wins.
_STAGE_PATTERNS = [
    ("awaiting Parliament", "awaiting Parliament 1st reading"),
    ("1st reading", "1st reading"),
    ("first reading", "1st reading"),
    ("2nd reading", "2nd reading"),
    ("Awaiting final decision", "awaiting final decision"),
    ("Awaiting Council", "awaiting Council position"),
    ("Procedure completed", "completed"),
    ("Act adopted", "adopted"),
    ("Awaiting committee decision", "committee stage"),
    ("Preparatory phase", "preparatory"),
]


def _extract_stage(text: str) -> str | None:
    low = (text or "").lower()
    for needle, label in _STAGE_PATTERNS:
        if needle.lower() in low:
            return label
    return None


def _extract_title(html: str) -> str | None:
    m = re.search(r"<title>(.*?)</title>", html or "", re.S | re.I)
    if not m:
        return None
    title = re.sub(r"\s+", " ", m.group(1)).strip()
    title = title.split("|")[0].strip()
    return title or None
