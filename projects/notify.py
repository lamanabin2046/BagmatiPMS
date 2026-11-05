"""SMS / इमेल सूचना.

  * कर्मचारी — दिनहुँ आफ्नो 'मेरो काम' का जरुरी / ध्यान दिनुपर्ने काम (इमेलमा पूरा सूची, SMS मा छोटो सारांश)
  * राजस्व ठेकेदार — किस्ता बुझाउने म्याद नजिकिँदा र नाघेपछि (१, ७, १५, ३० दिनमा) SMS / इमेल
  * एउटै सूचना दोहोरिँदैन (NotificationLog.key); असफल भएको अर्को पटक फेरि प्रयास हुन्छ

SMS: Sparrow SMS (api.sparrowsms.com) वा Aakash SMS (sms.aakashsms.com) — token सेटिङमा राख्ने।
चलाउने: python manage.py send_alerts  (cron मा दिनहुँ बिहान)
"""
import json
import re
import urllib.parse
import urllib.request
from datetime import date

from django.db import connection
from django.utils import timezone

SPARROW_URL = "https://api.sparrowsms.com/v2/sms/"
AAKASH_URL = "https://sms.aakashsms.com/sms/v3/send"
LATE_STEPS = (1, 7, 15, 30)
NP_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def phone(raw):
    """'९८४-१२३४५६७' / '+977 9841234567' → '9841234567'; मोबाइल नम्बर नभए ''."""
    d = re.sub(r"\D", "", (raw or "").translate(NP_DIGITS))
    if d.startswith("977") and len(d) == 13:
        d = d[3:]
    return d if re.fullmatch(r"9[678]\d{8}", d) else ""


def email_ok(raw):
    raw = (raw or "").strip()
    return raw if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", raw) else ""


def site_url(S):
    if S.site_url:
        return S.site_url.rstrip("/")
    try:
        d = connection.tenant.domains.filter(is_primary=True).first() or connection.tenant.domains.first()
        return f"https://{d.domain}" if d else ""
    except Exception:
        return ""


def palika_name():
    t = getattr(connection, "tenant", None)
    return (getattr(t, "full_name", "") or getattr(t, "name", "")) if t else ""


# ---------------------------------------------------------------- पठाउने
def _http_post(url, data, timeout=20):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def send_sms(S, to, text):
    """(ok, error)."""
    if not S.sms_provider or not S.sms_token:
        return False, "SMS सेटिङ अधुरो"
    try:
        if S.sms_provider == "sparrow":
            code, body = _http_post(SPARROW_URL, {"token": S.sms_token, "from": S.sms_from or "Demo", "to": to, "text": text})
            ok = code == 200 and '"response_code": 200' in body.replace('"response_code":200', '"response_code": 200')
        else:
            code, body = _http_post(AAKASH_URL, {"auth_token": S.sms_token, "to": to, "text": text})
            try:
                ok = code == 200 and json.loads(body).get("error") is False
            except ValueError:
                ok = False
        return (True, "") if ok else (False, f"{code}: {body[:200]}")
    except Exception as e:
        return False, str(e)[:250]


def _email_connection(S):
    from django.core.mail import get_connection

    return get_connection("django.core.mail.backends.smtp.EmailBackend", host=S.smtp_host, port=S.smtp_port,
                          username=S.smtp_user, password=S.smtp_password, use_tls=S.smtp_tls and S.smtp_port != 465,
                          use_ssl=S.smtp_port == 465, timeout=20)


def send_email(S, to, subject, text, html=None):
    if not S.email_on or not S.smtp_host:
        return False, "इमेल सेटिङ अधुरो"
    from django.core.mail import EmailMultiAlternatives

    try:
        m = EmailMultiAlternatives(subject, text, S.from_email or S.smtp_user, [to], connection=_email_connection(S))
        if html:
            m.attach_alternative(html, "text/html")
        m.send()
        return True, ""
    except Exception as e:
        return False, str(e)[:250]


def deliver(S, key, channel, to, kind, body, subject="", name="", html=None, dry=False):
    """एउटै key पहिले सफल भएको भए नपठाउने. फर्काउँछ: 'sent' | 'failed' | 'dup' | 'dry'."""
    from .models import NotificationLog

    if NotificationLog.objects.filter(key=key, channel=channel, status="sent").exists():
        return "dup"
    if dry:
        return "dry"
    ok, err = send_sms(S, to, body) if channel == "sms" else send_email(S, to, subject, body, html)
    NotificationLog.objects.create(key=key[:120], channel=channel, to=to[:150], name=(name or "")[:200], kind=kind, subject=subject[:200],
                                   body=body, status="sent" if ok else "failed", error=err[:300])
    return "sent" if ok else "failed"


# ---------------------------------------------------------------- के पठाउने
def staff_messages(S, today=None):
    """[(user, items)] — staff_roles का सक्रिय प्रयोगकर्ता, जरुरी / ध्यान दिनुपर्ने काम भएका मात्र."""
    from accounts.models import CustomUser
    from accounts.mywork import compute

    roles = [r.strip() for r in (S.staff_roles or "").split(",") if r.strip()]
    out = []
    for u in CustomUser.objects.filter(is_active=True, user_type__in=roles).order_by("id"):
        items = [i for i in compute(u)["items"] if i["tone"] in ("urgent", "warn")]
        if items:
            out.append((u, items))
    return out


def _np(x):
    return str(x).translate(str.maketrans("0123456789", "०१२३४५६७८९"))


def _bs(d):
    from biddings.views_workflow import to_bs

    return _np(to_bs(d))


def _rs(v):
    from .templatetags.outputs import money

    return money(v, 0)


def revenue_party(s):
    """राजस्व ठेकेदारको (नाम, मोबाइल, इमेल)."""
    b = s.selected
    if b is None:
        return "", "", ""
    mob, mail = "", ""
    if b.firm_id:
        mob, mail = phone(b.firm.firm_contact), email_ok(b.firm.email)
    if not mob or not mail:
        ob = s.online_bids.filter(bidder__name=b.name).select_related("bidder").first()
        if ob:
            mob = mob or phone(ob.bidder.mobile)
            mail = mail or email_ok(ob.bidder.email)
    return b.name, mob, mail


def revenue_messages(S, today=None):
    """[(key, kind, source, name, mobile, email, text)]."""
    from decimal import Decimal

    from . import revenue as rv

    today = today or date.today()
    L = rv.settings_()
    out = []
    pal = palika_name()
    for s in rv.queryset().filter(selected__isnull=False, settled_on__isnull=True, cancelled_on__isnull=True).select_related("selected__firm"):
        name, mob, mail = revenue_party(s)
        if not (mob or mail):
            continue
        for i in s.instalments.all():
            left = Decimal(i.amount) - Decimal(i.paid_amount)
            if left <= 0:
                continue
            days = (i.due_date - today).days
            if S.rev_due_sms and 0 <= days <= L.rev_reminder_days:
                txt = (f"{pal}: {s.name} ठेक्काको किस्ता रु. {_rs(left)} मिति {_bs(i.due_date)} भित्र बुझाउनुहोस्। "
                       f"म्याद नाघे विलम्ब शुल्क लाग्छ।")
                out.append((f"rev-due:{i.id}:{i.due_date}", "rev_due", s, name, mob, mail, txt))
            elif S.rev_late_sms and days < 0:
                late = -days
                step = max((x for x in LATE_STEPS if late >= x), default=None)
                if step is None:
                    continue
                fee = rv.late_fee(left, i.due_date, today, L.rev_late_fee_pct)
                txt = (f"{pal}: {s.name} ठेक्काको किस्ता रु. {_rs(left)} को म्याद {_bs(i.due_date)} मा नाघ्यो ({_np(late)} दिन)। "
                       + (f"विलम्ब शुल्क रु. {_rs(fee)} सहित " if fee else "") + "तुरुन्त बुझाउनुहोस्।")
                out.append((f"rev-late:{i.id}:{step}", "rev_late", s, name, mob, mail, txt))
    return out


def run(dry=False, today=None, only=None):
    """यो पालिकाको सबै सूचना. फर्काउँछ गन्ती dict."""
    from django.template.loader import render_to_string

    from .models import NotifySettings

    S = NotifySettings.get()
    today = today or date.today()
    c = {"sent": 0, "failed": 0, "dup": 0, "dry": 0, "no_contact": 0}
    can_sms, can_mail = bool(S.sms_provider and S.sms_token), bool(S.email_on and S.smtp_host)
    url = site_url(S)
    pal = palika_name()
    if S.staff_digest and only in (None, "staff"):
        for u, items in staff_messages(S, today):
            urgent = sum(i["count"] for i in items if i["tone"] == "urgent")
            warn = sum(i["count"] for i in items if i["tone"] == "warn")
            name = u.get_full_name() or u.mobile or ""
            sent_any = False
            if can_mail and email_ok(u.email):
                subject = f"{pal} — आजका काम: {_np(urgent)} जरुरी, {_np(warn)} ध्यान दिनुपर्ने"
                text = "\n".join(f"- {i['label']}: {i['count']} ({url}{i['url']})" for i in items)
                html = render_to_string("projects/email_digest.html", {"u": name, "items": items, "url": url, "pal": pal,
                                                                       "urgent": urgent, "warn": warn, "today": _bs(today)})
                c[deliver(S, f"digest:{u.id}:{today}", "email", u.email, "staff", text, subject, name, html, dry)] += 1
                sent_any = True
            mob = phone(u.mobile)
            if can_sms and mob and (urgent or not S.staff_sms_urgent):
                text = (f"{pal} PMS: तपाईंका {_np(urgent)} जरुरी" + (f" र {_np(warn)} ध्यान दिनुपर्ने" if warn else "")
                        + " काम छन्।" + (f" {url}/" if url else ""))
                c[deliver(S, f"digest:{u.id}:{today}", "sms", mob, "staff", text, "", name, None, dry)] += 1
                sent_any = True
            if not sent_any:
                c["no_contact"] += 1
    if only in (None, "revenue"):
        for key, kind, s, name, mob, mail, text in revenue_messages(S, today):
            sent_any = False
            if can_sms and mob:
                c[deliver(S, key, "sms", mob, kind, text, "", name, None, dry)] += 1
                sent_any = True
            if can_mail and mail:
                c[deliver(S, key, "email", mail, kind, text, f"{pal} — राजस्व ठेक्का किस्ता", name, None, dry)] += 1
                sent_any = True
            if not sent_any:
                c["no_contact"] += 1
    if not dry:
        S.last_run = timezone.now()
        S.save(update_fields=["last_run"])
    return c
