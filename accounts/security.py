"""लगइन सुरक्षा — गलत पासवर्डमा खाता अस्थायी बन्द, र पासवर्ड बिर्सँदा SMS OTP.

  * १५ मिनेटभित्र ५ पटक गलत पासवर्ड → १५ मिनेट लगइन बन्द (फेरि दोहोरिए ६० मिनेट)
  * एउटै IP बाट घण्टामा ३० पटकभन्दा बढी गलत → त्यो IP बाट केही समय रोक (धेरै नम्बर चलाएर अनुमान गर्ने रोक्न)
  * OTP: ६ अङ्क, १० मिनेट मान्य, ५ पटक मात्र प्रयास; एक नम्बरमा घण्टामा ३ पटक, ६० सेकेन्डको अन्तर
  * OTP को कोड डाटाबेस वा SMS लगमा राखिँदैन (HMAC मात्र)
  * नम्बर दर्ता छ कि छैन भन्ने कुरा जवाफबाट थाहा हुँदैन
"""
import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

MAX_FAILS = 5
FAIL_WINDOW = timedelta(minutes=15)
LOCK_FIRST = timedelta(minutes=15)
LOCK_REPEAT = timedelta(minutes=60)
IP_MAX_FAILS = 30
OTP_TTL = timedelta(minutes=10)
OTP_MAX_TRIES = 5
OTP_PER_HOUR = 3
OTP_GAP_SECONDS = 60
NP_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def norm_mobile(raw):
    import re

    d = re.sub(r"\D", "", (raw or "").translate(NP_DIGITS))
    if d.startswith("977") and len(d) == 13:
        d = d[3:]
    return d[:20]


def client_ip(request):
    return (request.META.get("REMOTE_ADDR") or "")[:45]


def _schema():
    return getattr(connection, "schema_name", "public")


def _np(x):
    return str(x).translate(str.maketrans("0123456789", "०१२३४५६७८९"))


# ---------------------------------------------------------------- गलत पासवर्ड
def _ip_key(ip):
    return f"loginfail:{_schema()}:{ip}"


def lock_status(mobile, ip=""):
    """बन्द भए बाँकी मिनेट (int), नत्र None."""
    from .models import LoginLock

    if ip and (cache.get(_ip_key(ip)) or 0) >= IP_MAX_FAILS:
        return 60
    lk = LoginLock.objects.filter(mobile=norm_mobile(mobile)).first()
    if lk and lk.locked_until and lk.locked_until > timezone.now():
        return max(1, int((lk.locked_until - timezone.now()).total_seconds() // 60) + 1)
    return None


def record_failure(mobile, ip=""):
    """गलत पासवर्ड. फर्काउँछ: (अब बन्द भयो?, बाँकी प्रयास)."""
    from .models import LoginLock

    if ip:
        k = _ip_key(ip)
        try:
            cache.incr(k)
        except ValueError:
            cache.set(k, 1, 3600)
    m = norm_mobile(mobile)
    if not m:
        return False, MAX_FAILS
    now = timezone.now()
    lk, _ = LoginLock.objects.get_or_create(mobile=m)
    if not lk.first_fail or now - lk.first_fail > FAIL_WINDOW or (lk.locked_until and lk.locked_until <= now and lk.failures >= MAX_FAILS):
        lk.failures, lk.first_fail = 0, now
    lk.failures += 1
    locked = False
    if lk.failures >= MAX_FAILS:
        lk.lock_count += 1
        lk.locked_until = now + (LOCK_REPEAT if lk.lock_count > 1 else LOCK_FIRST)
        locked = True
    lk.save()
    if locked:
        _notify_lock(m, lk)
    return locked, max(0, MAX_FAILS - lk.failures)


def clear_failures(mobile):
    from .models import LoginLock

    LoginLock.objects.filter(mobile=norm_mobile(mobile)).update(failures=0, first_fail=None, locked_until=None)


def _notify_lock(mobile, lk):
    """खाता बन्द हुँदा प्रयोगकर्तालाई SMS (SMS सेटिङ भए मात्र)."""
    from .models import CustomUser

    u = CustomUser.objects.filter(mobile=mobile, is_active=True).first()
    if u is None:
        return
    mins = int((lk.locked_until - timezone.now()).total_seconds() // 60) + 1
    try:
        from projects import notify as nt

        S = sms_settings()
        if S is None:
            return
        txt = (f"{nt.palika_name()} PMS: तपाईंको खातामा {_np(MAX_FAILS)} पटक गलत पासवर्ड हालियो, {_np(mins)} मिनेट लगइन बन्द गरिएको छ। "
               "तपाईं आफैँ होइन भने Admin लाई खबर गर्नुहोस्।")
        nt.deliver(S, f"lock:{u.id}:{lk.locked_until:%Y%m%d%H%M}", "sms", nt.phone(u.mobile), "lock", txt, "", u.get_full_name() or u.mobile)
    except Exception:
        pass


def log_login(user, ok, note=""):
    try:
        from usercommittee.models import ActivityLog

        ActivityLog.objects.create(user=user if ok or user else None, action="update", model_name="लगइन",
                                   object_id=getattr(user, "pk", None), object_repr=("सफल लगइन" if ok else "लगइन असफल")[:250],
                                   note=note[:250])
    except Exception:
        pass


# ---------------------------------------------------------------- SMS OTP
def sms_settings():
    """SMS चल्ने भए NotifySettings, नत्र None (public schema मा पनि None)."""
    if _schema() == "public":
        return None
    try:
        from projects.models import NotifySettings

        S = NotifySettings.objects.order_by("id").first()
    except Exception:
        return None
    return S if S and S.sms_provider and S.sms_token else None


def _hash(user_id, code):
    msg = f"{_schema()}:{user_id}:{code}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()


def request_otp(mobile, ip=""):
    """OTP पठाउने. फर्काउँछ: ('sent'|'unknown'|'wait'|'limit'|'off'|'failed', सेकेन्ड)."""
    from .models import CustomUser, PasswordOTP

    S = sms_settings()
    if S is None:
        return "off", 0
    m = norm_mobile(mobile)
    ip_k = f"otpip:{_schema()}:{ip}"
    if ip and (cache.get(ip_k) or 0) >= 10:
        return "limit", 0
    try:
        cache.incr(ip_k)
    except ValueError:
        cache.set(ip_k, 1, 3600)
    u = CustomUser.objects.filter(mobile=m, is_active=True).first()
    from projects import notify as nt

    if u is None or not nt.phone(u.mobile):
        return "unknown", 0
    now = timezone.now()
    recent = PasswordOTP.objects.filter(user=u, created_at__gte=now - timedelta(hours=1))
    last = recent.first()
    if last and (now - last.created_at).total_seconds() < OTP_GAP_SECONDS:
        return "wait", int(OTP_GAP_SECONDS - (now - last.created_at).total_seconds()) + 1
    if recent.count() >= OTP_PER_HOUR:
        return "limit", 0
    PasswordOTP.objects.filter(user=u, used_at__isnull=True).update(used_at=now)      # पुराना रद्द
    code = f"{secrets.randbelow(1000000):06d}"
    otp = PasswordOTP.objects.create(user=u, code_hash=_hash(u.id, code), expires_at=now + OTP_TTL, ip=ip)
    txt = f"{nt.palika_name()} PMS: पासवर्ड परिवर्तन कोड {code} (१० मिनेट मान्य)। यो कोड कसैलाई नदिनुहोस्।"
    ok, err = nt.send_sms(S, nt.phone(u.mobile), txt)
    from projects.models import NotificationLog
    NotificationLog.objects.create(key=f"otp:{otp.id}", channel="sms", to=nt.phone(u.mobile), name=(u.get_full_name() or u.mobile)[:200],
                                   kind="otp", body="पासवर्ड परिवर्तन कोड ****** (कोड लगमा राखिँदैन)",
                                   status="sent" if ok else "failed", error=err[:300])
    if not ok:
        otp.used_at = now
        otp.save(update_fields=["used_at"])
        return "failed", 0
    return "sent", 0


def verify_otp(mobile, code):
    """फर्काउँछ: (user | None, त्रुटि सन्देश)."""
    from .models import CustomUser, PasswordOTP

    m = norm_mobile(mobile)
    code = norm_mobile(code)            # नेपाली अङ्क पनि चल्ने
    u = CustomUser.objects.filter(mobile=m, is_active=True).first()
    otp = PasswordOTP.objects.filter(user=u, used_at__isnull=True).first() if u else None
    if otp is None or otp.expires_at <= timezone.now():
        return None, "कोडको म्याद सकियो वा कोड पठाइएको छैन — फेरि कोड माग्नुहोस्।"
    if otp.tries >= OTP_MAX_TRIES:
        return None, "धेरै पटक गलत कोड — फेरि नयाँ कोड माग्नुहोस्।"
    if not hmac.compare_digest(otp.code_hash, _hash(u.id, code)):
        otp.tries += 1
        if otp.tries >= OTP_MAX_TRIES:
            otp.used_at = timezone.now()
        otp.save(update_fields=["tries", "used_at"])
        left = OTP_MAX_TRIES - otp.tries
        return None, (f"कोड मिलेन — अझै {_np(left)} पटक प्रयास गर्न सकिन्छ।" if left else "धेरै पटक गलत कोड — फेरि नयाँ कोड माग्नुहोस्।")
    return u, ""


def consume_otp(user):
    from .models import PasswordOTP

    PasswordOTP.objects.filter(user=user, used_at__isnull=True).update(used_at=timezone.now())
