from html.parser import HTMLParser
from typing import List


class _HTMLTextExtractor(HTMLParser):
    """Strips tags from HTML, dropping <script>/<style> contents."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._chunks: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip_depth += 1
        elif tag in ("br", "p", "div", "tr", "li"):
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            self._chunks.append(data)

    def get_text(self) -> str:
        return "".join(self._chunks)


def html_to_text(html: str) -> str:
    """Convert an HTML body to readable plain text using only the stdlib."""
    parser = _HTMLTextExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    lines = [ln.strip() for ln in parser.get_text().splitlines()]
    return "\n".join(ln for ln in lines if ln)
