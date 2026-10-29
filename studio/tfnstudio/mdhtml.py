"""Markdown -> HTML for the studio manual (stdlib only).

`MANUAL.md` is the source of truth. `MANUAL.html` (project root) is generated from it by `scripts/build_manual.py` and is a
single self-contained file - inline CSS, a little progressive-enhancement JavaScript, no network, no external assets - so it can
be read in any browser straight from the file system, without the studio (or Python) running. The studio serves the same
file at /manual.

The converter implements the part of CommonMark / GFM that the manual (and similar README-style documents) uses: ATX headings,
paragraphs, thematic breaks, fenced code, GFM tables, bullet and ordered lists (nested, several blocks per item, tight and loose),
blockquotes, inline code, **strong**, *emphasis*, links, hard line breaks and backslash escapes.

Deliberate simplifications (each is a guard against surprises, not an omission):
  * no raw HTML pass-through - every character of the source is escaped;
  * link targets must be http(s), mailto, relative or #anchor (anything else, e.g. javascript:, is shown as plain text);
  * `_` is never emphasis, so identifiers such as nwn_gff stay intact;
  * no setext headings, reference links, autolinks, tabs for indentation, or nested emphasis edge cases.
`tests/test_mdhtml.py` pins this behaviour, checks the real manual (anchors, leaked markup, a trailing-whitespace-free source)
and fails when MANUAL.html is out of date.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import escape as _escape
from typing import Optional


@dataclass
class Heading:
    level: int
    id: str
    text: str            # plain text, no markup


@dataclass
class Document:
    body: str
    headings: list[Heading] = field(default_factory=list)

    @property
    def title(self) -> str:
        for h in self.headings:
            if h.level == 1:
                return h.text
        return "Manual"


# ---------------------------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------------------------

def esc(text: str) -> str:
    return _escape(text, quote=True)


def slugify(text: str) -> str:
    """GitHub-compatible heading id: lower case, drop punctuation (keeping - and _), spaces become hyphens."""
    return re.sub(r"[^\w\- ]", "", text.lower()).replace(" ", "-")


_CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)
_ESCAPABLE = re.compile(r"\\([!-/:-@\[-`{-~])")
_LINK = re.compile(r"\[([^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*)\]\(\s*([^()\s]*(?:\([^()\s]*\)[^()\s]*)*)(?:\s+&quot;([^&]*)&quot;)?\s*\)")
_STRONG = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.S)
_EM = re.compile(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])", re.S)
_HARD_BREAK = re.compile(r"(?: {2,}|\\)\n")
_SAFE_URL = re.compile(r"^(?!//)(?:#|/|\.{1,2}/|[^:/?#]*(?:[/?#]|$)|https?://|mailto:)", re.I)


def _plain(raw: str) -> str:
    """Heading source -> text without markup (what the id and the table of contents use)."""
    text = _ESCAPABLE.sub(lambda m: m.group(1), raw)
    text = _CODE_SPAN.sub(lambda m: m.group(2).strip(), text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<![\w*])\*([^*\s][^*]*?)\*(?![\w*])", r"\1", text)
    return " ".join(text.split())


def inline(text: str) -> str:
    """Render the inline markup of one paragraph / cell / heading to HTML."""
    code: list[str] = []

    def stash_code(m: re.Match) -> str:
        body = m.group(2)
        if len(body) > 2 and body[0] == " " and body[-1] == " " and body.strip():
            body = body[1:-1]
        code.append(f"<code>{esc(body)}</code>")
        return f"\x00{len(code) - 1}\x00"

    text = _CODE_SPAN.sub(stash_code, text)
    text = _ESCAPABLE.sub(lambda m: f"\x02{ord(m.group(1))}\x03", text)      # \* \| \_ ... become literal characters
    text = esc(text)

    def link(m: re.Match) -> str:
        label, url, title = m.group(1), m.group(2), m.group(3)
        if not _SAFE_URL.match(url):
            return label                                                      # javascript:, data:, ... -> plain text
        attrs = f' href="{url}"'
        if title:
            attrs += f' title="{title}"'
        if re.match(r"https?://", url, re.I):
            attrs += ' class="external" rel="noopener noreferrer"'
        return f"<a{attrs}>{label}</a>"

    text = _LINK.sub(link, text)
    text = _STRONG.sub(r"<strong>\1</strong>", text)
    text = _EM.sub(r"<em>\1</em>", text)
    text = _HARD_BREAK.sub("<br>\n", text)
    text = re.sub(r"\x02(\d+)\x03", lambda m: f"&#{m.group(1)};", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: code[int(m.group(1))], text)


# ---------------------------------------------------------------------------------------------------------------------
# block structure
# ---------------------------------------------------------------------------------------------------------------------

_FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})[ \t]*([^\s`]*)[^`]*$")
_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
_HR = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_QUOTE = re.compile(r"^ {0,3}>")
_BULLET = re.compile(r"^( {0,3})([*+-])( +)(\S.*)$")
_ORDERED = re.compile(r"^( {0,3})(\d{1,9})([.)])( +)(\S.*)$")
_TABLE_DELIM = re.compile(r"^ {0,3}\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")


@dataclass
class _Marker:
    indent: int
    key: tuple           # list identity: ("b", "*") or ("o", ".")
    number: int
    offset: int          # column where the item's content starts
    text: str


def _marker(line: str) -> Optional[_Marker]:
    m = _BULLET.match(line)
    if m:
        spaces = len(m.group(3)) if len(m.group(3)) <= 4 else 1
        return _Marker(len(m.group(1)), ("b", m.group(2)), 0, len(m.group(1)) + 1 + spaces, m.group(4))
    m = _ORDERED.match(line)
    if m:
        spaces = len(m.group(4)) if len(m.group(4)) <= 4 else 1
        width = len(m.group(2)) + 1
        return _Marker(len(m.group(1)), ("o", m.group(3)), int(m.group(2)), len(m.group(1)) + width + spaces, m.group(5))
    return None


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


@dataclass
class _Block:
    kind: str
    html: str
    blank_before: bool = False
    inner: str = ""      # rendered inline HTML of a paragraph (for tight lists)


class _Converter:
    def __init__(self) -> None:
        self.headings: list[Heading] = []
        self._ids: dict[str, int] = {}

    # ----------------------------------------------------------------- entry
    def run(self, text: str) -> str:
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        return "\n".join(b.html for b in self.blocks(lines))

    def blocks(self, lines: list[str]) -> list[_Block]:
        out: list[_Block] = []
        i, n = 0, len(lines)
        blank = False

        def emit(kind: str, html: str, inner: str = "") -> None:
            nonlocal blank
            out.append(_Block(kind, html, blank_before=blank and bool(out), inner=inner))
            blank = False

        while i < n:
            line = lines[i]
            if not line.strip():
                blank = True
                i += 1
                continue
            m = _FENCE.match(line)
            if m:
                html, i = self._fenced(lines, i, m)
                emit("code", html)
                continue
            m = _HEADING.match(line)
            if m:
                emit("heading", self._heading(len(m.group(1)), m.group(2)))
                i += 1
                continue
            if _HR.match(line):
                emit("hr", "<hr>")
                i += 1
                continue
            if _QUOTE.match(line):
                html, i = self._quote(lines, i)
                emit("quote", html)
                continue
            if _marker(line):
                html, i = self._list(lines, i)
                emit("list", html)
                continue
            if self._table_at(lines, i):
                html, i = self._table(lines, i)
                emit("table", html)
                continue
            inner, i = self._paragraph(lines, i)
            emit("p", f"<p>{inner}</p>", inner)
        return out

    # --------------------------------------------------------------- leaves
    def _heading(self, level: int, raw: str) -> str:
        plain = _plain(raw)
        base = slugify(plain) or "section"
        seen = self._ids.get(base, 0)
        self._ids[base] = seen + 1
        hid = base if seen == 0 else f"{base}-{seen}"
        self.headings.append(Heading(level, hid, plain))
        anchor = f'<a class="anchor" href="#{hid}" aria-label="Link to this section">#</a>' if level >= 2 else ""
        return f'<h{level} id="{hid}">{inline(raw)}{anchor}</h{level}>'

    def _fenced(self, lines: list[str], i: int, m: re.Match) -> tuple[str, int]:
        indent, fence, lang = len(m.group(1)), m.group(2), m.group(3)
        close = re.compile(rf"^ {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$")
        body: list[str] = []
        j = i + 1
        while j < len(lines) and not close.match(lines[j]):
            ln = lines[j]
            k = 0
            while k < indent and k < len(ln) and ln[k] == " ":
                k += 1
            body.append(ln[k:])
            j += 1
        j = j + 1 if j < len(lines) else j
        lang = re.sub(r"[^A-Za-z0-9_+-]", "", lang)
        cls = f' class="language-{lang}"' if lang else ""
        data = f' data-lang="{lang}"' if lang else ""
        return f'<div class="code"{data}><pre><code{cls}>{esc(chr(10).join(body))}\n</code></pre></div>', j

    def _paragraph(self, lines: list[str], i: int) -> tuple[str, int]:
        parts: list[str] = []
        n = len(lines)
        while i < n and lines[i].strip():
            if parts and self._interrupts(lines[i]):
                break
            parts.append(lines[i])
            i += 1
        cooked = []
        for k, ln in enumerate(parts):
            ln = ln.lstrip(" ")
            cooked.append(ln if (ln.endswith("  ") or ln.endswith("\\")) and k < len(parts) - 1 else ln.rstrip())
        return inline("\n".join(cooked)), i

    @staticmethod
    def _interrupts(line: str) -> bool:
        if _FENCE.match(line) or _HEADING.match(line) or _HR.match(line) or _QUOTE.match(line):
            return True
        mk = _marker(line)
        return bool(mk and (mk.key[0] == "b" or mk.number == 1))

    def _quote(self, lines: list[str], i: int) -> tuple[str, int]:
        inner: list[str] = []
        while i < len(lines) and lines[i].strip():
            ln = lines[i]
            if _QUOTE.match(ln):
                ln = re.sub(r"^ {0,3}> ?", "", ln)
            elif self._interrupts(ln):
                break
            inner.append(ln)
            i += 1
        return "<blockquote>\n" + "\n".join(b.html for b in self.blocks(inner)) + "\n</blockquote>", i

    # --------------------------------------------------------------- tables
    def _table_at(self, lines: list[str], i: int) -> bool:
        if i + 1 >= len(lines) or "|" not in lines[i] or "|" not in lines[i + 1]:
            return False
        if not _TABLE_DELIM.match(lines[i + 1]):
            return False
        return len(_split_row(lines[i])) == len(_split_row(lines[i + 1]))

    def _table(self, lines: list[str], i: int) -> tuple[str, int]:
        head = _split_row(lines[i])
        align = []
        for cell in _split_row(lines[i + 1]):
            left, right = cell.startswith(":"), cell.endswith(":")
            align.append("center" if left and right else "right" if right else "left" if left else "")
        i += 2
        rows: list[list[str]] = []
        while i < len(lines) and lines[i].strip() and not (_FENCE.match(lines[i]) or _HEADING.match(lines[i]) or _QUOTE.match(lines[i])):
            cells = _split_row(lines[i])
            rows.append((cells + [""] * len(head))[:len(head)])
            i += 1

        def cell(tag: str, text: str, k: int) -> str:
            cls = f' class="align-{align[k]}"' if align[k] else ""
            return f"<{tag}{cls}>{inline(text)}</{tag}>"

        out = ['<div class="table-wrap"><table>', "<thead><tr>" + "".join(cell("th", t, k) for k, t in enumerate(head)) + "</tr></thead>"]
        if rows:
            out.append("<tbody>")
            out += ["<tr>" + "".join(cell("td", t, k) for k, t in enumerate(row)) + "</tr>" for row in rows]
            out.append("</tbody>")
        out.append("</table></div>")
        return "\n".join(out), i

    # ---------------------------------------------------------------- lists
    def _list(self, lines: list[str], i: int) -> tuple[str, int]:
        first = _marker(lines[i])
        assert first is not None
        key, n = first.key, len(lines)
        items: list[list[str]] = []
        loose = False
        j = i
        while j < n:
            mk = _marker(lines[j])
            if mk is None or mk.key != key:
                break
            offset = mk.offset
            item = [mk.text]
            fence: Optional[str] = None
            j += 1
            fence = self._track_fence(mk.text, fence)
            while j < n:
                ln = lines[j]
                if not ln.strip():
                    k = j
                    while k < n and not lines[k].strip():
                        k += 1
                    if k < n and _indent(lines[k]) >= offset:
                        item.extend([""] * (k - j))
                        j = k
                        continue
                    break
                if _indent(ln) >= offset:
                    item.append(ln[offset:])
                    fence = self._track_fence(ln[offset:], fence)
                    j += 1
                    continue
                if fence is None and item[-1].strip() and not self._starts_block(ln):
                    item.append(ln.strip())          # lazy continuation of the item's paragraph
                    j += 1
                    continue
                break
            items.append(item)
            k = j
            while k < n and not lines[k].strip():
                k += 1
            if k > j:
                nxt = _marker(lines[k]) if k < n else None
                if nxt is not None and nxt.key == key:
                    loose = True
                    j = k
                    continue
                break
        rendered = [self.blocks(item) for item in items]
        loose = loose or any(b.blank_before for blocks in rendered for b in blocks[1:])
        lis = []
        for blocks in rendered:
            parts = [b.html if (loose or b.kind != "p") else b.inner for b in blocks]
            lis.append("<li>" + "\n".join(parts) + ("\n" if blocks and blocks[-1].kind == "list" and not loose else "") + "</li>")
        if key[0] == "o":
            start = "" if first.number == 1 else f' start="{first.number}"'
            return f"<ol{start}>\n" + "\n".join(lis) + "\n</ol>", j
        return "<ul>\n" + "\n".join(lis) + "\n</ul>", j

    @staticmethod
    def _track_fence(line: str, state: Optional[str]) -> Optional[str]:
        m = _FENCE.match(line)
        if state is None:
            return m.group(2)[0] * len(m.group(2)) if m else None
        return None if re.match(rf"^ {{0,3}}{re.escape(state[0])}{{{len(state)},}}[ \t]*$", line) else state

    @staticmethod
    def _starts_block(line: str) -> bool:
        return bool(_FENCE.match(line) or _HEADING.match(line) or _HR.match(line) or _QUOTE.match(line) or _marker(line))


def convert(markdown: str) -> Document:
    conv = _Converter()
    body = conv.run(markdown)
    return Document(body=body, headings=conv.headings)


# ---------------------------------------------------------------------------------------------------------------------
# page
# ---------------------------------------------------------------------------------------------------------------------

def render_toc(headings: list[Heading]) -> str:
    """Sidebar table of contents: the h2 sections with their h3 subsections (the title and "Contents" are skipped)."""
    out: list[str] = []
    open_item = False
    sub_open = False
    for h in headings:
        if h.level not in (2, 3) or h.id == "contents":
            continue
        link = f'<a href="#{h.id}">{esc(h.text)}</a>'
        if h.level == 2:
            if sub_open:
                out.append("</ul>")
                sub_open = False
            if open_item:
                out.append("</li>")
            out.append(f"<li>{link}")
            open_item = True
        else:
            if not open_item:
                out.append("<li>")
                open_item = True
            if not sub_open:
                out.append('<ul class="sub">')
                sub_open = True
            out.append(f"<li>{link}</li>")
    if sub_open:
        out.append("</ul>")
    if open_item:
        out.append("</li>")
    return "<ul>\n" + "\n".join(out) + "\n</ul>"


def write_page(path, page: str) -> None:
    """Write `page` as UTF-8 with plain \\n line endings on every OS (Path.write_text(newline=) needs Python 3.10)."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(page)


def render_page(markdown: str) -> str:
    """The complete, self-contained HTML document for a manual written in Markdown."""
    doc = convert(markdown)
    page = _PAGE
    for token, value in (("@@TITLE@@", esc(doc.title)), ("@@STYLE@@", _CSS), ("@@SCRIPT@@", _JS),
                         ("@@TOC@@", render_toc(doc.headings)), ("@@BODY@@", doc.body)):
        page = page.replace(token, value)
    return page


_ICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' "
         "fill='%232f6fdb'/%3E%3Cpath d='M9 9h14v3.4h-5.3V24h-3.4V12.4H9z' fill='white'/%3E%3C/svg%3E")

_PAGE = """<!doctype html>
<!-- Generated by scripts/build_manual.py from MANUAL.md (tfnstudio/mdhtml.py). Do not edit by hand: edit MANUAL.md and regenerate. -->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>@@TITLE@@</title>
<link rel="icon" href="@@ICON@@">
<style>
@@STYLE@@
</style>
</head>
<body>
<a class="skip" href="#content">Skip to the manual</a>
<header class="top">
  <span class="brand">TFN Content Studio</span><span class="sub">Manual</span>
  <nav class="top-links" aria-label="Page links">
    <a href="#contents">Contents</a>
    <a id="open-studio" href="/" hidden>Open the studio &rarr;</a>
  </nav>
</header>
<div class="layout">
<nav class="toc" aria-label="Table of contents">
<h2>On this page</h2>
@@TOC@@
</nav>
<main id="content">
@@BODY@@
</main>
</div>
<script>
@@SCRIPT@@
</script>
</body>
</html>
""".replace("@@ICON@@", _ICON)

_CSS = """\
:root {
  --bg: #f4f5f7; --panel: #ffffff; --panel2: #eef0f4; --text: #1c2330; --muted: #5d6778; --line: #d5d9e2;
  --accent: #2f6fdb; --accent-text: #ffffff; --good: #1d8a4b; --warn: #b9770e; --bad: #c8372d;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; --shadow: 0 1px 3px rgba(20, 28, 45, .12);
  color-scheme: light dark;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #12151c; --panel: #1b202b; --panel2: #232a38; --text: #e5e9f2; --muted: #98a2b6; --line: #313a4d;
    --accent: #5b94f5; --accent-text: #0b1220; --good: #46c07a; --warn: #e0a43a; --bad: #f0675c; --shadow: 0 1px 3px rgba(0, 0, 0, .5);
  }
}
* { box-sizing: border-box; }
html { scroll-padding-top: 4.5rem; }
body { margin: 0; background: var(--bg); color: var(--text); font: 16px/1.65 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
a { color: var(--accent); text-underline-offset: 2px; }
a:focus-visible, button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 3px; }
.skip { position: absolute; left: -999px; top: 0; background: var(--accent); color: var(--accent-text); padding: .5rem 1rem; z-index: 20; }
.skip:focus { left: 0; }

header.top { position: sticky; top: 0; z-index: 10; display: flex; align-items: center; gap: .6rem; height: 3.2rem; padding: 0 1rem;
  background: var(--panel); border-bottom: 1px solid var(--line); }
header.top .brand { font-weight: 700; letter-spacing: .02em; }
header.top .sub { color: var(--muted); padding-left: .6rem; border-left: 1px solid var(--line); }
header.top .top-links { margin-left: auto; display: flex; gap: 1.2rem; font-size: .92rem; }
header.top .top-links a { text-decoration: none; }
header.top .top-links a:hover { text-decoration: underline; }
[hidden] { display: none !important; }

.layout { display: grid; grid-template-columns: 17rem minmax(0, 1fr); gap: 1.6rem; max-width: 78rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
.toc { position: sticky; top: 4.6rem; align-self: start; max-height: calc(100vh - 6rem); overflow: auto; overscroll-behavior: contain; font-size: .88rem; line-height: 1.4; padding-right: .5rem; }
.toc h2 { font-size: .75rem; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin: 0 0 .6rem; border: 0; padding: 0; }
.toc ul { list-style: none; margin: 0; padding: 0; }
.toc li { margin: .2rem 0; }
.toc ul.sub { margin: .15rem 0 .45rem .8rem; padding-left: .7rem; border-left: 1px solid var(--line); }
.toc a { display: block; padding: .15rem .4rem; border-radius: 5px; color: var(--muted); text-decoration: none; }
.toc a:hover { color: var(--text); background: var(--panel2); }
.toc a[aria-current="true"] { color: var(--accent); background: var(--panel2); font-weight: 600; }

main { min-width: 0; background: var(--panel); border: 1px solid var(--line); border-radius: 10px; box-shadow: var(--shadow); padding: 1.6rem 2.2rem 2.2rem; }
h1, h2, h3 { line-height: 1.25; }
h1 { font-size: 1.95rem; margin: 0 0 1rem; }
h2 { font-size: 1.45rem; margin: 2.6rem 0 1rem; padding-bottom: .35rem; border-bottom: 1px solid var(--line); }
h3 { font-size: 1.14rem; margin: 1.9rem 0 .6rem; }
.anchor { margin-left: .5rem; font-weight: 400; text-decoration: none; color: var(--muted); opacity: 0; }
h2:hover .anchor, h3:hover .anchor, .anchor:focus { opacity: 1; }
p, ul, ol, .table-wrap, .code, blockquote { margin: 0 0 1rem; }
ul, ol { padding-left: 1.6rem; }
li { margin: .25rem 0; }
li > ul, li > ol { margin: .3rem 0 .3rem; }
hr { border: 0; border-top: 1px solid var(--line); margin: 2rem 0; }
blockquote { border-left: 4px solid var(--line); padding: .1rem 1rem; color: var(--muted); background: var(--panel2); border-radius: 0 6px 6px 0; }
strong { font-weight: 650; }

code { font-family: var(--mono); font-size: .875em; background: var(--panel2); border: 1px solid var(--line); padding: .05em .35em; border-radius: 4px; word-break: break-word; }
.code { position: relative; }
.code pre { margin: 0; padding: .9rem 1rem; background: var(--panel2); border: 1px solid var(--line); border-radius: 8px; overflow: auto; line-height: 1.5; tab-size: 4; }
.code pre code { background: none; border: 0; padding: 0; font-size: .84rem; word-break: normal; white-space: pre; }
.code[data-lang]::before { content: attr(data-lang); position: absolute; top: .3rem; right: .6rem; font: .7rem var(--mono); color: var(--muted); text-transform: uppercase; letter-spacing: .05em; pointer-events: none; }
.code .copy { position: absolute; top: .35rem; right: .5rem; font: .75rem system-ui, sans-serif; padding: .15rem .55rem; border: 1px solid var(--line); border-radius: 5px;
  background: var(--panel); color: var(--text); cursor: pointer; opacity: 0; transition: opacity .12s; }
.code:hover .copy, .code .copy:focus { opacity: 1; }
.code:hover[data-lang]::before { opacity: 0; }

.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .92rem; }
th, td { text-align: left; vertical-align: top; padding: .45rem .7rem; border: 1px solid var(--line); }
th { background: var(--panel2); font-weight: 650; white-space: nowrap; }
tbody tr:nth-child(even) td { background: color-mix(in srgb, var(--panel2) 55%, transparent); }
.align-right { text-align: right; } .align-center { text-align: center; }
td code { white-space: normal; }

@media (max-width: 1000px) {
  .layout { grid-template-columns: minmax(0, 1fr); padding: .8rem .6rem 3rem; }
  .toc { display: none; }
  main { padding: 1rem 1rem 1.6rem; border-radius: 8px; }
  h1 { font-size: 1.55rem; } h2 { font-size: 1.25rem; }
}
@media print {
  header.top, .toc, .copy, .anchor, .skip { display: none !important; }
  body { background: #fff; color: #000; font-size: 11pt; }
  .layout { display: block; padding: 0; max-width: none; }
  main { border: 0; box-shadow: none; padding: 0; background: #fff; }
  .code pre, .code pre code { white-space: pre-wrap; overflow-wrap: anywhere; }
  .code pre { break-inside: avoid; }
  h2, h3 { break-after: avoid; }
  tr, .code { break-inside: avoid; }
  a { color: inherit; text-decoration: none; }
  a[href^="http"]::after { content: " (" attr(href) ")"; font-size: .85em; }
}
"""

_JS = """\
(function () {
  'use strict';
  // The page works without any of this; it only adds conveniences.
  // In-page links glide; opening the page at a #section (or back/forward) jumps instantly, as browsers do by default.
  document.addEventListener('click', function (e) {
    var a = e.target.closest ? e.target.closest('a[href^="#"]') : null;
    if (!a || e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var id = decodeURIComponent(a.getAttribute('href').slice(1));
    var target = id ? document.getElementById(id) : null;
    if (!target || !window.matchMedia || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    e.preventDefault();
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (history.pushState) history.pushState(null, '', '#' + id);
  });
  var back = document.getElementById('open-studio');
  if (back && /^https?:$/.test(location.protocol)) back.hidden = false;      // a studio to go back to only exists over http

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    return new Promise(function (resolve, reject) {
      var ta = document.createElement('textarea');
      ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy') ? resolve() : reject(); } catch (e) { reject(e); }
      document.body.removeChild(ta);
    });
  }
  Array.prototype.forEach.call(document.querySelectorAll('.code'), function (box) {
    var btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'copy'; btn.textContent = 'Copy'; btn.setAttribute('aria-label', 'Copy this code');
    btn.addEventListener('click', function () {
      var code = box.querySelector('code');
      copyText(code ? code.textContent : '').then(function () { btn.textContent = 'Copied'; }, function () { btn.textContent = 'Select + copy'; });
      setTimeout(function () { btn.textContent = 'Copy'; }, 1600);
    });
    box.appendChild(btn);
  });

  var toc = document.querySelector('.toc');
  function reveal(a) {                                   // keep the highlighted entry visible inside the scrolling sidebar
    if (!toc) return;
    var t = a.getBoundingClientRect(), c = toc.getBoundingClientRect();
    if (t.top < c.top + 24) toc.scrollTop -= c.top + 24 - t.top;
    else if (t.bottom > c.bottom - 24) toc.scrollTop += t.bottom - (c.bottom - 24);
  }
  var links = {};
  Array.prototype.forEach.call(document.querySelectorAll('.toc a[href^="#"]'), function (a) { links[a.getAttribute('href').slice(1)] = a; });
  var heads = Array.prototype.filter.call(document.querySelectorAll('main h2[id], main h3[id]'), function (h) { return links[h.id]; });
  if ('IntersectionObserver' in window && heads.length) {
    var current = null;
    var seen = {};
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { seen[e.target.id] = e.isIntersecting; });
      var first = heads.filter(function (h) { return seen[h.id]; })[0];
      if (!first) return;
      if (current) current.removeAttribute('aria-current');
      current = links[first.id];
      current.setAttribute('aria-current', 'true');
      reveal(current);
    }, { rootMargin: '-8% 0px -72% 0px' });
    heads.forEach(function (h) { observer.observe(h); });
  }
})();
"""
