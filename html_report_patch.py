#!/usr/bin/env python3
"""
html_report_patch.py
====================
기존 html_report.py 에 두 가지 기능을 추가합니다.

  1. export_json(alerts, out_dir)
       scored alerts 를 site/alerts.json 으로 저장합니다.
       GitHub raw URL 을 통해 로컬 HTML 이 fetch 해갈 수 있습니다.

  2. render_local_client(out_dir, github_raw_base)
       로컬 PC 에 한 번만 배포하면 되는 standalone HTML 을 생성합니다.
       파일을 열 때마다 alerts.json 을 fetch → 최신 데이터로 자동 렌더링합니다.
       인터넷이 연결되어 있어야 하며, GitHub repo 가 Public 이거나
       Personal Access Token 을 사용해야 합니다.

사용 방법 (eu_reg_watch.py 의 html_report 블록에 추가):
-------------------------------------------------------
    from html_report import render_site
    from html_report_patch import export_json, render_local_client

    paths = render_site(relevant_alerts, out_dir, cfg)

    # JSON 내보내기 (방법 A 에 필요)
    export_json(relevant_alerts, out_dir)

    # 로컬 클라이언트 HTML 생성 (최초 1회 또는 URL 변경 시)
    raw_base = cfg.get("html_report", {}).get("github_raw_base", "")
    if raw_base:
        render_local_client(out_dir, raw_base)
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
from dataclasses import asdict, is_dataclass


# ---------------------------------------------------------------------------
# 직렬화 헬퍼
# ---------------------------------------------------------------------------
def _act_to_dict(a) -> dict:
    """Act 객체 또는 일반 dict 를 JSON 직렬화 가능한 dict 로 변환합니다."""
    if is_dataclass(a):
        d = asdict(a)
    elif hasattr(a, "__dict__"):
        d = dict(a.__dict__)
    else:
        d = dict(a)
    # extra 필드가 중첩 dict 일 수 있으므로 str 로 폴백
    if "extra" in d and not isinstance(d["extra"], (dict, list, str, int, float, bool, type(None))):
        d["extra"] = str(d["extra"])
    return d


# ---------------------------------------------------------------------------
# 1. JSON 내보내기
# ---------------------------------------------------------------------------
def export_json(alerts: list, out_dir: str) -> str:
    """
    scored alerts 를 site/alerts.json 으로 저장합니다.

    반환값: 저장된 파일 경로
    """
    os.makedirs(out_dir, exist_ok=True)
    payload = {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "count": len(alerts),
        "alerts": [_act_to_dict(a) for a in alerts],
    }
    path = os.path.join(out_dir, "alerts.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[info] alerts.json written: {path}")
    return path


# ---------------------------------------------------------------------------
# 2. 로컬 클라이언트 HTML
# ---------------------------------------------------------------------------
# github_raw_base 예시:
#   https://raw.githubusercontent.com/yourname/eu-reg-watch/main/site
# 이 URL + /alerts.json 을 fetch 합니다.

_LOCAL_HTML_TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>EU Regulatory Early-Warning (live)</title>
<style>
:root{{--bg:#faf9f7;--card:#fff;--ink:#1c1b19;--ink2:#5b574f;--ink3:#8a857c;
      --line:#e7e3dc;--link:#0c447c;--accent:#3d6fb4;--ok:#1a7f4b;--warn:#b45309}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);
     font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}
.wrap{{max-width:860px;margin:0 auto;padding:32px 20px 64px}}
header h1{{font-size:22px;margin:0 0 4px}}
header .sub{{color:var(--ink2);font-size:13px;margin:0 0 4px}}
.status{{display:inline-flex;align-items:center;gap:6px;font-size:12px;
         padding:4px 10px;border-radius:7px;margin:4px 0 16px;
         background:#e8f4ec;color:var(--ok);border:1px solid #a7d4b8}}
.status.loading{{background:#f1efe8;color:var(--ink3);border-color:var(--line)}}
.status.error{{background:#fef2f2;color:#b91c1c;border-color:#fca5a5}}
.status .dot{{width:7px;height:7px;border-radius:50%;background:currentColor}}
.controls{{margin:12px 0 8px;display:flex;gap:8px;flex-wrap:wrap}}
.controls button{{font:inherit;font-size:13px;border:1px solid var(--line);
                  background:var(--card);color:var(--ink2);padding:5px 12px;
                  border-radius:8px;cursor:pointer}}
.controls button.active{{background:var(--accent);color:#fff;border-color:var(--accent)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;
       padding:16px 18px;margin:12px 0}}
.row{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px}}
.pill{{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;
       padding:4px 10px;border-radius:7px}}
.dot{{width:8px;height:8px;border-radius:50%;display:inline-block}}
.muted{{font-size:12px;color:var(--ink3)}}
.title{{display:inline-block;font-size:15px;font-weight:600;color:var(--link);
        text-decoration:none;margin:2px 0 6px}}
.title:hover{{text-decoration:underline}}
.summary{{margin:0 0 12px;color:var(--ink2);font-size:14px}}
.facts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
        gap:8px;border-top:1px solid var(--line);padding-top:10px}}
.facts .k{{display:block;font-size:11px;color:var(--ink3)}}
.facts .v{{display:block;font-size:13px}}
.facts .owner{{font-weight:600}}
.empty{{color:var(--ink3);padding:40px 0;text-align:center}}
.foot{{margin-top:32px;color:var(--ink3);font-size:12px;
       border-top:1px solid var(--line);padding-top:16px}}
a{{color:var(--link)}}
@media(prefers-color-scheme:dark){{
  :root{{--bg:#1a1917;--card:#242320;--ink:#e8e6e0;--ink2:#a09c94;--ink3:#6b6760;
         --line:#2e2c29;--link:#7aaedf;--accent:#5a8cc4}}
}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>EU Regulatory Early-Warning</h1>
    <p class="sub" id="subtitle">불러오는 중...</p>
  </header>
  <div class="status loading" id="status">
    <span class="dot"></span><span id="status-text">데이터 가져오는 중...</span>
  </div>
  <div class="controls" id="controls"></div>
  <div id="cards"></div>
  <div class="foot">
    자동 조기경보 시스템 — EUR-Lex, Have Your Say, Legislative Observatory 기반.<br>
    AI 요약은 참고용이며 담당 팀이 확인 후 조치해야 합니다.<br>
    데이터 출처: <a href="{raw_base}/alerts.json" target="_blank">alerts.json</a>
    &nbsp;·&nbsp; <a href="#" onclick="loadData()">새로고침</a>
  </div>
</div>

<script>
const DATA_URL = "{raw_base}/alerts.json";

const TIER_META = {{
  ACTIVE:   {{dot:"#E24B4A", bg:"#FCEBEB", fg:"#A32D2D", label:"active"}},
  PIPELINE: {{dot:"#D85A30", bg:"#FAECE7", fg:"#993C1D", label:"pipeline"}},
  HORIZON:  {{dot:"#EF9F27", bg:"#FAEEDA", fg:"#854F0B", label:"horizon"}},
}};
const SOURCE_LABEL = {{
  CELLAR: "EUR-Lex (published)",
  HYS:    "Have Your Say (consultation)",
  OEIL:   "Leg. Observatory (procedure)",
}};
const TIER_ORDER = {{ACTIVE:0, PIPELINE:1, HORIZON:2}};

function esc(s) {{
  return String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}}

function card(a) {{
  const m = TIER_META[a.tier] || {{dot:"#888",bg:"#eee",fg:"#444",label:a.tier||"n/a"}};
  const src = SOURCE_LABEL[a.source] || a.source;
  return `
  <article class="card" data-line="${{esc(a.product_line)}}" data-tier="${{esc(a.tier)}}">
    <div class="row">
      <span class="pill" style="background:${{m.bg}};color:${{m.fg}}">
        <span class="dot" style="background:${{m.dot}}"></span>${{m.label}}
      </span>
      <span class="muted">관련도 ${{esc(a.relevance)}}</span>
      <span class="muted">· ${{esc(src)}}</span>
    </div>
    <a class="title" href="${{esc(a.url)}}" target="_blank" rel="noopener">${{esc(a.title)}} &#8599;</a>
    <p class="summary">${{esc(a.summary)}}</p>
    <div class="facts">
      <div><span class="k">product line</span><span class="v">${{esc(a.product_line)}}</span></div>
      <div><span class="k">stage</span><span class="v">${{esc(a.stage)||"n/a"}}</span></div>
      <div><span class="k">date</span><span class="v">${{esc(a.date)||"n/a"}}</span></div>
      <div><span class="k">topics</span><span class="v">${{esc(a.topics)}}</span></div>
      <div><span class="k">owner</span><span class="v owner">${{esc(a.owner)}}</span></div>
    </div>
  </article>`;
}}

function setStatus(text, type) {{
  const el = document.getElementById("status");
  el.className = "status " + (type || "");
  document.getElementById("status-text").textContent = text;
}}

async function loadData() {{
  setStatus("데이터 가져오는 중...", "loading");
  try {{
    // 캐시 무효화: 매번 서버에서 최신본을 가져옵니다
    const res = await fetch(DATA_URL + "?t=" + Date.now(), {{cache: "no-store"}});
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();

    // 부제목 업데이트
    const dt = data.generated ? data.generated.replace("T", " ").slice(0,16) : "";
    document.getElementById("subtitle").textContent =
      `${{data.count}}개 항목 · 마지막 업데이트: ${{dt}} UTC`;

    // 티어·관련도 순으로 정렬
    const sorted = (data.alerts || []).sort((a,b) =>
      (TIER_ORDER[a.tier]??9) - (TIER_ORDER[b.tier]??9) || (b.relevance||0) - (a.relevance||0)
    );

    // 필터 버튼
    const lines = [...new Set(sorted.map(a => a.product_line).filter(x => x && x!=="none"))].sort();
    const ctrl = document.getElementById("controls");
    ctrl.innerHTML = `<button class="active" data-filter="all">전체</button>` +
      lines.map(l => `<button data-filter="${{esc(l)}}">${{esc(l)}}</button>`).join("");
    ctrl.querySelectorAll("button").forEach(b => b.addEventListener("click", () => {{
      ctrl.querySelectorAll("button").forEach(x => x.classList.remove("active"));
      b.classList.add("active");
      const f = b.dataset.filter;
      document.querySelectorAll(".card").forEach(c =>
        c.style.display = (f==="all" || c.dataset.line===f) ? "" : "none"
      );
    }}));

    // 카드 렌더링
    const cardsEl = document.getElementById("cards");
    cardsEl.innerHTML = sorted.length
      ? sorted.map(card).join("")
      : '<div class="empty">이번 실행에서 관련 항목이 없습니다.</div>';

    setStatus(`✓ 최신 데이터 로드 완료 (${{dt}} UTC)`, "");

  }} catch(e) {{
    setStatus("오류: " + e.message + " — 인터넷 연결 또는 repo 공개 여부를 확인하세요.", "error");
    document.getElementById("cards").innerHTML =
      '<div class="empty">데이터를 불러올 수 없습니다.</div>';
  }}
}}

// 페이지 로드 시 자동 실행
loadData();
</script>
</body>
</html>
"""


def render_local_client(out_dir: str, github_raw_base: str) -> str:
    """
    로컬 PC 에 배포할 standalone HTML 을 생성합니다.

    Parameters
    ----------
    out_dir : str
        출력 디렉토리 (통상 "site")
    github_raw_base : str
        raw.githubusercontent.com 경로.
        예: https://raw.githubusercontent.com/yourname/eu-reg-watch/main/site

    반환값: 저장된 파일 경로
    """
    os.makedirs(out_dir, exist_ok=True)
    raw_base = github_raw_base.rstrip("/")
    content = _LOCAL_HTML_TEMPLATE.format(raw_base=raw_base)
    path = os.path.join(out_dir, "local_client.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[info] local_client.html written: {path}")
    return path
