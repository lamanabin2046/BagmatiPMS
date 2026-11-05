"""फर्म / निर्माण व्यवसायी दर्ता — खोज/थप, कालोसूची जाँच, चालु ठेक्का सीमा, कामको इतिहास र कार्यसम्पादन.

स्रोत:  बोलपत्र (SealedBid.firm), दरभाउपत्र (स्वीकृत फर्मको नाम), सोझै खरिद / संस्था (MinorQuote.firm छानिएको)
ढिलाइ:  बोलपत्र — अन्तिम बिलको ढिलाइ दिन वा “हर्जाना सहित” म्याद थप; सोझै/संस्था — तोकिएको मितिभन्दा पछि सम्पन्न
"""
from datetime import date
from decimal import Decimal

ZERO = Decimal("0")


def D(v):
    return Decimal(str(v or 0))


def find(name="", pan=""):
    from quatation.models import Suchikrit

    name, pan = (name or "").strip(), (pan or "").strip()
    f = Suchikrit.objects.filter(firm_pan=pan).first() if pan else None
    return f or (Suchikrit.objects.filter(firm_name=name).first() if name else None)


def find_or_create(name, pan="", address="", owner="", kind="contractor"):
    from quatation.models import Suchikrit

    f = find(name, pan)
    if f is None and (name or "").strip():
        f = Suchikrit.objects.create(firm_name=name.strip(), firm_pan=(pan or "").strip(), firm_address=address or "",
                                     firm_owner=owner or "", firm_contact="", kind=kind, enlisted=False)
    elif f is not None:
        changed = []
        for field, val in (("firm_pan", pan), ("firm_address", address), ("firm_owner", owner)):
            if val and not getattr(f, field):
                setattr(f, field, val.strip())
                changed.append(field)
        if changed:
            f.save(update_fields=changed)
    return f


def blocked(firm, name="", pan=""):
    """पालिकाको वा PPMO कालोसूचीमा भए कारण, नभए ''. firm नभए पनि नाम/PAN बाट PPMO जाँचिन्छ."""
    from .registry import ppmo_match

    hit = ppmo_match(firm, name, pan) if (firm is not None or name or pan) else None
    if hit is not None:
        who = firm.firm_name if firm is not None else name
        until = f" ({hit.to_date} सम्म)" if hit.to_date else ""
        return f"“{who}” सार्वजनिक खरिद अनुगमन कार्यालय (PPMO) को कालोसूचीमा छ{until} — खरिदमा सहभागी हुन पाउँदैन। {hit.decision}".strip()
    if firm is None:
        return ""
    if firm.is_blacklisted:
        until = f" ({firm.blacklist_until} सम्म)" if firm.blacklist_until else ""
        return f"“{firm.firm_name}” कालोसूचीमा छ{until} — खरिदमा सहभागी हुन पाउँदैन। {firm.blacklist_ref}".strip()
    if not firm.is_active:
        return f"“{firm.firm_name}” निष्क्रिय गरिएको फर्म हो।"
    return ""


def running_contracts(firm, exclude_project=None):
    """सम्झौता भई अन्तिम बिल बाँकी रहेका बोलपत्र ठेक्का."""
    if firm is None:
        return 0
    qs = firm.bids.filter(contract__isnull=False, contract__final_payment__isnull=True)
    if exclude_project is not None:
        qs = qs.exclude(project=exclude_project)
    return qs.count()


def capacity_problem(firm, project=None):
    from .procurement import limits

    cap = limits().max_running_contracts
    if not cap or firm is None:
        return ""
    n = running_contracts(firm, project)
    if n >= cap:
        return f"“{firm.firm_name}” सँग {n} वटा चालु ठेक्का छन् — एकैपटक {cap} वटासम्म मात्र (सेटिङ)।"
    return ""


def history(firm):
    """[{p, kind, kind_label, amount, status, delay_days, ld, note}] र सारांश."""
    from biddings.models import SealedBid

    from .models import MinorProcurement

    rows = []
    for b in (SealedBid.objects.filter(firm=firm).select_related("project__ward", "project__fiscalyear")
              .prefetch_related("contract__extensions", "contract__variations")):
        c = getattr(b, "contract", None)
        fin = getattr(c, "final_payment", None) if c else None
        penalty_ext = sum(1 for e in c.extensions.all() if e.kind == "penalty") if c else 0
        status = "completed" if fin else ("running" if c else "bid")
        delay = fin.ld_days if fin else 0
        if c and not fin and c.current_expiry_date and c.current_expiry_date < date.today():
            delay = (date.today() - c.current_expiry_date).days
        rows.append({"p": b.project, "kind": "bid", "kind_label": "बोलपत्र", "amount": D(b.bidding_amount), "status": status,
                     "delay_days": delay, "ld": D(fin.ld_amount) if fin else ZERO,
                     "note": " · ".join(x for x in (f"{penalty_ext} पटक हर्जानासहित म्याद थप" if penalty_ext else "",
                                                     f"{c.variations.count()} भेरिएसन" if c and c.variations.exists() else "") if x)})
    try:
        from quatation.models import QuationApproval
        for ap in QuationApproval.objects.filter(firm_name=firm.firm_name).select_related("quation__project__ward",
                                                                                          "quation__project__fiscalyear"):
            q = ap.quation
            fin = q.quationfinal_set.first()
            rows.append({"p": q.project, "kind": "quot", "kind_label": "दरभाउपत्र", "amount": D(ap.amount),
                         "status": "completed" if fin else ("running" if q.agreement_date else "bid"),
                         "delay_days": 0, "ld": ZERO, "note": ""})
    except Exception:
        pass
    for m in (MinorProcurement.objects.filter(selected__firm=firm).select_related("project__ward", "project__fiscalyear")
              .prefetch_related("payments")):
        fin = next((p for p in m.payments.all() if p.kind == "final"), None)
        delay = (m.completed_on - m.due_date).days if m.completed_on and m.due_date and m.completed_on > m.due_date else 0
        rows.append({"p": m.project, "kind": m.method, "kind_label": m.get_method_display(),
                     "amount": D(m.order_amount or m.selected.amount), "status": "completed" if fin else "running",
                     "delay_days": delay, "ld": ZERO, "note": ""})
    rows.sort(key=lambda r: (r["p"].fiscalyear.name if r["p"].fiscalyear else "", r["p"].id), reverse=True)
    awarded = [r for r in rows if r["status"] != "bid"]
    done = [r for r in awarded if r["status"] == "completed"]
    late = [r for r in awarded if r["delay_days"] > 0]
    s = {"jobs": len(awarded), "value": sum((r["amount"] for r in awarded), ZERO), "running": sum(1 for r in awarded if r["status"] == "running"),
         "completed": len(done), "late": len(late), "ld": sum((r["ld"] for r in rows), ZERO),
         "on_time_pct": round((len(awarded) - len(late)) * 100 / len(awarded)) if awarded else None}
    return rows, s


def options(kinds=None, include_blocked=False):
    """फारमका datalist का लागि."""
    from quatation.models import Suchikrit

    qs = Suchikrit.objects.filter(is_active=True).order_by("firm_name")
    if kinds:
        qs = qs.filter(kind__in=kinds)
    return [f for f in qs if include_blocked or not f.is_blacklisted]
