"""सम्पादकबाट आएको HTML सफा गर्ने (script, event handler, बाहिरी link आदि हटाउने)."""
import re
from html import escape
from html.parser import HTMLParser

ALLOWED_TAGS = {
    "p", "br", "div", "span", "b", "strong", "i", "em", "u", "s", "strike", "sub", "sup", "small",
    "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "hr",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup", "col", "font",
}
VOID = {"br", "hr", "col"}
ALLOWED_ATTRS = {"style", "class", "colspan", "rowspan", "align", "width", "valign", "dir", "size", "color"}
ALLOWED_CSS = {
    "text-align", "font-weight", "font-style", "font-size", "text-decoration", "color", "background-color",
    "margin", "margin-left", "margin-right", "margin-top", "margin-bottom", "padding", "padding-left",
    "padding-right", "padding-top", "padding-bottom", "line-height", "width", "height", "border",
    "border-collapse", "border-top", "border-bottom", "border-left", "border-right", "vertical-align",
    "text-indent", "letter-spacing", "white-space", "list-style-type", "font-family",
}
DROP_CONTENT = {"script", "style", "iframe", "object", "embed", "noscript", "template", "svg", "math"}
BAD_CSS = re.compile(r"url\s*\(|expression\s*\(|javascript:|@import|behavior", re.I)


def _clean_style(value):
    out = []
    for decl in value.split(";"):
        if ":" not in decl:
            continue
        prop, val = decl.split(":", 1)
        prop, val = prop.strip().lower(), val.strip()
        if prop in ALLOWED_CSS and val and not BAD_CSS.search(val):
            out.append(f"{prop}: {val}")
    return "; ".join(out)


class _Cleaner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.out, self.stack, self.skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in DROP_CONTENT:
            self.skip += 1
            return
        if self.skip or tag not in ALLOWED_TAGS:
            return
        parts = []
        for k, v in attrs:
            k = (k or "").lower()
            if k not in ALLOWED_ATTRS or v is None:
                continue
            if k == "style":
                v = _clean_style(v)
                if not v:
                    continue
            parts.append(f' {k}="{escape(v, quote=True)}"')
        self.out.append(f"<{tag}{''.join(parts)}>")
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() in self.stack[-1:] and tag.lower() not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in DROP_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in ALLOWED_TAGS or tag in VOID or tag not in self.stack:
            return
        while self.stack:
            t = self.stack.pop()
            self.out.append(f"</{t}>")
            if t == tag:
                break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(escape(data, quote=False))

    def handle_entityref(self, name):
        if not self.skip:
            self.out.append(f"&{name};")

    def handle_charref(self, name):
        if not self.skip:
            self.out.append(f"&#{name};")

    def close(self):
        super().close()
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")


def clean_html(html):
    c = _Cleaner()
    c.feed(html or "")
    c.close()
    return "".join(c.out).strip()
