"""पुराना बोलपत्र विजेता र सोझै/संस्थाका दरभाउ — फर्म दर्तामा जोड्ने (PAN, नभए नाम मिलाएर; नभए नयाँ थप्ने)."""
from django.db import migrations


def _firm(F, name, pan="", address="", owner="", kind="contractor"):
    name = (name or "").strip()
    if not name:
        return None
    f = None
    if pan:
        f = F.objects.filter(firm_pan=pan).first()
    f = f or F.objects.filter(firm_name=name).first()
    if f is None:
        f = F.objects.create(firm_name=name, firm_pan=pan or "", firm_address=address or "", firm_owner=owner or "",
                             firm_contact="", kind=kind, enlisted=False)
    return f


def forward(apps, schema_editor):
    F = apps.get_model("quatation", "Suchikrit")
    Bid = apps.get_model("biddings", "SealedBid")
    Q = apps.get_model("projects", "MinorQuote")
    for b in Bid.objects.filter(firm__isnull=True).exclude(bidder_name_nepali__isnull=True).exclude(bidder_name_nepali=""):
        b.firm = _firm(F, b.bidder_name_nepali, address=b.bidder_address_nepali or "", owner=b.bidder_owner_nepali or "")
        b.save(update_fields=["firm"])
    for q in Q.objects.filter(firm__isnull=True).select_related("minor"):
        kind = "organization" if q.minor.method == "sanstha" else "supplier"
        q.firm = _firm(F, q.name, pan=q.pan, address=q.address, kind=kind)
        q.save(update_fields=["firm"])


class Migration(migrations.Migration):
    dependencies = [("projects", "0016_minorquote_firm_and_more"), ("biddings", "0019_sealedbid_firm"),
                    ("quatation", "0004_suchikrit_blacklist_reason_suchikrit_blacklist_ref_and_more")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
