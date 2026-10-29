"""Markdown -> HTML converter (tfnstudio/mdhtml.py) and the generated, self-contained MANUAL.html."""

from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

from tests.fixture import ROOT  # noqa: F401  (sets sys.path)

from tfnstudio import mdhtml
from tfnstudio.mdhtml import convert, inline, render_page, slugify

MANUAL_MD = ROOT / "MANUAL.md"
MANUAL_HTML = ROOT / "MANUAL.html"


def body(md: str) -> str:
    return convert(md).body


class InlineTests(unittest.TestCase):
    def test_code_spans_are_escaped_and_protect_their_content(self):
        self.assertEqual(inline("use `a < b && c` now"), "use <code>a &lt; b &amp;&amp; c</code> now")
        self.assertEqual(inline("`**not bold**` and `*x*`"), "<code>**not bold**</code> and <code>*x*</code>")
        self.assertEqual(inline("`` a ` b ``"), "<code>a ` b</code>")                       # double-backtick span, padding stripped
        self.assertEqual(inline("`src/**/*.json`"), "<code>src/**/*.json</code>")

    def test_strong_and_emphasis(self):
        self.assertEqual(inline("a **b** c"), "a <strong>b</strong> c")
        self.assertEqual(inline("a *b* c"), "a <em>b</em> c")
        self.assertEqual(inline("**bold `code` bold**"), "<strong>bold <code>code</code> bold</strong>")
        self.assertEqual(inline("*a **b** c*"), "<em>a <strong>b</strong> c</em>")
        self.assertEqual(inline("**spans\nlines**"), "<strong>spans\nlines</strong>")
        self.assertEqual(inline("5 * 3 * 2"), "5 * 3 * 2")                                  # spaces: not emphasis

    def test_underscores_are_never_emphasis(self):
        self.assertEqual(inline("nwn_gff and _x_ and __y__"), "nwn_gff and _x_ and __y__")

    def test_links(self):
        self.assertEqual(inline("[a](#b)"), '<a href="#b">a</a>')
        self.assertEqual(inline("[PLAN](PLAN.md)"), '<a href="PLAN.md">PLAN</a>')
        self.assertEqual(inline("[x](docs/a.md#top)"), '<a href="docs/a.md#top">x</a>')
        self.assertEqual(inline("[x](https://example.com/a?b=1&c=2)"),
                         '<a href="https://example.com/a?b=1&amp;c=2" class="external" rel="noopener noreferrer">x</a>')
        self.assertEqual(inline('[x](#y "the title")'), '<a href="#y" title="the title">x</a>')
        self.assertEqual(inline("[`doctor` **now**](#d)"), '<a href="#d"><code>doctor</code> <strong>now</strong></a>')
        self.assertEqual(inline("[x](https://e.com/a_(b))"), '<a href="https://e.com/a_(b)" class="external" rel="noopener noreferrer">x</a>')

    def test_unsafe_link_targets_become_plain_text(self):
        for url in ("javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,x", "vbscript:x", "//evil.example/x", "file:///etc/passwd"):
            out = inline(f"[click]({url})")
            self.assertEqual(out, "click", url)
            self.assertNotIn("href", out)

    def test_html_is_never_passed_through(self):
        out = inline('<script>alert("x")</script> <b>x</b> & "q"')
        self.assertNotIn("<script", out)
        self.assertNotIn("<b>", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertIn("&amp;", out)
        self.assertEqual(inline("a <b> c"), "a &lt;b&gt; c")

    def test_backslash_escapes(self):
        self.assertEqual(inline(r"\*not em\*"), "&#42;not em&#42;")
        self.assertEqual(inline(r"a \| b"), "a &#124; b")
        self.assertEqual(inline(r"\[x\](y)"), "&#91;x&#93;(y)")
        self.assertEqual(inline("trailing \\"), "trailing \\")                                  # a lone backslash stays

    def test_hard_line_break(self):
        self.assertEqual(inline("one  \ntwo"), "one<br>\ntwo")
        self.assertEqual(inline("one\ntwo"), "one\ntwo")


class HeadingTests(unittest.TestCase):
    def test_slugs_match_github(self):
        self.assertEqual(slugify("1. Quick start"), "1-quick-start")
        self.assertEqual(slugify("3.5 Tools (nwn_gff, nwnsc, nwn_resman_extract)"), "35-tools-nwn_gff-nwnsc-nwn_resman_extract")
        self.assertEqual(slugify("10. Changes: review, apply, undo"), "10-changes-review-apply-undo")
        self.assertEqual(slugify("TFN Content Studio — Manual"), "tfn-content-studio--manual")
        self.assertEqual(slugify("Ärger & Übung"), "ärger--übung")

    def test_headings_get_ids_anchors_and_plain_text_entries(self):
        doc = convert("# Title\n\n## 3.5 Tools (`nwn_gff`, **x**)\n\n### Sub *part*\n")
        self.assertEqual([(h.level, h.id, h.text) for h in doc.headings],
                         [(1, "title", "Title"), (2, "35-tools-nwn_gff-x", "3.5 Tools (nwn_gff, x)"), (3, "sub-part", "Sub part")])
        self.assertIn('<h1 id="title">Title</h1>', doc.body)                                  # no anchor on the title
        self.assertIn('<h2 id="35-tools-nwn_gff-x">3.5 Tools (<code>nwn_gff</code>, <strong>x</strong>)'
                      '<a class="anchor" href="#35-tools-nwn_gff-x" aria-label="Link to this section">#</a></h2>', doc.body)
        self.assertEqual(doc.title, "Title")

    def test_duplicate_headings_get_unique_ids(self):
        doc = convert("## Notes\n\n## Notes\n\n## Notes\n")
        self.assertEqual([h.id for h in doc.headings], ["notes", "notes-1", "notes-2"])

    def test_closing_hashes_and_levels(self):
        doc = convert("#### Four ####\n\n###### Six\n\n####### not a heading\n")
        self.assertEqual([(h.level, h.text) for h in doc.headings], [(4, "Four"), (6, "Six")])
        self.assertIn("<p>####### not a heading</p>", doc.body)


class BlockTests(unittest.TestCase):
    def test_paragraphs_and_interruptions(self):
        self.assertEqual(body("one\ntwo\n\nthree"), "<p>one\ntwo</p>\n<p>three</p>")
        out = body("text\n# H\ntext2\n- item\nmore")
        self.assertIn("<p>text</p>", out)
        self.assertIn('<h1 id="h">H</h1>', out)
        self.assertIn("<p>text2</p>", out)
        self.assertIn("<ul>", out)

    def test_thematic_break_and_no_setext_headings(self):
        self.assertEqual(body("a\n\n---\n\nb"), "<p>a</p>\n<hr>\n<p>b</p>")
        self.assertEqual(body("***"), "<hr>")
        self.assertEqual(body("Foo\n---"), "<p>Foo</p>\n<hr>")                                    # documented simplification

    def test_fenced_code(self):
        out = body("```bash\necho \"<hi>\" && ls   # **x**\n```")
        self.assertIn('<div class="code" data-lang="bash"><pre><code class="language-bash">', out)
        self.assertIn("echo &quot;&lt;hi&gt;&quot; &amp;&amp; ls   # **x**", out)                 # escaped, no inline markup inside
        self.assertNotIn("<strong>", out)
        self.assertEqual(body("```\nplain\n```").count("language-"), 0)
        self.assertIn("~~~ not closed by ```", body("~~~\n~~~ not closed by ```\n```\n~~~"))
        self.assertIn("a\n```\nb", body("````\na\n```\nb\n````"))                                # longer fence holds a shorter one
        self.assertIn("never closed", body("```\nnever closed"))                                  # runs to the end of the document

    def test_a_fence_indented_by_up_to_three_spaces_strips_that_indent_from_its_lines(self):
        out = body("  ```\n  code\n    more\n  ```\nafter")
        self.assertIn("<code>code\n  more\n</code>", out)
        self.assertIn("<p>after</p>", out)

    def test_tables(self):
        out = body("| A | B |\n|---|:-:|\n| `x \\| y` | **bold** |\n| only one |\n")
        self.assertIn('<div class="table-wrap"><table>', out)
        self.assertIn("<thead><tr><th>A</th><th class=\"align-center\">B</th></tr></thead>", out)
        self.assertIn("<code>x | y</code>", out)                                                 # \| inside a cell is a literal pipe
        self.assertIn('<td class="align-center"><strong>bold</strong></td>', out)
        self.assertIn('<td>only one</td><td class="align-center"></td>', out)                     # ragged rows are padded
        self.assertEqual(out.count("<tr>"), 3)

    def test_a_paragraph_with_pipes_is_not_a_table(self):
        self.assertEqual(body("a | b\nc | d"), "<p>a | b\nc | d</p>")
        self.assertEqual(body("| a | b |\n|---|\n| 1 | 2 |").count("<table>"), 0)               # delimiter row must match the header

    def test_blockquote(self):
        out = body("> quoted *text*\n> more\n\nafter")
        self.assertIn("<blockquote>\n<p>quoted <em>text</em>\nmore</p>\n</blockquote>", out)
        self.assertIn("<p>after</p>", out)


class ListTests(unittest.TestCase):
    def test_tight_list_has_no_paragraphs(self):
        self.assertEqual(body("* a\n* b\n* c"), "<ul>\n<li>a</li>\n<li>b</li>\n<li>c</li>\n</ul>")

    def test_blank_line_between_items_makes_it_loose(self):
        out = body("* a\n\n* b")
        self.assertEqual(out, "<ul>\n<li><p>a</p></li>\n<li><p>b</p></li>\n</ul>")

    def test_ordered_lists_keep_their_start_number(self):
        self.assertTrue(body("1. a\n2. b").startswith("<ol>"))
        self.assertTrue(body("3. a\n4. b").startswith('<ol start="3">'))

    def test_different_markers_start_a_new_list(self):
        out = body("* a\n- b\n1. c\n1) d")
        self.assertEqual(out.count("<ul>"), 2)
        self.assertEqual(out.count("<ol"), 2)

    def test_nested_lists_and_continuation_lines(self):
        out = body("1. **Place things:**\n   * one\n     wraps here\n   * two\n2. next")
        self.assertIn("<ol>\n<li><strong>Place things:</strong>\n<ul>\n<li>one\nwraps here</li>\n<li>two</li>\n</ul>\n</li>", out)
        self.assertIn("<li>next</li>", out)

    def test_fenced_code_and_paragraphs_inside_items(self):
        md = "* **Pack** — run:\n  ```bash\n  cd x\n  make\n  ```\n  Then wait.\n\n  Done.\n* **Other**"
        out = body(md)
        self.assertIn('<pre><code class="language-bash">cd x\nmake\n</code></pre>', out)       # fence de-indented
        self.assertIn("<p>Then wait.</p>", out)
        self.assertIn("<p>Done.</p>", out)                                                       # blank line inside the item: loose list
        self.assertEqual(out.count("<li>"), 2)

    def test_nested_ordered_list_followed_by_a_paragraph_of_the_outer_item(self):
        md = "* **Validation** — runs:\n  1. first\n  2. second\n\n  Messages are shown.\n* **Apply**"
        out = body(md)
        self.assertIn("<ol>", out)
        self.assertIn("<p>Messages are shown.</p>", out)
        self.assertEqual(out.count("<ul>"), 1)
        self.assertEqual(out.count("<ol>"), 1)

    def test_lazy_continuation_joins_the_paragraph(self):
        out = body("* item text\ncontinues lazily\n* next")
        self.assertIn("<li>item text\ncontinues lazily</li>", out)

    def test_a_marker_needs_a_space_and_text(self):
        self.assertEqual(body("**bold** start"), "<p><strong>bold</strong> start</p>")
        self.assertEqual(body("-not a list"), "<p>-not a list</p>")
        self.assertEqual(body("2026-10-02. Version"), "<p>2026-10-02. Version</p>")


class ManualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.md = MANUAL_MD.read_text(encoding="utf-8")
        cls.doc = convert(cls.md)
        cls.html = MANUAL_HTML.read_text(encoding="utf-8")

    # ------------------------------------------------------------- source hygiene
    def test_source_has_no_tabs_or_trailing_whitespace(self):
        for n, line in enumerate(self.md.split("\n"), 1):
            self.assertNotIn("\t", line, f"MANUAL.md:{n} contains a tab")
            self.assertEqual(line, line.rstrip(), f"MANUAL.md:{n} has trailing whitespace")

    def test_every_rule_follows_a_blank_line(self):
        """`text` directly above `---` is a heading in other renderers (GitHub), a rule here: keep both readings identical."""
        lines = self.md.split("\n")
        in_fence = False
        for n, line in enumerate(lines):
            if line.startswith("```"):
                in_fence = not in_fence
            if not in_fence and line == "---" and n > 0:
                self.assertEqual(lines[n - 1], "", f"MANUAL.md:{n + 1}: '---' must follow a blank line")

    # ------------------------------------------------------------------- structure
    def test_title_and_sections(self):
        self.assertEqual(self.doc.title, "TFN Content Studio — Installation, Startup and Usage Manual")
        h2 = [h.text for h in self.doc.headings if h.level == 2]
        self.assertEqual(len(h2), 19)                                                            # Contents + sections 1-18
        self.assertEqual(h2[0], "Contents")
        ids = [h.id for h in self.doc.headings]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_internal_link_resolves(self):
        ids = {h.id for h in self.doc.headings}
        targets = re.findall(r"\]\(#([^)]+)\)", self.md)
        self.assertGreater(len(targets), 20)
        for t in targets:
            self.assertIn(t, ids, f"MANUAL.md links to #{t}, which is not a heading")
        # and in the generated page
        page_ids = set(re.findall(r'\sid="([^"]+)"', self.html))
        for href in re.findall(r'href="#([^"]+)"', self.html):
            self.assertIn(href, page_ids, f"MANUAL.html links to #{href}")

    def test_no_markup_leaks_into_the_page(self):
        text = re.sub(r"<pre>.*?</pre>", "", self.doc.body, flags=re.S)
        text = re.sub(r"<code[^>]*>.*?</code>", "", text, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        for needle in ("**", "`", "\x00", "\x02", "\x03", "](", "&amp;lt;", "&amp;amp;"):
            self.assertNotIn(needle, text, f"leaked {needle!r}")

    def test_tables_and_code_blocks_are_all_converted(self):
        delimiter_rows = len(re.findall(r"^\|[-| :]+\|$", self.md, re.M))
        self.assertEqual(self.doc.body.count("<table>"), delimiter_rows)
        fences = len(re.findall(r"^\s*```", self.md, re.M))
        self.assertEqual(self.doc.body.count('<div class="code"'), fences // 2)

    def test_the_page_documents_the_new_entry_points(self):
        for needle in ("MANUAL.html", "/manual", "tfn-studio manual", "doctor", "Manual ↗"):
            self.assertIn(needle, self.md)

    # ------------------------------------------------------- the generated file
    def test_manual_html_is_up_to_date(self):
        self.assertEqual(self.html, render_page(self.md),
                         "MANUAL.html is out of date: run  python3 scripts/build_manual.py  and commit it")

    def test_build_script_check_mode_agrees(self):
        import contextlib
        import io
        import runpy
        mod = runpy.run_path(str(ROOT / "scripts" / "build_manual.py"))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mod["main"](["--check"]), 0)

    def test_the_page_is_self_contained(self):
        """It must work from file:// on a machine with nothing installed and no network."""
        class Refs(HTMLParser):
            def __init__(self):
                super().__init__()
                self.refs, self.scripts, self.styles, self.stylesheets = [], 0, 0, 0

            def handle_starttag(self, tag, attrs):
                a = dict(attrs)
                for key in ("src", "href", "srcset", "action", "data"):
                    if a.get(key):
                        self.refs.append((tag, key, a[key]))
                if tag == "script":
                    self.scripts += 1
                if tag == "style":
                    self.styles += 1
                if tag == "link" and "stylesheet" in (a.get("rel") or ""):
                    self.stylesheets += 1

        p = Refs()
        p.feed(self.html)
        self.assertEqual((p.scripts, p.styles, p.stylesheets), (1, 1, 0))
        for tag, key, value in p.refs:
            self.assertFalse(re.match(r"^(?:https?:)?//", value), f"external reference <{tag} {key}={value[:60]}>")
            if tag == "link":
                self.assertTrue(value.startswith("data:"), f"<link href={value[:40]}> must be a data URI")
            if tag == "a" and not value.startswith("#"):
                # relative links point at documents next to the manual; they must not climb out of the project folder
                self.assertTrue(re.match(r"^[A-Za-z0-9_.-]+$|^/$|^https?://", value), f"unexpected link {value}")
        for needle in ("@import", "url(http", "//cdn", "<iframe", "<object", "<embed"):
            self.assertNotIn(needle, self.html)
        self.assertTrue(self.html.lstrip().lower().startswith("<!doctype html>"))
        self.assertIn('<meta charset="utf-8">', self.html)
        self.assertIn('name="viewport"', self.html)

    def test_open_the_studio_link_is_hidden_until_the_page_is_served_over_http(self):
        self.assertRegex(self.html, r'<a id="open-studio" href="/" hidden>')
        self.assertIn("/^https?:$/.test(location.protocol)", self.html)

    def test_pages_link_to_the_manual_sections_that_exist(self):
        """common.js sends each page's Manual link to a section; those ids must exist in the manual."""
        js = (ROOT / "tfnstudio" / "web" / "static" / "common.js").read_text(encoding="utf-8")
        block = re.search(r"MANUAL_SECTIONS = \{(.*?)\};", js, re.S)
        self.assertIsNotNone(block)
        pairs = re.findall(r"'(/[a-z]*)':\s*'#([^']+)'", block.group(1))
        self.assertEqual({p for p, _ in pairs}, {"/", "/camps", "/spawns", "/quests", "/changes"})
        ids = {h.id for h in self.doc.headings}
        for page, anchor in pairs:
            self.assertIn(anchor, ids, f"{page} -> #{anchor} is not a heading in MANUAL.md")


class PageTests(unittest.TestCase):
    def test_render_page_for_a_small_document(self):
        page = render_page("# Hello\n\n## One\n\ntext `x`\n\n### Sub\n\n## Contents\n\n- a\n")
        self.assertIn("<title>Hello</title>", page)
        self.assertIn('<li><a href="#one">One</a>', page)                                       # sidebar entry
        self.assertIn('<ul class="sub">', page)
        self.assertNotIn('href="#contents">Contents</a></li>', page.split("<main")[0].split("<nav class=\"toc\"")[1])  # not listed itself
        self.assertEqual(page.count("@@"), 0)

    def test_toc_is_balanced_html(self):
        toc = mdhtml.render_toc(convert("## A\n\n### A1\n\n### A2\n\n## B\n\n### B1\n").headings)
        self.assertEqual(toc.count("<ul"), toc.count("</ul>"))
        self.assertEqual(toc.count("<li>"), toc.count("</li>"))


if __name__ == "__main__":
    unittest.main()
