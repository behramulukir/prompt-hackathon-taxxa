"""Inline memo renderer — the document-style answer surface (LEFT column).

The memo is rendered as a self-contained HTML component (not Streamlit
markdown) so the citation pills can have proper :hover tooltips and the
typography lives in its own iframe-isolated stylesheet.

Layout from hybrid_cinematic_concept.md:
  - Meta line: "Memo · date · sources in force at issuance"
  - Title and sub-line
  - Assumption chip (Clarifier-surfaced default)
  - Body sections (one per paragraph in result.answer)
  - Inline conflict callout (positioned between sections, not at end)
  - Citations list (full pills at the bottom)
"""

from __future__ import annotations

import re
from datetime import date

from src.models import AnswerResult
from web.components.source_pill import render_pill_full, render_pill_inline

_SOURCE_TOKEN_RE = re.compile(r"\[\s*Source\s+(\d+)\s*\]")


def render_html(result: AnswerResult, today: date | None = None) -> str:
    """Return a full HTML document for the memo column."""
    today = today or date.today()
    in_force = "Finlex + Vero, in force " + today.isoformat()
    pills = result.cited_source_ids
    body_with_pills = _insert_inline_pills(result.answer, pills)

    # Compose sections with optional conflict callout interleaved.
    sections_html = _split_sections(body_with_pills, result.conflicts)
    assumption_chip = ""
    if result.assumptions:
        items = "".join(
            f'<li>{_esc(a)}</li>' for a in result.assumptions
        )
        assumption_chip = (
            '<div class="memo-assumption">'
            '<div class="memo-assumption-head">Assumption' + ("s" if len(result.assumptions) > 1 else "") + '</div>'
            f'<ul>{items}</ul>'
            '</div>'
        )

    if pills:
        citations = (
            '<div class="memo-citations">'
            '<div class="memo-citations-head">Citations</div>'
            + "".join(render_pill_full(i + 1, cid) for i, cid in enumerate(pills))
            + '</div>'
        )
    else:
        citations = '<div class="memo-citations memo-citations-empty">No sources cited.</div>'

    body = sections_html if sections_html.strip() else '<p class="memo-empty">No answer available for this question.</p>'

    return _TEMPLATE.replace("{{TODAY}}", today.isoformat()) \
                    .replace("{{IN_FORCE}}", _esc(in_force)) \
                    .replace("{{QUESTION}}", _esc(result.question)) \
                    .replace("{{ASSUMPTION_CHIP}}", assumption_chip) \
                    .replace("{{BODY}}", body) \
                    .replace("{{CITATIONS}}", citations)


def _insert_inline_pills(answer: str, cited_ids: list[str]) -> str:
    """Replace `[Source N]` tokens with hover-capable pill HTML."""
    def sub(m):
        idx = int(m.group(1))
        if idx < 1 or idx > len(cited_ids):
            # Out-of-range token — keep as plain text so the issue is visible.
            return m.group(0)
        return render_pill_inline(idx, cited_ids[idx - 1])
    # Light Markdown: bold (**...**) and paragraph breaks via blank lines.
    answer = _esc_keep_markers(answer)
    answer = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", answer, flags=re.S)
    return _SOURCE_TOKEN_RE.sub(sub, answer)


def _esc_keep_markers(s: str) -> str:
    """Escape HTML but keep our Markdown markers and pill tokens intact."""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _split_sections(body_html: str, conflicts: list[dict]) -> str:
    """Render paragraphs separated by blank lines; insert conflict callout
    between paragraphs 2 and 3 (matching the cinematic concept).
    """
    paras = [p.strip() for p in re.split(r"\n\s*\n", body_html) if p.strip()]
    rendered: list[str] = []
    callout_inserted = False
    for i, p in enumerate(paras):
        rendered.append(f'<p class="memo-para">{p}</p>')
        if conflicts and not callout_inserted and i == min(1, len(paras) - 2):
            rendered.append(_render_conflict_callout(conflicts[0]))
            callout_inserted = True
    # If only one paragraph but there's a conflict, append the callout at end.
    if conflicts and not callout_inserted:
        rendered.append(_render_conflict_callout(conflicts[0]))
    return "\n".join(rendered)


def _render_conflict_callout(c: dict) -> str:
    topic = c.get("topic") or "Authority divergence between sources"
    resolution = c.get("resolution") or "Higher authority rank prevails."
    statute = c.get("statute_position")
    guidance = c.get("guidance_position")
    rows = ""
    if statute:
        rows += f'<div class="cc-row"><span class="cc-tag cc-tag-statute">Statute</span><span>{_esc(statute)}</span></div>'
    if guidance:
        rows += f'<div class="cc-row"><span class="cc-tag cc-tag-guidance">Guidance</span><span>{_esc(guidance)}</span></div>'
    return (
        '<div class="memo-conflict">'
        '<div class="memo-conflict-head"><span class="cc-icon">⚠</span> Conflict: '
        + _esc(topic) +
        '</div>'
        + rows +
        f'<div class="cc-resolution"><strong>Resolution.</strong> {_esc(resolution)}</div>'
        '</div>'
    )


def _esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# --------------------------------------------------------------------------
# HTML template — self-contained, served via st.components.v1.html
# --------------------------------------------------------------------------

_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<style>
  :root {
    --bg: #0e1117;
    --paper: #161b22;
    --paper-2: #1f2630;
    --border: #2a3340;
    --text: #e6e8ec;
    --muted: #8a96a8;
    --finlex: #6ea8ff;
    --finlex-soft: rgba(110, 168, 255, 0.16);
    --vero: #f5a524;
    --vero-soft: rgba(245, 165, 36, 0.16);
    --conflict: #f97066;
    --conflict-soft: rgba(249, 112, 102, 0.14);
    --mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, monospace;
    --serif: "Iowan Old Style", "Georgia", "Times New Roman", serif;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13px; line-height: 1.5; }

  .memo {
    background: var(--paper); border: 1px solid var(--border);
    border-radius: 12px; padding: 22px 24px;
    max-width: 100%;
  }
  .memo-meta {
    font-family: var(--mono); font-size: 11px; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.07em;
    border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-bottom: 14px;
  }
  .memo-title {
    font-family: var(--serif); font-weight: 700; font-size: 22px;
    line-height: 1.25; margin-bottom: 4px;
  }
  .memo-sub {
    font-size: 12.5px; color: var(--muted); margin-bottom: 16px;
  }
  .memo-assumption {
    background: var(--finlex-soft); border: 1px solid var(--finlex);
    border-radius: 9px; padding: 9px 12px; margin-bottom: 14px;
    font-size: 12.5px;
  }
  .memo-assumption-head {
    font-weight: 700; color: var(--finlex); font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px;
  }
  .memo-assumption ul { margin: 0; padding-left: 18px; }
  .memo-assumption li { margin-bottom: 2px; }

  .memo-para { margin: 0 0 12px 0; }
  .memo-empty { color: var(--muted); font-style: italic; }

  /* ───────── Conflict callout ───────── */
  .memo-conflict {
    background: var(--conflict-soft); border-left: 3px solid var(--conflict);
    border-radius: 0 8px 8px 0; padding: 11px 14px; margin: 10px 0 14px;
    font-size: 12.5px;
  }
  .memo-conflict-head {
    font-weight: 700; color: var(--conflict); margin-bottom: 6px;
  }
  .cc-icon { font-size: 14px; }
  .cc-row { display: grid; grid-template-columns: 88px 1fr; gap: 8px; margin: 3px 0; }
  .cc-tag {
    font-family: var(--mono); font-size: 10.5px; font-weight: 700;
    padding: 2px 7px; border-radius: 5px; text-align: center; height: fit-content;
  }
  .cc-tag-statute { background: var(--finlex-soft); color: var(--finlex); }
  .cc-tag-guidance { background: var(--vero-soft); color: var(--vero); }
  .cc-resolution { margin-top: 6px; padding-top: 6px; border-top: 1px dashed rgba(249,112,102,0.3); }

  /* ───────── Citations ───────── */
  .memo-citations {
    margin-top: 18px; padding-top: 14px;
    border-top: 1px solid var(--border);
  }
  .memo-citations-head {
    font-weight: 700; font-size: 11px; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px;
  }
  .memo-citations-empty { color: var(--muted); font-style: italic; }

  /* ───────── Pills ───────── */
  .pill {
    position: relative;
    display: inline-flex; align-items: center; gap: 4px;
    font-family: var(--mono); font-size: 11px; font-weight: 600;
    padding: 1px 7px; border-radius: 4px;
    border: 1px solid transparent; cursor: default;
    transition: background 0.15s, border-color 0.15s;
    vertical-align: baseline;
  }
  .pill-inline { margin: 0 2px; }
  .pill-full {
    display: block; padding: 7px 10px; margin: 4px 0;
    border-radius: 7px; font-family: -apple-system, sans-serif; font-size: 12px; font-weight: 500;
  }
  .pill-finlex { background: var(--finlex-soft); color: var(--finlex); border-color: rgba(110,168,255,0.4); }
  .pill-vero   { background: var(--vero-soft);   color: var(--vero);   border-color: rgba(245,165,36,0.4); }
  .pill-unknown { background: var(--paper-2);    color: var(--muted);  border-color: var(--border); }
  .pill-inline:hover, .pill-full:hover {
    border-color: currentColor; filter: brightness(1.15);
  }
  .pill-idx { font-weight: 700; }
  .pill-rank-inline {
    background: rgba(255,255,255,0.08); color: var(--text);
    font-size: 9.5px; padding: 0 4px; border-radius: 3px; margin-left: 2px;
  }
  .pill-publisher { font-weight: 600; }
  .pill-label { color: var(--text); }
  .pill-rank { color: var(--muted); font-size: 10.5px; font-family: var(--mono); }

  /* ───────── Hover tooltip ───────── */
  .pill-tooltip {
    position: absolute; left: 50%; bottom: calc(100% + 6px);
    transform: translateX(-50%);
    min-width: 260px; max-width: 340px;
    background: #11161e; color: var(--text);
    border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 12px; font-family: -apple-system, sans-serif;
    font-weight: normal; font-size: 11.5px; line-height: 1.45;
    box-shadow: 0 6px 24px rgba(0,0,0,0.45);
    opacity: 0; pointer-events: none; transform-origin: bottom center;
    transform: translateX(-50%) translateY(4px);
    transition: opacity 0.18s, transform 0.18s; z-index: 9999;
    white-space: normal; text-align: left;
  }
  .pill:hover .pill-tooltip,
  .pill:focus .pill-tooltip,
  .pill:focus-within .pill-tooltip {
    opacity: 1; pointer-events: auto; transform: translateX(-50%) translateY(0);
  }
  .pt-head { display: block; font-size: 11px; color: var(--muted); margin-bottom: 4px; }
  .pt-label { display: block; font-weight: 700; font-size: 12.5px; margin-bottom: 3px; color: var(--text); }
  .pt-rank { display: block; font-family: var(--mono); font-size: 11px; color: var(--muted); margin-bottom: 6px; }
  .pt-excerpt { display: block; color: var(--text); font-size: 12px; margin-bottom: 6px;
    padding-top: 6px; border-top: 1px solid var(--border); }
  .pt-cid { display: block; font-family: var(--mono); font-size: 10px; color: var(--muted); word-break: break-all; }
  .pill-synth {
    display: inline-block; font-size: 9px; padding: 0 5px;
    background: rgba(138,150,168,0.15); color: var(--muted);
    border: 1px solid var(--border); border-radius: 3px; margin-left: 4px;
    text-transform: uppercase; letter-spacing: 0.05em;
  }
</style>
</head>
<body>
<div class="memo">
  <div class="memo-meta">Memo · {{TODAY}} · {{IN_FORCE}}</div>
  <div class="memo-title">{{QUESTION}}</div>
  <div class="memo-sub">Generated by GraphRAG · Finlex + Vero corpus</div>
  {{ASSUMPTION_CHIP}}
  <div class="memo-body">
    {{BODY}}
  </div>
  {{CITATIONS}}
</div>
</body></html>
"""
