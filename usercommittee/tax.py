"""अन्तिम भुक्तानीको कर कट्टी — पालिकाअनुसार फरक कर शीर्षक (TaxHead).

फारमबाट tax_head[] (code) र tax_amount[] आउँछ; FinalPayment.tax_deduction मा {code: रकम} बस्छ।
"""
from decimal import Decimal, InvalidOperation

# कर शीर्षक तालिका बन्नुअघिका अभिलेखका नाम
LEGACY = {
    "agrim_tax": "अग्रिम कर कट्टी",
    "bahal_tax": "भर्पाइमा हुने बहाल कर",
    "dhuwani_tax": "ढुवानीमा हुने बहाल कर",
    "sasu_tax": "सामाजिक सुरक्षा कर",
}
NP = str.maketrans("०१२३४५६७८९", "0123456789")


def tax_labels():
    from .models import TaxHead

    labels = dict(LEGACY)
    labels.update(dict(TaxHead.objects.values_list("code", "name")))
    return labels


def active_heads():
    from .models import TaxHead

    return list(TaxHead.objects.filter(is_active=True))


def parse_tax_rows(post, allowed_codes):
    """(tax_dict, errors). खाली/शून्य row छोडिन्छ; एउटै शीर्षक दोहोरिए रकम जोडिन्छ।"""
    heads, amounts = post.getlist("tax_head"), post.getlist("tax_amount")
    out, errors = {}, []
    for i, code in enumerate(heads):
        raw = (amounts[i] if i < len(amounts) else "").strip().translate(NP).replace(",", "")
        if not code and not raw:
            continue
        if not code:
            errors.append(f"रकम {raw} को कर शीर्षक छान्नुहोस्।")
            continue
        if code not in allowed_codes:
            errors.append("कर शीर्षक मिलेन, पेज फेरि खोल्नुहोस्।")
            continue
        try:
            amount = Decimal(raw or "0")
        except InvalidOperation:
            errors.append(f"कर रकम मिलेन: {raw}")
            continue
        if amount < 0:
            errors.append("कर रकम ऋणात्मक हुन सक्दैन।")
            continue
        if amount == 0:
            continue
        out[code] = float(Decimal(str(out.get(code, 0))) + amount)
    return out, errors


def tax_rows(tax_deduction):
    """सम्पादन फारमका लागि [(code, रकम)] — शून्य बाहेक।"""
    return [(k, v) for k, v in (tax_deduction or {}).items() if v not in (0, 0.0, "0", None, "")]
