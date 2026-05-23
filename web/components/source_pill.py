"""Citation pill rendering.

A "pill" is the inline `[Source N]` chip that appears in the memo body and in
the citations list. It carries:
  - publisher (drives color: Finlex blue, Vero amber)
  - authority rank label, e.g. "rank 100, binding"
  - hover tooltip with the excerpt

Authority rank surfacing is a MANDATORY demo requirement — the V3.2 ranks are
provisional and the demo viewer must be able to spot rank errors. Rank text
appears in the pill itself, not only in the tooltip.
"""

from __future__ import annotations

from web.data.source_meta import SourceMeta, lookup


def render_pill_inline(idx: int, chunk_id: str) -> str:
    """Inline pill for use inside the memo body (replaces `[Source N]` tokens).

    Compact: just "[N]" with publisher color + tooltip on hover.
    """
    meta = lookup(chunk_id)
    pub = (meta.get("publisher") or "unknown").lower()
    css = "pill pill-inline pill-" + pub
    rank = meta.get("authority_rank")
    tier = meta.get("authority_tier") or "—"
    tooltip = _tooltip_html(idx, chunk_id, meta)
    return (
        f'<span class="{css}" tabindex="0">'
        f'[{idx}]'
        f'<span class="pill-rank">{_rank_short(rank, tier)}</span>'
        f'{tooltip}'
        f'</span>'
    )


def render_pill_full(idx: int, chunk_id: str) -> str:
    """Full-width pill for the citations list at the bottom of the memo."""
    meta = lookup(chunk_id)
    pub = (meta.get("publisher") or "unknown").lower()
    label = meta.get("label") or chunk_id.rsplit("/", 1)[-1]
    rank = meta.get("authority_rank") or 0
    tier = meta.get("authority_tier") or "—"
    publisher_name = _publisher_display(pub, meta.get("subcorpus") or "")
    tooltip = _tooltip_html(idx, chunk_id, meta)
    return (
        f'<div class="pill pill-full pill-{pub}" tabindex="0">'
        f'<span class="pill-idx">[Source {idx}]</span> '
        f'<span class="pill-publisher">{_esc(publisher_name)}</span>'
        f' &middot; <span class="pill-label">{_esc(label)}</span>'
        f' <span class="pill-rank">(rank {rank}, {_esc(tier)})</span>'
        f'{tooltip}'
        f'</div>'
    )


def _tooltip_html(idx: int, chunk_id: str, meta: SourceMeta) -> str:
    excerpt = meta.get("excerpt") or "(no excerpt)"
    label = meta.get("label") or chunk_id.rsplit("/", 1)[-1]
    pub = (meta.get("publisher") or "unknown").lower()
    pub_disp = _publisher_display(pub, meta.get("subcorpus") or "")
    rank = meta.get("authority_rank") or 0
    tier = meta.get("authority_tier") or "—"
    synth_flag = '<span class="pill-synth">synthetic</span>' if meta.get("synthetic") else ""
    return (
        '<span class="pill-tooltip">'
        f'<span class="pt-head"><strong>[Source {idx}]</strong> '
        f'{_esc(pub_disp)} {synth_flag}</span>'
        f'<span class="pt-label">{_esc(label)}</span>'
        f'<span class="pt-rank">rank {rank}, {_esc(tier)}</span>'
        f'<span class="pt-excerpt">{_esc(excerpt)}</span>'
        f'<span class="pt-cid">{_esc(_short_cid(chunk_id))}</span>'
        '</span>'
    )


def _rank_short(rank, tier) -> str:
    if not rank:
        return ""
    t = (tier or "").upper()[:1] or "?"
    return f' <span class="pill-rank-inline">{rank}{t}</span>'


def _publisher_display(pub: str, subcorpus: str) -> str:
    if pub == "finlex":
        if subcorpus == "kho":
            return "Finlex · KHO"
        if subcorpus.startswith("laki"):
            return "Finlex · Laki"
        if subcorpus.startswith("asetus"):
            return "Finlex · Asetus"
        return "Finlex"
    if pub == "vero":
        nice = {
            "vero_ohje": "Vero · Ohje",
            "vero_paatos": "Vero · Päätös",
            "vero_kannanotto": "Vero · Kannanotto",
            "vero_kvl": "Vero · KVL",
        }.get(subcorpus, "Vero")
        return nice
    return pub.title() if pub else "Unknown"


def _short_cid(cid: str) -> str:
    parts = cid.split("/")
    if len(parts) <= 3:
        return cid
    return parts[0] + "/" + parts[1] + "/…/" + parts[-1]


def _esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
