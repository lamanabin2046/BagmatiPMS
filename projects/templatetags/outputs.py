from decimal import Decimal

from django import template

register = template.Library()


@register.filter
def qty(v):
    """Decimal('12.500') -> '12.5', Decimal('10.000') -> '10', None -> ''."""
    if v is None or v == "":
        return ""
    try:
        d = Decimal(str(v))
    except Exception:
        return v
    s = format(d.normalize(), "f")
    return s


NP = str.maketrans("0123456789", "०१२३४५६७८९")


def _group_np(intpart):
    """1234567 -> '12,34,567' (लाख/करोड शैली)."""
    s = str(intpart)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


@register.filter
def money(v, decimals=2):
    """1234567.5 -> '१२,३४,५६७.५०' ; None -> '—'."""
    if v is None or v == "":
        return "—"
    try:
        d = Decimal(str(v)).quantize(Decimal(1) if int(decimals) == 0 else Decimal("0." + "0" * int(decimals)))
    except Exception:
        return v
    neg = d < 0
    d = abs(d)
    s = format(d, "f")
    ip, _, fp = s.partition(".")
    out = _group_np(ip) + ("." + fp if fp else "")
    return ("-" if neg else "") + out.translate(NP)


@register.filter
def npn(v):
    """अङ्क मात्र नेपालीमा (कमा बिना)।"""
    return "" if v is None else str(v).translate(NP)


@register.filter
def sub(a, b):
    """{{ a|sub:b }} — घटाउ (Decimal/float)."""
    from decimal import Decimal

    try:
        return Decimal(str(a or 0)) - Decimal(str(b or 0))
    except Exception:
        return ""


@register.filter
def bs(d):
    """{{ date|bs }} — वि.सं. मिति (नेपाली अङ्कमा)."""
    if not d:
        return ""
    from usercommittee.workflow import bs_date

    return bs_date(d)


@register.simple_tag
def contingency_pct(kind):
    """{% contingency_pct 'uc' %} — सेटिङको कन्टिन्जेन्सी दर (JS मा पनि प्रयोग हुने: अङ्ग्रेजी अङ्क)."""
    from projects.procurement import contingency_pct as cp

    v = cp(kind).normalize()
    return format(v, "f")


@register.filter
def pct_of(part, whole):
    """{{ part|pct_of:whole }} — प्रतिशत (२ दशमलवसम्म, शून्य हटाएर)."""
    from decimal import Decimal, InvalidOperation

    try:
        w = Decimal(str(whole or 0))
        if not w:
            return ""
        v = (Decimal(str(part or 0)) * 100 / w).quantize(Decimal("0.01"))
        return format(v.normalize(), "f")
    except (InvalidOperation, ValueError, TypeError):
        return ""
