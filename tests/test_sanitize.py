# SPDX-License-Identifier: GPL-3.0-or-later
"""Teacher-written HTML is rendered on our origin: only formatting survives."""

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openlms.data import academic_year, file_links, sanitize_html  # noqa: E402


class SanitizeTest(unittest.TestCase):
    def test_keeps_formatting(self):
        self.assertEqual(sanitize_html("<p>Hi <b>all</b>, <em>see</em><br>below</p><ul><li>one</li></ul>"),
                         "<p>Hi <b>all</b>, <em>see</em><br>below</p><ul><li>one</li></ul>")

    def test_drops_scripts_styles_and_handlers(self):
        out = sanitize_html('<p onclick="steal()" style="x">ok</p><script>alert(1)</script><style>p{}</style>'
                            '<iframe src="https://evil"></iframe><img src=x onerror=alert(1)>')
        self.assertEqual(out, "<p>ok</p>")

    def test_links_are_http_only_and_open_safely(self):
        self.assertEqual(sanitize_html('<a href="javascript:alert(1)">x</a>'),
                         '<a target="_blank" rel="noopener noreferrer">x</a>')
        self.assertEqual(sanitize_html('<a href="https://a.test/b?c=1&d=2">y</a>'),
                         '<a href="https://a.test/b?c=1&amp;d=2" target="_blank" rel="noopener noreferrer">y</a>')
        self.assertEqual(sanitize_html('<img src="data:image/png;base64,xx">'), "")

    def test_void_and_self_closing_dropped_tags_do_not_swallow_text(self):
        self.assertEqual(sanitize_html("<div><input name=x>after<script/>more</div>"), "<div>aftermore</div>")

    def test_balances_tags_and_ignores_strays(self):
        self.assertEqual(sanitize_html("</div><p>open<b>bold"), "<p>open<b>bold</b></p>")

    def test_plain_text_keeps_lines_and_escapes(self):
        self.assertEqual(sanitize_html("a & b\nc"), "a &amp; b<br>c")
        self.assertEqual(sanitize_html(None), "")


class HelpersTest(unittest.TestCase):
    def test_academic_year_rolls_over_in_june(self):
        self.assertEqual(academic_year(date(2026, 10, 9)), "2026-27")
        self.assertEqual(academic_year(date(2027, 3, 1)), "2026-27")
        self.assertEqual(academic_year(date(2027, 6, 1)), "2027-28")

    def test_file_links(self):
        self.assertEqual(file_links([{"url": "https://s3/x/Sheet%201.pdf?sig=1", "type": "file"}, {"name": "no url"},
                                     "https://s3/y.docx", {"file_url": "https://s3/z", "name": "z.png", "size_bytes": 5}]),
                         [{"name": "Sheet%201.pdf", "url": "https://s3/x/Sheet%201.pdf?sig=1", "type": "file", "size": None},
                          {"name": "y.docx", "url": "https://s3/y.docx", "type": None, "size": None},
                          {"name": "z.png", "url": "https://s3/z", "type": None, "size": 5}])


if __name__ == "__main__":
    unittest.main()
