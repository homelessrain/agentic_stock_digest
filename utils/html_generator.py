"""
Convert Markdown-style stock research text into a standalone HTML document.

Handles common patterns from LLM digest output: ATX headings, horizontal rules,
GFM-style tables, bullet/numbered lists, blockquotes, **bold**, and *italic*.

Use :class:`StockReportHtmlGenerator` from ``send_digest`` or other callers; the
CLI entry point remains for ad-hoc file conversion.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from collections.abc import Sequence
from pathlib import Path


def _inline_format(text: str) -> str:
    """Apply **bold** and *italic* after escaping other HTML."""
    if not text:
        return ""

    segments: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if i < n - 1 and text[i : i + 2] == "**":
            end = text.find("**", i + 2)
            if end == -1:
                segments.append(html.escape(text[i:]))
                break
            inner = html.escape(text[i + 2 : end])
            segments.append(f"<strong>{inner}</strong>")
            i = end + 2
            continue
        if text[i] == "*":
            end = text.find("*", i + 1)
            if end == -1 or end == i + 1:
                segments.append(html.escape(text[i]))
                i += 1
                continue
            inner = html.escape(text[i + 1 : end])
            segments.append(f"<em>{inner}</em>")
            i = end + 1
            continue
        next_star = text.find("*", i)
        if next_star == -1:
            segments.append(html.escape(text[i:]))
            break
        segments.append(html.escape(text[i:next_star]))
        i = next_star
    return "".join(segments)


def _is_table_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.count("|") >= 2


def _is_table_separator(line: str) -> bool:
    s = line.strip().strip("|")
    if not s:
        return False
    cells = [c.strip() for c in s.split("|")]
    return all(re.fullmatch(r":?-{3,}:?", c) is not None for c in cells if c)


def _parse_table_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _table_to_html(rows: list[list[str]], has_header: bool) -> str:
    if not rows:
        return ""
    body_start = 1 if has_header else 0
    parts = ['<div class="table-wrap"><table>']
    if has_header and rows:
        parts.append("<thead><tr>")
        for cell in rows[0]:
            parts.append(f"<th>{_inline_format(cell)}</th>")
        parts.append("</tr></thead>")
    parts.append("<tbody>")
    for row in rows[body_start:]:
        parts.append("<tr>")
        for cell in row:
            parts.append(f"<td>{_inline_format(cell)}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def _flush_paragraph(buf: list[str], out: list[str]) -> None:
    if not buf:
        return
    text = "\n".join(buf).strip()
    buf.clear()
    if not text:
        return
    out.append(f'<p class="paragraph">{_inline_format(text)}</p>')


def _parse_blocks(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    i = 0
    par_buf: list[str] = []

    def flush_par() -> None:
        _flush_paragraph(par_buf, out)

    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()

        if stripped == "":
            flush_par()
            i += 1
            continue

        if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", stripped):
            flush_par()
            out.append('<hr class="rule" />')
            i += 1
            continue

        m = _HEADING_RE.match(stripped)
        if m:
            flush_par()
            level = len(m.group(1))
            title = m.group(2).strip()
            tag = f"h{min(level, 6)}"
            css = "doc-title" if level == 1 else "section-heading"
            out.append(f'<{tag} class="{css}">{_inline_format(title)}</{tag}>')
            i += 1
            continue

        if stripped.startswith(">"):
            flush_par()
            quote_lines: list[str] = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                q = lines[i].strip()
                quote_lines.append(q[1:].lstrip() if q.startswith(">") else q)
                i += 1
            qtext = "\n".join(quote_lines).strip()
            out.append(f'<blockquote class="callout">{_inline_format(qtext)}</blockquote>')
            continue

        if _is_table_row(raw):
            flush_par()
            table_rows: list[list[str]] = [_parse_table_row(lines[i])]
            i += 1
            has_header = bool(i < len(lines) and _is_table_separator(lines[i]))
            if has_header:
                i += 1
            while i < len(lines) and _is_table_row(lines[i]):
                if _is_table_separator(lines[i]):
                    i += 1
                    continue
                table_rows.append(_parse_table_row(lines[i]))
                i += 1
            out.append(_table_to_html(table_rows, has_header))
            continue

        if re.match(r"^\s*-\s+", raw):
            flush_par()
            items: list[str] = []
            while i < len(lines) and re.match(r"^\s*-\s+", lines[i]):
                item = re.sub(r"^\s*-\s+", "", lines[i]).strip()
                items.append(f"<li>{_inline_format(item)}</li>")
                i += 1
            out.append(f'<ul class="bullet-list">{"".join(items)}</ul>')
            continue

        if re.match(r"^\s*\d+\.\s+", raw):
            flush_par()
            items = []
            while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i]):
                item = re.sub(r"^\s*\d+\.\s+", "", lines[i]).strip()
                items.append(f"<li>{_inline_format(item)}</li>")
                i += 1
            out.append(f'<ol class="numbered-list">{"".join(items)}</ol>')
            continue

        par_buf.append(raw.strip())
        i += 1

    flush_par()
    return "\n".join(out)


def _document_shell(body: str, title: str) -> str:
    safe_title = html.escape(title)
    # Page `<title>` is always set; add a visible masthead unless the body already
    # opens with an h1 from a leading Markdown `#` line.
    visible_heading = ""
    if not re.match(r'^\s*<h1\s+class="doc-title"', body):
        visible_heading = f'<h1 class="doc-title">{safe_title}</h1>\n'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{safe_title}</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --paper: #ffffff;
      --ink: #1a1d26;
      --muted: #5c6370;
      --accent: #0f766e;
      --border: #e2e5ec;
      --quote-bg: #f0fdf9;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      font-size: 17px;
      line-height: 1.65;
      color: var(--ink);
      background: var(--bg);
    }}
    .page {{
      max-width: 880px;
      margin: 0 auto;
      padding: 2.5rem 1.5rem 4rem;
    }}
    article {{
      background: var(--paper);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 2.25rem 2.5rem;
      box-shadow: 0 12px 40px rgba(15, 23, 42, 0.06);
    }}
    .doc-title {{
      font-size: 1.85rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      margin: 0 0 0.5rem;
      color: #0b1220;
    }}
    .section-heading {{
      font-size: 1.25rem;
      font-weight: 650;
      margin: 2rem 0 0.75rem;
      padding-bottom: 0.35rem;
      border-bottom: 2px solid rgba(15, 118, 110, 0.25);
      color: #111827;
    }}
    h3.section-heading {{ font-size: 1.1rem; border-bottom-width: 1px; margin-top: 1.5rem; }}
    h4.section-heading, h5.section-heading, h6.section-heading {{
      font-size: 1rem;
      font-weight: 600;
      border-bottom: none;
      margin-top: 1.25rem;
      color: #374151;
    }}
    .paragraph {{
      margin: 0 0 1rem;
      color: var(--ink);
    }}
    .rule {{
      border: none;
      border-top: 1px solid var(--border);
      margin: 1.75rem 0;
    }}
    .bullet-list, .numbered-list {{
      margin: 0 0 1.25rem 1.1rem;
      padding: 0;
    }}
    .bullet-list li, .numbered-list li {{
      margin-bottom: 0.45rem;
    }}
    .callout {{
      margin: 1.25rem 0;
      padding: 1rem 1.15rem;
      border-left: 4px solid var(--accent);
      background: var(--quote-bg);
      color: #134e4a;
      border-radius: 0 8px 8px 0;
    }}
    .table-wrap {{
      overflow-x: auto;
      margin: 1rem 0 1.5rem;
      border: 1px solid var(--border);
      border-radius: 8px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.95rem;
      min-width: 520px;
    }}
    th, td {{
      padding: 0.65rem 0.85rem;
      border-bottom: 1px solid var(--border);
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: #f8fafc;
      font-weight: 600;
      color: #0f172a;
    }}
    tr:last-child td {{ border-bottom: none; }}
    tr:nth-child(even) td {{ background: #fafbfe; }}
    strong {{ font-weight: 650; color: #0b1220; }}
    em {{ color: var(--muted); }}
    footer.report-meta {{
      margin-top: 2rem;
      font-size: 0.8rem;
      color: var(--muted);
      text-align: center;
    }}
    .feedback-bar {{
      margin-top: 2.5rem;
      padding-top: 1.5rem;
      border-top: 1px solid var(--border);
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }}
    .feedback-label {{
      font-size: 0.9rem;
      color: var(--muted);
    }}
    .feedback-btn {{
      background: none;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.4rem 0.85rem;
      font-size: 1.15rem;
      cursor: pointer;
      transition: background 0.15s, border-color 0.15s, transform 0.1s;
      line-height: 1;
    }}
    .feedback-btn:hover {{
      background: var(--bg);
      border-color: var(--accent);
    }}
    .feedback-btn.active-up {{
      background: #d1fae5;
      border-color: var(--accent);
    }}
    .feedback-btn.active-down {{
      background: #fee2e2;
      border-color: #dc2626;
    }}
    .feedback-btn:active {{ transform: scale(0.93); }}
    .feedback-thanks {{
      font-size: 0.85rem;
      color: var(--accent);
      display: none;
    }}
  </style>
</head>
<body>
  <div class="page">
    <article>
{visible_heading}{body}
      <div class="feedback-bar">
        <span class="feedback-label">Was this report helpful?</span>
        <button class="feedback-btn" id="btn-up" onclick="vote('up')" title="Thumbs up">&#128077;</button>
        <button class="feedback-btn" id="btn-down" onclick="vote('down')" title="Thumbs down">&#128078;</button>
        <span class="feedback-thanks" id="feedback-thanks">Thanks for your feedback!</span>
      </div>
    </article>
    <footer class="report-meta">
      <a href="https://github.com/homelessrain/agentic_stock_digest" target="_blank" rel="noopener">View on GitHub: agentic_stock_digest</a>
    </footer>
    <script>
      function vote(dir) {{
        var up = document.getElementById('btn-up');
        var down = document.getElementById('btn-down');
        var thanks = document.getElementById('feedback-thanks');
        up.classList.remove('active-up');
        down.classList.remove('active-down');
        if (dir === 'up') {{ up.classList.add('active-up'); }}
        else {{ down.classList.add('active-down'); }}
        thanks.style.display = 'inline';
      }}
    </script>
  </div>
</body>
</html>
"""


def infer_title(text: str, fallback: str = "Stock research report") -> str:
    for line in text.splitlines():
        s = line.strip()
        m = _HEADING_RE.match(s)
        if m:
            return re.sub(r"\*{2,}", "", m.group(2)).strip() or fallback
    return fallback


class StockReportHtmlGenerator:
    """
    Build a standalone HTML page from one or more agent response strings
    (Markdown-like sections).
    """

    def __init__(self, *, document_title: str | None = None) -> None:
        self.default_document_title = document_title

    def body_html(self, text: str) -> str:
        """Return only the inner HTML fragment (inside ``<article>``), no shell."""
        return _parse_blocks(text)

    def to_html(self, text: str, *, document_title: str | None = None) -> str:
        """
        Convert a single Markdown-like report into a full HTML document.

        Title is ``document_title``, or ``self.default_document_title``, or the
        first heading in ``text``.
        """
        title = document_title or self.default_document_title or infer_title(text)
        body = self.body_html(text)
        return _document_shell(body, title)

    def to_html_from_responses(
        self,
        responses: Sequence[str],
        *,
        document_title: str | None = None,
        section_separator: str = "\n\n---\n\n",
    ) -> str:
        """
        Join multiple agent replies into one report, then build the full HTML page.

        Empty or whitespace-only entries are skipped. Sections are separated by
        ``section_separator`` (default: a horizontal rule in Markdown).
        """
        parts = [r.strip() for r in responses if r and r.strip()]
        combined = section_separator.join(parts)
        title = document_title or self.default_document_title or infer_title(combined)
        body = self.body_html(combined)
        return _document_shell(body, title)


def convert_report_text_to_html(text: str, *, document_title: str | None = None) -> str:
    """Backward-compatible wrapper around :class:`StockReportHtmlGenerator`."""
    return StockReportHtmlGenerator(document_title=document_title).to_html(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert stock research text (Markdown-like) to a standalone HTML file."
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        help="Input text file (default: read stdin)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output HTML file (default: write stdout)",
    )
    parser.add_argument("-t", "--title", help="HTML document title (overrides inferred title)")
    args = parser.parse_args(argv)

    if args.input is None:
        raw = sys.stdin.read()
    else:
        raw = args.input.read_text(encoding="utf-8")

    html_out = StockReportHtmlGenerator(document_title=args.title).to_html(raw)

    if args.output is None:
        sys.stdout.write(html_out)
    else:
        args.output.write_text(html_out, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
