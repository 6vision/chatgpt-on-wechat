"""HTML extraction keeps readable text and block boundaries."""

import pytest

from agent.tools.web_fetch.web_fetch import WebFetch


@pytest.mark.parametrize(
    "html, expected_lines",
    [
        ("<h1>Quarterly report</h1><p>Revenue increased.</p><p>Costs fell.</p>",
         ["Quarterly report", "Revenue increased.", "Costs fell."]),
        ("<ul><li>North</li><li>South</li></ul>", ["North", "South"]),
        ("<p>Street 12<br>Suite 34<br/>Paris</p>", ["Street 12", "Suite 34", "Paris"]),
        ("<table><tr><td>Revenue</td><td>42</td></tr><tr><td>Costs</td><td>17</td></tr></table>",
         ["Revenue", "42", "Costs", "17"]),
        ('<p title="a > b">Visible paragraph.</p>', ["Visible paragraph."]),
        ("<p>Caf&#233; costs &#x20ac;42 &copy; 2026.</p>", ["Café costs €42 © 2026."]),
        ("<p>Literal &amp;lt;p&amp;gt; &lt; 42 &gt; 17.</p>", ["Literal &lt;p&gt; < 42 > 17."]),
        ("<!-- hidden > comment --><p>Visible.</p>", ["Visible."]),
        ("<div>First<section>Second<p>Third</p></section>Fourth</div>",
         ["First", "Second", "Third", "Fourth"]),
    ],
)
def test_html_preserves_readable_text(html, expected_lines):
    text = WebFetch._extract_text(html)
    assert [line for line in text.splitlines() if line] == expected_lines


@pytest.mark.parametrize(
    "html, expected",
    [
        ("<p>Py<strong>thon</strong> is <em>useful</em>.</p>", "Python is useful."),
        ("<p>Before<script>if (a < b) {secret()}</script><style>.secret {color:red}</style> after.</p>",
         "Before after."),
        ("<P>中文 <SPAN>résumé</SPAN> 🐄</P>", "中文 résumé 🐄"),
        ("Plain text\n\nwith   spaces", "Plain text\n\nwith spaces"),
        ('<p>Read <a href="/doc?a=1&amp;b=2">the guide</a> today.</p>', "Read the guide today."),
        ('<p>Before <img src="photo.png" alt="Photo"> after.</p>', "Before after."),
        ("<p>Text <script>document.write('<style>hidden</style>')</script> stays.</p>", "Text stays."),
        ("<p>Text <style>p::after {content: '<script>hidden</script>'}</style> stays.</p>", "Text stays."),
        ("<p>Unclosed <strong>inline", "Unclosed inline"),
        ("2 < 3 and 5 > 4", "2 < 3 and 5 > 4"),
        ("<p>Before<script>unterminated secret", "Before"),
        ("<p>Before<style>unterminated secret", "Before"),
        ("<p>A &amp; B &lt; C &gt; D &quot;x&quot; &#39;y&#39; &nbsp; E</p>",
         'A & B < C > D "x" \'y\' E'),
        ("", ""),
    ],
)
def test_existing_text_controls(html, expected):
    assert WebFetch._extract_text(html) == expected
