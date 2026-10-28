"""
ui_components.py - small reusable Streamlit display helpers (CSS, cards, risk banner, status chips).

Only presentation lives here. Every piece of text that can come from outside (place names, API
messages) is HTML-escaped before it is placed into an HTML string.
"""
from __future__ import annotations

from html import escape

import streamlit as st

import data_service as ds
from risk import RiskCategory

CSS = """
<style>
.kn-hero{padding:1.1rem 1.3rem;border-radius:14px;background:linear-gradient(135deg,#0b3d2e,#1b6b8f);color:#fff;margin-bottom:.9rem}
.kn-hero h1{margin:0;padding:0;font-size:1.75rem;line-height:1.2;color:#fff}
.kn-hero p{margin:.3rem 0 0;opacity:.93;font-size:.98rem}
.kn-banner{border-radius:14px;padding:1rem 1.25rem;margin:.4rem 0 1rem}
.kn-banner .t{font-size:.85rem;font-weight:600;letter-spacing:.03em;text-transform:uppercase;opacity:.9}
.kn-banner .c{font-size:1.9rem;font-weight:750;line-height:1.2;margin:.1rem 0 .3rem}
.kn-banner ul{margin:.3rem 0 .5rem 1.1rem;padding:0}
.kn-banner .d{font-size:.78rem;opacity:.92;margin-top:.5rem;border-top:1px solid rgba(255,255,255,.35);padding-top:.4rem}
.kn-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.7rem;margin:.3rem 0 .9rem}
.kn-card{border:1px solid rgba(128,128,128,.3);border-radius:12px;padding:.7rem .9rem;background:var(--secondary-background-color,rgba(128,128,128,.08))}
.kn-card .l{font-size:.8rem;opacity:.8}
.kn-card .v{font-size:1.5rem;font-weight:650;line-height:1.3}
.kn-card .s{font-size:.75rem;opacity:.8}
.kn-chip{display:inline-block;padding:.15rem .65rem;border-radius:999px;border:1px solid rgba(128,128,128,.45);font-size:.82rem;margin:0 .4rem .4rem 0}
.kn-tag{display:inline-block;padding:.05rem .5rem;border-radius:6px;border:1px solid rgba(128,128,128,.45);font-size:.72rem;margin-left:.4rem;vertical-align:middle}
@media (max-width:640px){.kn-hero h1{font-size:1.35rem}.kn-banner .c{font-size:1.5rem}.kn-card .v{font-size:1.25rem}}
</style>
"""

# text colours chosen for contrast on each background; the label is always written out as well
BANNER = {
    RiskCategory.LOW: ("#2e7d32", "#ffffff", "✅"),
    RiskCategory.MODERATE: ("#f9a825", "#1a1a1a", "🟡"),
    RiskCategory.HIGH: ("#bf360c", "#ffffff", "🟠"),
    RiskCategory.VERY_HIGH: ("#b71c1c", "#ffffff", "🔴"),
}
STATUS_ICON = {ds.STATUS_LIVE: "🟢", ds.STATUS_CACHED: "🟠", ds.STATUS_UNAVAILABLE: "🔴", ds.STATUS_DEMO: "🟣"}


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str) -> None:
    st.markdown(f'<div class="kn-hero"><h1>🛡️ {escape(title)}</h1><p>{escape(subtitle)}</p></div>', unsafe_allow_html=True)


def risk_banner(overall) -> None:
    bg, fg, icon = BANNER[overall.category]
    reasons = "".join(f"<li>{escape(r)}</li>" for r in overall.reasons[:5])
    caveats = "".join(f"<div>⚠️ {escape(c)}</div>" for c in overall.caveats)
    html = (f'<div class="kn-banner" style="background:{bg};color:{fg}" role="status">'
            f'<div class="t">Overall environmental risk (app-generated)</div>'
            f'<div class="c">{icon} {escape(overall.category.label)}</div>'
            f'<div>{escape(overall.headline)}</div>'
            f'<div style="margin-top:.4rem"><strong>Why:</strong></div><ul>{reasons}</ul>'
            f'<div><strong>What to do:</strong> {escape(overall.recommendation)}</div>{caveats}'
            f'<div class="d">{escape(overall.disclaimer)}</div></div>')
    st.markdown(html, unsafe_allow_html=True)


def metric_grid(items: list, tag: str = "") -> None:
    """items: dicts with icon, label, value, sub. `tag` marks the whole group (e.g. 'Forecast')."""
    cards = "".join(
        f'<div class="kn-card"><div class="l">{escape(i.get("icon", ""))} {escape(i["label"])}</div>'
        f'<div class="v">{escape(str(i["value"]))}</div><div class="s">{escape(str(i.get("sub", "")))}</div></div>'
        for i in items)
    st.markdown(f'<div class="kn-grid">{cards}</div>', unsafe_allow_html=True)


def section(title: str, tag: str) -> None:
    st.markdown(f'#### {title} <span class="kn-tag">{escape(tag)}</span>', unsafe_allow_html=True)


def status_chips(status_items: list) -> None:
    chips = "".join(f'<span class="kn-chip">{STATUS_ICON.get(i.status, "⚪")} <strong>{escape(i.name)}:</strong> '
                    f'{escape(i.label)}</span>' for i in status_items)
    st.markdown(chips, unsafe_allow_html=True)


def show_chart(fig, key=None) -> None:
    """st.plotly_chart across Streamlit versions (newer: width='stretch'; older: use_container_width)."""
    try:
        st.plotly_chart(fig, width="stretch", key=key)
    except TypeError:
        st.plotly_chart(fig, use_container_width=True, key=key)
