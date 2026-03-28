"""
Ariadne — Literature Review Dashboard
Run:  python -m streamlit run app.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))
import db_sync as db

# ─────────────────────────────────────────────────────────────────────────────
# Page config  (must be first st call)
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Ariadne",
    page_icon="🧵",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Design tokens
# ─────────────────────────────────────────────────────────────────────────────

PILLAR_HEX = {
    "pure_math":     "#58a6ff",
    "computational": "#3fb950",
    "financial":     "#f78166",
    "unassigned":    "#6e7681",
}
PILLAR_BG = {
    "pure_math":     "#0d2a4a",
    "computational": "#0d2f1a",
    "financial":     "#2f1212",
    "unassigned":    "#161b22",
}
PILLAR_LABEL = {
    "pure_math":     "Pure Math",
    "computational": "Computational",
    "financial":     "Financial",
    "unassigned":    "Unassigned",
}
PILLAR_ICON = {
    "pure_math":     "∂",
    "computational": "λ",
    "financial":     "₿",
    "unassigned":    "·",
}

STATUS_HEX = {
    "unread":    "#6e7681",
    "skimmed":   "#d29922",
    "read":      "#58a6ff",
    "deep_read": "#3fb950",
}
STATUS_LABEL = {
    "unread":    "Unread",
    "skimmed":   "Skimmed",
    "read":      "Read",
    "deep_read": "Deep Read",
}
STATUS_DOT = {
    "unread":    "○",
    "skimmed":   "◑",
    "read":      "◕",
    "deep_read": "●",
}

CHAPTERS = [
    "", "introduction", "mathematical_framework",
    "numerical_methodology", "empirical_results", "conclusion", "appendix",
]

# ─────────────────────────────────────────────────────────────────────────────
# Global CSS
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* ── Reset & base ───────────────────────────────────────────────── */
[data-testid="stAppViewContainer"] { background: #0d1117; }
[data-testid="stHeader"]           { background: transparent; border-bottom: 1px solid #21262d; }
[data-testid="stSidebar"]          { background: #0d1117; border-right: 1px solid #21262d; }
[data-testid="stSidebar"] > div    { padding-top: 1.5rem; }
section.main > div                 { padding-top: 1.5rem; }
h1, h2, h3, h4                     { color: #e6edf3 !important; }
p, li, label                       { color: #8b949e !important; }
hr                                 { border-color: #21262d !important; }
[data-testid="stExpander"]         { border: 1px solid #21262d !important; border-radius: 8px !important; background: #161b22 !important; }
[data-testid="stExpander"] summary { color: #c9d1d9 !important; }
[data-testid="stExpander"] summary:hover { color: #e6edf3 !important; }
div[data-testid="stSelectbox"] label  { color: #8b949e !important; font-size: 0.78rem !important; }
div[data-testid="stTextInput"] label  { color: #8b949e !important; font-size: 0.78rem !important; }
div[data-testid="stTextArea"]  label  { color: #8b949e !important; font-size: 0.78rem !important; }
div[data-testid="stSelectSlider"] label { color: #8b949e !important; font-size: 0.78rem !important; }
div[data-testid="stMultiSelect"] label  { color: #8b949e !important; font-size: 0.78rem !important; }
div[data-testid="stSlider"] label       { color: #8b949e !important; font-size: 0.78rem !important; }
input, textarea, select            { background: #161b22 !important; color: #e6edf3 !important; border: 1px solid #30363d !important; border-radius: 6px !important; }
.stButton > button                 { background: #21262d !important; color: #c9d1d9 !important; border: 1px solid #30363d !important; border-radius: 6px !important; font-size: 0.82rem !important; }
.stButton > button:hover           { background: #30363d !important; border-color: #58a6ff !important; color: #e6edf3 !important; }
.stButton > button[kind="primary"] { background: #1f6feb !important; color: #fff !important; border-color: #1f6feb !important; }
.stButton > button[kind="primary"]:hover { background: #388bfd !important; }
[data-testid="stProgress"] > div > div { background: #1f6feb !important; border-radius: 4px !important; }
[data-testid="stProgress"] > div       { background: #21262d !important; border-radius: 4px !important; }
[data-testid="stDataFrame"]            { border: 1px solid #21262d !important; border-radius: 8px !important; }

/* ── Typography ──────────────────────────────────────────────────── */
.page-title {
  font-size: 1.45rem;
  font-weight: 700;
  color: #e6edf3;
  letter-spacing: -0.02em;
  margin-bottom: 0.15rem;
  line-height: 1.2;
}
.page-subtitle {
  font-size: 0.82rem;
  color: #6e7681;
  margin-bottom: 1.5rem;
}
.section-title {
  font-size: 0.75rem;
  font-weight: 600;
  color: #6e7681;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 0.75rem;
  margin-top: 0.25rem;
}

/* ── Stat cards ──────────────────────────────────────────────────── */
.stat-card {
  background: #161b22;
  border: 1px solid #21262d;
  border-radius: 10px;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.stat-card:hover { border-color: #30363d; }
.stat-number {
  font-size: 2rem;
  font-weight: 800;
  line-height: 1;
  color: #e6edf3;
  font-variant-numeric: tabular-nums;
}
.stat-label {
  font-size: 0.75rem;
  font-weight: 500;
  color: #6e7681;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.stat-accent { border-top: 2px solid #1f6feb; }
.stat-green  { border-top: 2px solid #3fb950; }
.stat-yellow { border-top: 2px solid #d29922; }
.stat-gray   { border-top: 2px solid #30363d; }
.stat-red    { border-top: 2px solid #f78166; }

/* ── Paper cards ─────────────────────────────────────────────────── */
.paper-card {
  background: #161b22;
  border: 1px solid #21262d;
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 8px;
  border-left: 3px solid #30363d;
  transition: border-color 0.15s;
}
.paper-card:hover { border-color: #30363d; }
.paper-title {
  font-size: 0.92rem;
  font-weight: 600;
  color: #e6edf3;
  line-height: 1.35;
  margin-bottom: 5px;
}
.paper-authors {
  font-size: 0.78rem;
  color: #8b949e;
  margin-bottom: 4px;
}
.paper-meta {
  font-size: 0.75rem;
  color: #6e7681;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 6px;
}
.paper-tldr {
  font-size: 0.78rem;
  color: #8b949e;
  margin-top: 7px;
  padding-top: 7px;
  border-top: 1px solid #21262d;
  font-style: italic;
  line-height: 1.45;
}

/* ── Badges ──────────────────────────────────────────────────────── */
.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border-radius: 20px;
  padding: 2px 9px;
  font-size: 0.71rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  white-space: nowrap;
}
.tag-badge {
  background: #21262d;
  color: #8b949e;
  border: 1px solid #30363d;
  border-radius: 4px;
  padding: 1px 7px;
  font-size: 0.7rem;
  display: inline-block;
  margin: 2px 3px 2px 0;
}

/* ── Pill bar (pillar / status breakdown) ────────────────────────── */
.pill-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  background: #161b22;
  border: 1px solid #21262d;
  border-radius: 8px;
  margin-bottom: 6px;
}
.pill-icon {
  font-size: 1.1rem;
  font-weight: 700;
  min-width: 20px;
  text-align: center;
}
.pill-name   { font-size: 0.82rem; color: #c9d1d9; font-weight: 500; min-width: 120px; }
.pill-count  { font-size: 0.82rem; color: #e6edf3; font-weight: 700; min-width: 28px; text-align: right; }
.pill-bar    { flex: 1; height: 5px; background: #21262d; border-radius: 3px; overflow: hidden; }
.pill-fill   { height: 100%; border-radius: 3px; }
.pill-pct    { font-size: 0.7rem; color: #6e7681; min-width: 34px; text-align: right; }

/* ── Extraction grid ─────────────────────────────────────────────── */
.ext-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-top: 10px;
}
.ext-cell {
  background: #0d1117;
  border: 1px solid #21262d;
  border-radius: 8px;
  padding: 10px 14px;
}
.ext-label {
  font-size: 0.68rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: #6e7681;
  margin-bottom: 4px;
}
.ext-value { font-size: 0.82rem; color: #c9d1d9; line-height: 1.4; }

/* ── Sidebar nav ─────────────────────────────────────────────────── */
.nav-logo {
  font-size: 1.1rem;
  font-weight: 700;
  color: #e6edf3;
  letter-spacing: -0.02em;
  padding: 0 0 4px 0;
}
.nav-sub { font-size: 0.72rem; color: #6e7681; }
.sidebar-stat {
  background: #161b22;
  border: 1px solid #21262d;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 10px;
}
.sidebar-stat-num   { font-size: 1.5rem; font-weight: 800; color: #e6edf3; }
.sidebar-stat-label { font-size: 0.72rem; color: #6e7681; margin-top: 1px; }

/* ── Empty state ─────────────────────────────────────────────────── */
.empty-state {
  background: #161b22;
  border: 1px dashed #30363d;
  border-radius: 12px;
  padding: 40px 32px;
  text-align: center;
}
.empty-icon  { font-size: 2.5rem; margin-bottom: 12px; }
.empty-title { font-size: 1rem; font-weight: 600; color: #e6edf3 !important; margin-bottom: 6px; }
.empty-body  { font-size: 0.82rem; color: #6e7681 !important; line-height: 1.6; }

/* ── Links ───────────────────────────────────────────────────────── */
a { color: #58a6ff !important; text-decoration: none !important; }
a:hover { text-decoration: underline !important; }

/* ── Hide Streamlit branding ─────────────────────────────────────── */
#MainMenu, footer, [data-testid="stDeployButton"] { display: none !important; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Helper: HTML components
# ─────────────────────────────────────────────────────────────────────────────

def _badge(text: str, colour: str, bg: str) -> str:
    return (
        f'<span class="badge" style="background:{bg};color:{colour};'
        f'border:1px solid {colour}44">{text}</span>'
    )

def _pillar_badge(pillar: str) -> str:
    p = pillar or "unassigned"
    icon = PILLAR_ICON.get(p, "·")
    label = PILLAR_LABEL.get(p, p)
    return _badge(f"{icon} {label}", PILLAR_HEX.get(p, "#6e7681"), PILLAR_BG.get(p, "#161b22"))

def _status_badge(status: str) -> str:
    s = status or "unread"
    dot = STATUS_DOT.get(s, "○")
    label = STATUS_LABEL.get(s, s)
    return _badge(f"{dot} {label}", STATUS_HEX.get(s, "#6e7681"), STATUS_HEX.get(s, "#6e7681") + "18")

def _tag_chips(tags: list[str]) -> str:
    return "".join(f'<span class="tag-badge">{t}</span>' for t in tags)

def _paper_card(p: dict, accent: str = "") -> str:
    colour = PILLAR_HEX.get(p.get("pillar") or "unassigned", "#30363d")
    authors = ", ".join(a["name"] for a in p.get("authors", [])[:3])
    if len(p.get("authors", [])) > 3:
        authors += " et al."
    year = p.get("year") or "n.d."
    cit = f'{p["citation_count"]:,} citations' if p.get("citation_count") else ""
    venue = p.get("venue") or ""
    tags_html = _tag_chips(p.get("tags") or [])
    tldr = p.get("tldr") or ""
    tldr_html = f'<div class="paper-tldr">{tldr[:220]}{"…" if len(tldr)>220 else ""}</div>' if tldr else ""
    meta_parts = [x for x in [year, venue, cit] if x]
    stars = ("★" * (p.get("relevance") or 0)) + ("☆" * (5 - (p.get("relevance") or 0)))
    stars_html = f'<span style="color:#d29922;font-size:0.75rem">{stars}</span>' if p.get("relevance") else ""

    return (
        f'<div class="paper-card" style="border-left-color:{colour}">'
        f'<div class="paper-title">{p["title"]}</div>'
        f'<div class="paper-authors">{authors}</div>'
        f'<div class="paper-meta">'
        f'{_status_badge(p.get("status","unread"))}'
        f'{_pillar_badge(p.get("pillar","unassigned"))}'
        f'{"".join(f"<span>{x}</span>" for x in meta_parts)}'
        f'{stars_html}'
        f'</div>'
        f'{f"<div style=margin-top:8px>{tags_html}</div>" if tags_html else ""}'
        f'{tldr_html}'
        f'</div>'
    )

def _pill_row(label: str, icon: str, count: int, total: int, colour: str) -> str:
    pct = int(count / (total or 1) * 100)
    fill_w = f"{pct}%"
    return (
        f'<div class="pill-row">'
        f'<span class="pill-icon" style="color:{colour}">{icon}</span>'
        f'<span class="pill-name">{label}</span>'
        f'<div class="pill-bar"><div class="pill-fill" style="width:{fill_w};background:{colour}"></div></div>'
        f'<span class="pill-count">{count}</span>'
        f'<span class="pill-pct">{pct}%</span>'
        f'</div>'
    )

def _stat_card(num: int | str, label: str, css_class: str = "") -> str:
    return (
        f'<div class="stat-card {css_class}">'
        f'<div class="stat-number">{num}</div>'
        f'<div class="stat-label">{label}</div>'
        f'</div>'
    )

def _ext_grid(p: dict) -> str:
    fields = [
        ("Methodology",        p.get("methodology")),
        ("Limitations",        p.get("limitations")),
        ("Math Framework",     p.get("math_framework")),
        ("Convergence Bounds", p.get("convergence_bounds")),
    ]
    cells = "".join(
        f'<div class="ext-cell"><div class="ext-label">{lbl}</div>'
        f'<div class="ext-value">{val}</div></div>'
        for lbl, val in fields if val
    )
    return f'<div class="ext-grid">{cells}</div>' if cells else ""


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown(
        '<div class="nav-logo">🧵 Ariadne</div>'
        '<div class="nav-sub">Literature Review System</div>',
        unsafe_allow_html=True,
    )
    st.markdown("<br>", unsafe_allow_html=True)

    page = st.radio(
        "nav",
        ["Dashboard", "Papers", "Citation Graph", "Edit Paper"],
        format_func=lambda x: {
            "Dashboard":    "📊  Dashboard",
            "Papers":       "📄  Papers",
            "Citation Graph": "🕸  Citation Graph",
            "Edit Paper":   "✏️  Edit Paper",
        }[x],
        label_visibility="collapsed",
    )

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="section-title">Library</div>', unsafe_allow_html=True)

    if db.db_exists():
        s = db.stats()
        total = s["total"] or 1
        read  = s["by_status"].get("deep_read", 0) + s["by_status"].get("read", 0)
        pct   = int(read / total * 100)

        col1, col2 = st.columns(2)
        col1.markdown(
            f'<div class="sidebar-stat">'
            f'<div class="sidebar-stat-num">{s["total"]}</div>'
            f'<div class="sidebar-stat-label">Papers</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        col2.markdown(
            f'<div class="sidebar-stat">'
            f'<div class="sidebar-stat-num" style="color:#3fb950">{pct}%</div>'
            f'<div class="sidebar-stat-label">Read</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.progress(read / total)

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="section-title">Pillars</div>', unsafe_allow_html=True)
        for pillar, colour in PILLAR_HEX.items():
            cnt = s["by_pillar"].get(pillar, 0)
            if cnt:
                st.markdown(
                    _pill_row(PILLAR_LABEL[pillar], PILLAR_ICON[pillar], cnt, s["total"], colour),
                    unsafe_allow_html=True,
                )
    else:
        st.markdown(
            '<div class="empty-state">'
            '<div class="empty-icon">📭</div>'
            '<div class="empty-title">Library is empty</div>'
            '<div class="empty-body">Use the MCP tools in Claude Code to add papers.</div>'
            '</div>',
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Guard: empty library
# ─────────────────────────────────────────────────────────────────────────────

if not db.db_exists():
    st.markdown(
        '<div class="page-title">Literature Review Dashboard</div>'
        '<div class="page-subtitle">No library found — start by importing papers via the MCP server</div>',
        unsafe_allow_html=True,
    )
    st.markdown("""
    <div class="empty-state" style="max-width:600px;margin-top:2rem">
      <div class="empty-icon">⬡</div>
      <div class="empty-title">Getting started</div>
      <div class="empty-body">
        In a Claude Code session, run:<br><br>
        <code style="background:#0d1117;padding:10px 14px;border-radius:6px;display:inline-block;text-align:left;font-size:0.8rem;color:#58a6ff">
          import_from_bibtex()&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;# seed from report/references.bib<br>
          search_papers("Deep BSDE solver McKean-Vlasov")<br>
          add_paper("paper_id_from_search")
        </code>
      </div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()


# ═════════════════════════════════════════════════════════════════════════════
# PAGE 1 — DASHBOARD
# ═════════════════════════════════════════════════════════════════════════════

if page == "Dashboard":
    s      = db.stats()
    papers = db.get_all_papers()
    total  = s["total"] or 1

    st.markdown(
        '<div class="page-title">Dashboard</div>'
        '<div class="page-subtitle">Reading progress and library overview</div>',
        unsafe_allow_html=True,
    )

    # ── Stat row ──────────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.markdown(_stat_card(s["total"],                            "Total Papers",  "stat-accent"), unsafe_allow_html=True)
    c2.markdown(_stat_card(s["by_status"].get("deep_read", 0),   "Deep Read",     "stat-green"),  unsafe_allow_html=True)
    c3.markdown(_stat_card(s["by_status"].get("read", 0),        "Read",          "stat-accent"), unsafe_allow_html=True)
    c4.markdown(_stat_card(s["by_status"].get("skimmed", 0),     "Skimmed",       "stat-yellow"), unsafe_allow_html=True)
    c5.markdown(_stat_card(s["by_status"].get("unread", 0),      "Unread",        "stat-gray"),   unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Pillar + Chapter ──────────────────────────────────────────────────
    left, right = st.columns(2)

    with left:
        st.markdown('<div class="section-title">By Research Pillar</div>', unsafe_allow_html=True)
        for pillar, colour in PILLAR_HEX.items():
            cnt = s["by_pillar"].get(pillar, 0)
            st.markdown(
                _pill_row(PILLAR_LABEL[pillar], PILLAR_ICON[pillar], cnt, total, colour),
                unsafe_allow_html=True,
            )

    with right:
        st.markdown('<div class="section-title">By Dissertation Chapter</div>', unsafe_allow_html=True)
        chapter_icons = {
            "introduction":          "①",
            "mathematical_framework":"②",
            "numerical_methodology": "③",
            "empirical_results":     "④",
            "conclusion":            "⑤",
            "appendix":              "A",
        }
        if s["by_chapter"]:
            for chap, cnt in sorted(s["by_chapter"].items()):
                label = chap.replace("_", " ").title()
                icon  = chapter_icons.get(chap, "·")
                st.markdown(
                    _pill_row(label, icon, cnt, total, "#8b949e"),
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                '<div class="empty-state" style="padding:20px">'
                '<div class="empty-body">No chapter assignments yet.<br>'
                'Use <code>assign_chapter()</code> in Claude Code.</div></div>',
                unsafe_allow_html=True,
            )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Reading status breakdown ──────────────────────────────────────────
    st.markdown('<div class="section-title">Reading Pipeline</div>', unsafe_allow_html=True)
    pipe_cols = st.columns(4)
    status_order = ["unread", "skimmed", "read", "deep_read"]
    for i, status in enumerate(status_order):
        cnt    = s["by_status"].get(status, 0)
        colour = STATUS_HEX[status]
        dot    = STATUS_DOT[status]
        label  = STATUS_LABEL[status]
        pipe_cols[i].markdown(
            f'<div class="stat-card" style="border-top:2px solid {colour}">'
            f'<div style="font-size:1.6rem;color:{colour};font-weight:800">{cnt}</div>'
            f'<div style="font-size:0.72rem;color:#6e7681;text-transform:uppercase;'
            f'letter-spacing:.06em">{dot} {label}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Two bottom sections ───────────────────────────────────────────────
    bl, br = st.columns(2)

    with bl:
        st.markdown('<div class="section-title">Most Cited in Library</div>', unsafe_allow_html=True)
        top = sorted(
            [p for p in papers if p.get("citation_count")],
            key=lambda p: p["citation_count"], reverse=True,
        )[:6]
        if top:
            for p in top:
                st.markdown(_paper_card(p), unsafe_allow_html=True)
        else:
            st.markdown(
                '<div class="empty-state" style="padding:20px">'
                '<div class="empty-body">Citation counts are fetched automatically when papers are added.</div></div>',
                unsafe_allow_html=True,
            )

    with br:
        st.markdown('<div class="section-title">Priority Reading Queue</div>', unsafe_allow_html=True)
        urgent = [
            p for p in papers
            if p.get("status") in ("unread", "skimmed")
            and (p.get("relevance") or 0) >= 4
        ]
        urgent.sort(key=lambda p: (-(p.get("relevance") or 0), -(p.get("citation_count") or 0)))
        if urgent:
            for p in urgent[:6]:
                st.markdown(_paper_card(p), unsafe_allow_html=True)
        else:
            st.markdown(
                '<div class="empty-state" style="padding:20px">'
                '<div class="empty-body" style="color:#3fb950 !important">✓ All high-relevance papers have been read.</div></div>',
                unsafe_allow_html=True,
            )


# ═════════════════════════════════════════════════════════════════════════════
# PAGE 2 — PAPERS BROWSER
# ═════════════════════════════════════════════════════════════════════════════

elif page == "Papers":
    st.markdown(
        '<div class="page-title">Papers</div>'
        '<div class="page-subtitle">Browse, filter, and annotate your library</div>',
        unsafe_allow_html=True,
    )

    # ── Filter bar ────────────────────────────────────────────────────────
    f1, f2, f3, f4, f5 = st.columns([2, 2, 2, 2, 3])
    pillar_opts = ["All", "pure_math", "computational", "financial", "unassigned"]
    status_opts = ["All", "unread", "skimmed", "read", "deep_read"]
    sort_map    = {
        "Citations ↓": "citation_count",
        "Year ↓":      "year",
        "Relevance ↓": "relevance",
        "Title A–Z":   "title",
        "Date Added":  "added_at",
    }
    all_tags = db.get_tags()

    chosen_pillar = f1.selectbox("Pillar",  pillar_opts, index=0)
    chosen_status = f2.selectbox("Status",  status_opts, index=0)
    chosen_tag    = f3.selectbox("Tag",     ["All"] + all_tags, index=0)
    chosen_sort   = f4.selectbox("Sort",    list(sort_map.keys()), index=0)
    search_text   = f5.text_input("Search", placeholder="Title, author, abstract…")

    papers = db.get_all_papers(
        pillar  = None if chosen_pillar == "All" else chosen_pillar,
        status  = None if chosen_status == "All" else chosen_status,
        tag     = None if chosen_tag    == "All" else chosen_tag,
        sort_by = sort_map[chosen_sort],
    )
    if search_text:
        q = search_text.lower()
        papers = [p for p in papers if
                  q in (p.get("title") or "").lower() or
                  q in (p.get("abstract") or "").lower() or
                  q in (p.get("notes") or "").lower() or
                  any(q in a["name"].lower() for a in p.get("authors", []))]

    total_str = f"**{len(papers)}** paper{'s' if len(papers) != 1 else ''}"
    st.markdown(f"<div style='color:#8b949e;font-size:0.82rem;margin-bottom:0.5rem'>{total_str}</div>",
                unsafe_allow_html=True)
    st.divider()

    if not papers:
        st.markdown(
            '<div class="empty-state">'
            '<div class="empty-icon">🔍</div>'
            '<div class="empty-title">No papers match</div>'
            '<div class="empty-body">Try adjusting the filters above.</div>'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        for p in papers:
            pillar = p.get("pillar") or "unassigned"
            colour = PILLAR_HEX[pillar]
            status = p.get("status") or "unread"
            authors = ", ".join(a["name"] for a in p.get("authors", [])[:2])
            if len(p.get("authors", [])) > 2:
                authors += " et al."

            expander_label = f'{STATUS_DOT.get(status,"○")}  {p["title"][:80]}{"…" if len(p["title"])>80 else ""}  ({p.get("year","?")})'

            with st.expander(expander_label, expanded=False):
                # Header row
                header_left, header_right = st.columns([5, 1])
                with header_left:
                    st.markdown(
                        f'{_status_badge(status)} {_pillar_badge(pillar)}'
                        + (f' {_tag_chips(p.get("tags") or [])}' if p.get("tags") else ""),
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f'<div style="font-size:0.78rem;color:#6e7681;margin-top:4px">'
                        f'{authors}'
                        + (f' · <em style="color:#8b949e">{p["venue"]}</em>' if p.get("venue") else "")
                        + (f' · {p["citation_count"]:,} citations' if p.get("citation_count") else "")
                        + (f' · Chapter: <span style="color:#8b949e">{p["chapter"].replace("_"," ")}</span>' if p.get("chapter") else "")
                        + f'</div>',
                        unsafe_allow_html=True,
                    )

                # Links
                link_parts = []
                if p.get("doi"):      link_parts.append(f'<a href="https://doi.org/{p["doi"]}">DOI</a>')
                if p.get("url"):      link_parts.append(f'<a href="{p["url"]}">Semantic Scholar</a>')
                if p.get("pdf_url"):  link_parts.append(f'<a href="{p["pdf_url"]}">PDF ↗</a>')
                if link_parts:
                    st.markdown(
                        '<div style="font-size:0.78rem;margin-top:4px">' + " · ".join(link_parts) + '</div>',
                        unsafe_allow_html=True,
                    )

                st.divider()

                # Abstract + TLDR
                if p.get("abstract"):
                    st.markdown(
                        f'<div style="font-size:0.82rem;color:#8b949e;line-height:1.6">{p["abstract"]}</div>',
                        unsafe_allow_html=True,
                    )
                if p.get("tldr"):
                    st.markdown(
                        f'<div style="font-size:0.78rem;color:#6e7681;font-style:italic;'
                        f'margin-top:8px;padding-top:8px;border-top:1px solid #21262d">'
                        f'<strong style="color:#8b949e">TL;DR:</strong> {p["tldr"]}</div>',
                        unsafe_allow_html=True,
                    )

                # Extraction
                ext_html = _ext_grid(p)
                if ext_html:
                    st.markdown(
                        '<div style="margin-top:12px"><div class="section-title">Structured Extraction</div>'
                        + ext_html + '</div>',
                        unsafe_allow_html=True,
                    )

                # Notes
                if p.get("notes"):
                    st.markdown(
                        '<div style="margin-top:12px"><div class="section-title">Notes</div>'
                        f'<div style="font-size:0.82rem;color:#c9d1d9;line-height:1.6;'
                        f'background:#0d1117;border:1px solid #21262d;border-radius:6px;padding:10px 14px">'
                        f'{p["notes"]}</div></div>',
                        unsafe_allow_html=True,
                    )

                # Quick-edit
                st.markdown('<div style="margin-top:14px"><div class="section-title">Quick Edit</div></div>', unsafe_allow_html=True)
                qe1, qe2, qe3, qe4 = st.columns([2, 2, 1, 1])
                new_status = qe1.selectbox(
                    "Status",
                    ["unread", "skimmed", "read", "deep_read"],
                    index=["unread","skimmed","read","deep_read"].index(p.get("status","unread")),
                    key=f"st_{p['id']}",
                )
                new_pillar = qe2.selectbox(
                    "Pillar",
                    ["", "pure_math", "computational", "financial"],
                    index=(["","pure_math","computational","financial"].index(p.get("pillar") or "")),
                    key=f"pl_{p['id']}",
                )
                new_rel = qe3.select_slider(
                    "Relevance",
                    options=[0,1,2,3,4,5],
                    value=p.get("relevance") or 0,
                    key=f"rl_{p['id']}",
                )
                qe4.markdown("<br>", unsafe_allow_html=True)
                if qe4.button("Save", key=f"sv_{p['id']}", type="primary"):
                    upd: dict = {"status": new_status}
                    if new_pillar: upd["pillar"] = new_pillar
                    if new_rel:    upd["relevance"] = new_rel
                    db.update_paper(p["id"], **upd)
                    st.toast("Saved ✓", icon="✅")
                    st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
# PAGE 3 — CITATION GRAPH
# ═════════════════════════════════════════════════════════════════════════════

elif page == "Citation Graph":
    import networkx as nx
    from pyvis.network import Network
    import os as _os

    st.markdown(
        '<div class="page-title">Citation Graph</div>'
        '<div class="page-subtitle">Interactive network — drag to explore, hover for details</div>',
        unsafe_allow_html=True,
    )

    papers    = db.get_all_papers()
    citations = db.get_all_citations()

    if not papers:
        st.markdown(
            '<div class="empty-state">'
            '<div class="empty-icon">🕸</div>'
            '<div class="empty-title">No papers in library</div>'
            '<div class="empty-body">Add papers first using the MCP tools.</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.stop()

    # Controls
    gc1, gc2 = st.columns([3, 3])
    show_pillar = gc1.multiselect(
        "Pillars",
        ["pure_math", "computational", "financial", "unassigned"],
        default=["pure_math", "computational", "financial", "unassigned"],
        format_func=lambda x: PILLAR_LABEL[x],
    )
    show_status = gc2.multiselect(
        "Reading status",
        ["unread", "skimmed", "read", "deep_read"],
        default=["unread", "skimmed", "read", "deep_read"],
        format_func=lambda x: STATUS_LABEL[x],
    )

    paper_map = {
        p["id"]: p for p in papers
        if (p.get("pillar") or "unassigned") in show_pillar
        and (p.get("status") or "unread")    in show_status
    }

    if not paper_map:
        st.warning("No papers match. Adjust the filters above.")
        st.stop()

    # Build graph
    G = nx.DiGraph()
    for pid, p in paper_map.items():
        pillar = p.get("pillar") or "unassigned"
        if p.get("authors"):
            short_label = p["authors"][0].get("name","").split()[-1] + f" {p.get('year','')}"
        else:
            short_label = p["title"][:30]
        tooltip = (
            f"<b>{p['title']}</b><br>"
            + (f"<i>{', '.join(a['name'] for a in p['authors'][:2])}</i><br>" if p.get("authors") else "")
            + f"{p.get('year','?')} · {PILLAR_LABEL[pillar]}<br>"
            + (f"{p['citation_count']:,} citations" if p.get("citation_count") else "")
        )
        G.add_node(
            pid,
            label=short_label,
            title=tooltip,
            color={"background": PILLAR_HEX[pillar], "border": PILLAR_HEX[pillar],
                   "highlight": {"background": "#e6edf3", "border": "#e6edf3"}},
            size=max(12, min(45, (p.get("citation_count") or 0) // 40 + 12)),
            font={"color": "#e6edf3", "size": 11, "face": "monospace"},
            borderWidth=2,
            shape="dot",
        )
    for c in citations:
        if c["citing_id"] in paper_map and c["cited_id"] in paper_map:
            G.add_edge(
                c["citing_id"], c["cited_id"],
                color={"color": "#30363d", "highlight": "#58a6ff", "hover": "#58a6ff"},
                width=2 if c.get("is_influential") else 1,
                arrows="to",
            )

    # Stats bar
    n, e = G.number_of_nodes(), G.number_of_edges()
    st.markdown(
        f'<div style="display:flex;gap:20px;margin:8px 0 12px;font-size:0.78rem;color:#6e7681">'
        f'<span><strong style="color:#e6edf3">{n}</strong> nodes</span>'
        f'<span><strong style="color:#e6edf3">{e}</strong> edges</span>'
        f'<span>Node size ∝ citation count</span></div>',
        unsafe_allow_html=True,
    )

    # Render
    net = Network(height="620px", width="100%", bgcolor="#0d1117",
                  font_color="#e6edf3", directed=True)
    net.from_nx(G)
    net.set_options("""{
      "physics": {
        "forceAtlas2Based": {
          "gravitationalConstant": -80, "centralGravity": 0.004,
          "springLength": 130, "springConstant": 0.06
        },
        "maxVelocity": 50, "solver": "forceAtlas2Based",
        "timestep": 0.35, "stabilization": {"iterations": 180}
      },
      "edges": {
        "smooth": {"type": "continuous"},
        "arrows": {"to": {"enabled": true, "scaleFactor": 0.5}}
      },
      "interaction": {"hover": true, "tooltipDelay": 100, "navigationButtons": false}
    }""")

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        tmp_path = f.name
    net.save_graph(tmp_path)
    html_content = Path(tmp_path).read_text(encoding="utf-8")
    _os.unlink(tmp_path)
    st.components.v1.html(html_content, height=630, scrolling=False)

    # Legend
    st.markdown("<br>", unsafe_allow_html=True)
    lcols = st.columns(4)
    for i, (pillar, colour) in enumerate(PILLAR_HEX.items()):
        cnt = s["by_pillar"].get(pillar, 0) if db.db_exists() else 0
        lcols[i].markdown(
            f'<div style="display:flex;align-items:center;gap:8px;padding:8px">'
            f'<div style="width:12px;height:12px;border-radius:50%;background:{colour};flex-shrink:0"></div>'
            f'<span style="font-size:0.8rem;color:#c9d1d9">{PILLAR_LABEL[pillar]}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Bridge table
    if e > 0:
        bridges = []
        for citing_id, cited_id in G.edges():
            cp, tp = paper_map.get(citing_id, {}), paper_map.get(cited_id, {})
            if cp.get("pillar") and tp.get("pillar") and cp["pillar"] != tp["pillar"]:
                bridges.append({
                    "Paper":      cp["title"][:65],
                    "Pillar":     PILLAR_LABEL[cp["pillar"]],
                    "→ Cites":    tp["title"][:55],
                    "Into Pillar": PILLAR_LABEL[tp["pillar"]],
                })
        if bridges:
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown('<div class="section-title">Bridge Papers — Cross-Pillar Links</div>', unsafe_allow_html=True)
            import pandas as pd
            st.dataframe(
                pd.DataFrame(bridges),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Paper":       st.column_config.TextColumn(width="large"),
                    "→ Cites":     st.column_config.TextColumn(width="large"),
                    "Pillar":      st.column_config.TextColumn(width="small"),
                    "Into Pillar": st.column_config.TextColumn(width="small"),
                },
            )


# ═════════════════════════════════════════════════════════════════════════════
# PAGE 4 — EDIT PAPER
# ═════════════════════════════════════════════════════════════════════════════

elif page == "Edit Paper":
    papers = db.get_all_papers()
    if not papers:
        st.markdown(
            '<div class="empty-state"><div class="empty-icon">📭</div>'
            '<div class="empty-title">Library is empty</div></div>',
            unsafe_allow_html=True,
        )
        st.stop()

    options = {f"{p['title'][:75]} ({p.get('year','?')})": p["id"] for p in papers}
    chosen  = st.selectbox("Select paper to edit", list(options.keys()), label_visibility="visible")
    p       = db.get_paper(options[chosen])
    if not p:
        st.error("Paper not found.")
        st.stop()

    # Header
    authors_str = ", ".join(a["name"] for a in p.get("authors", []))
    pillar = p.get("pillar") or "unassigned"
    colour = PILLAR_HEX[pillar]

    st.markdown(
        f'<div style="background:#161b22;border:1px solid #21262d;border-left:3px solid {colour};'
        f'border-radius:10px;padding:16px 20px;margin:12px 0 20px">'
        f'<div style="font-size:1.05rem;font-weight:700;color:#e6edf3;line-height:1.3">{p["title"]}</div>'
        f'<div style="font-size:0.8rem;color:#8b949e;margin-top:5px">{authors_str}</div>'
        f'<div style="margin-top:8px">{_status_badge(p.get("status","unread"))} {_pillar_badge(pillar)}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if p.get("abstract"):
        with st.expander("Abstract"):
            st.markdown(
                f'<div style="font-size:0.82rem;color:#8b949e;line-height:1.6">{p["abstract"]}</div>',
                unsafe_allow_html=True,
            )

    # Fields — two column layout
    st.markdown('<div class="section-title" style="margin-top:16px">Classification</div>', unsafe_allow_html=True)
    e1, e2, e3 = st.columns(3)
    new_status  = e1.selectbox("Reading Status", ["unread","skimmed","read","deep_read"],
                               index=["unread","skimmed","read","deep_read"].index(p.get("status","unread")))
    new_pillar  = e2.selectbox("Research Pillar", ["","pure_math","computational","financial"],
                               index=(["","pure_math","computational","financial"].index(p.get("pillar") or "")))
    new_chapter = e3.selectbox("Dissertation Chapter", CHAPTERS,
                               index=CHAPTERS.index(p.get("chapter") or ""))

    e4, e5 = st.columns([1, 3])
    new_rel      = e4.select_slider("Relevance", options=[0,1,2,3,4,5], value=p.get("relevance") or 0)
    new_tags_raw = e5.text_input("Tags (comma-separated)", value=", ".join(p.get("tags") or []))

    st.markdown('<div class="section-title" style="margin-top:16px">Structured Extraction</div>', unsafe_allow_html=True)
    s1, s2 = st.columns(2)
    new_meth = s1.text_area("Methodology",        value=p.get("methodology") or "",       height=90)
    new_lim  = s2.text_area("Limitations",         value=p.get("limitations") or "",       height=90)
    new_math = s1.text_area("Math Framework",      value=p.get("math_framework") or "",    height=90)
    new_conv = s2.text_area("Convergence Bounds",  value=p.get("convergence_bounds") or "", height=90)

    st.markdown('<div class="section-title" style="margin-top:16px">Notes</div>', unsafe_allow_html=True)
    new_notes = st.text_area("", value=p.get("notes") or "", height=180, label_visibility="collapsed")

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("💾  Save All Changes", type="primary"):
        db.update_paper(p["id"], **{
            "status":             new_status,
            "pillar":             new_pillar or None,
            "chapter":            new_chapter or None,
            "relevance":          new_rel or None,
            "tags":               [t.strip() for t in new_tags_raw.split(",") if t.strip()],
            "notes":              new_notes or None,
            "methodology":        new_meth or None,
            "limitations":        new_lim  or None,
            "math_framework":     new_math or None,
            "convergence_bounds": new_conv or None,
        })
        st.toast("Changes saved ✓", icon="✅")
        st.rerun()
