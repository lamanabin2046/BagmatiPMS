"""राजस्व ठेक्का — सार्वजनिक सूचना पेज र अनलाइन बोलपत्र (लगइन नचाहिने पेज: /Projects/Public/...).

सुरक्षा:
  * बोलपत्रदाता पालिकाका कर्मचारी होइनन् — छुट्टै तालिका (RevenueBidder), छुट्टै session key; कर्मचारी प्रणालीमा पहुँच छैन
  * पासवर्ड Django hasher बाट; लगइन प्रयास १५ मिनेटमा ५ पटकसम्म
  * कबोल अङ्क सिलबन्दी: HMAC-SHA256 keystream (encrypt-then-MAC), key = SECRET_KEY + पालिका schema बाट;
    पेश गर्ने अन्तिम मिति नसकी प्रणालीले खोल्दैन। (SECRET_KEY र डाटाबेस दुवै पाउने सर्भर प्रशासकले भने खोल्न सक्छ।)
  * म्यादपछि पेश / परिवर्तन नहुने; हरेक पेशको समय र सिलको digest प्राप्ति-पत्रमा
"""
import base64
import hashlib
import hmac
import os
from datetime import date

from django.conf import settings
from django.db import connection

SESSION_KEY = "rev_bidder_id"


def _keys():
    base = hmac.new(settings.SECRET_KEY.encode(), f"revenue-bid-seal:{connection.schema_name}".encode(), hashlib.sha256).digest()
    return (hmac.new(base, b"enc", hashlib.sha256).digest(), hmac.new(base, b"mac", hashlib.sha256).digest())


def _stream(key, nonce, n):
    out, i = b"", 0
    while len(out) < n:
        out += hmac.new(key, nonce + i.to_bytes(4, "big"), hashlib.sha256).digest()
        i += 1
    return out[:n]


def seal(amount):
    enc, mac = _keys()
    nonce = os.urandom(16)
    pt = f"{amount:.2f}".encode()
    ct = bytes(a ^ b for a, b in zip(pt, _stream(enc, nonce, len(pt))))
    tag = hmac.new(mac, nonce + ct, hashlib.sha256).digest()
    blob = "v1:" + ":".join(base64.b64encode(x).decode() for x in (nonce, ct, tag))
    return blob, hashlib.sha256(blob.encode()).hexdigest()


def unseal(obj):
    """कर्मचारीले म्याद सकिएपछि मात्र प्रयोग गर्ने (views मा जाँच)। सिल बिग्रिए ValueError."""
    from decimal import Decimal

    enc, mac = _keys()
    _v, n, c, t = obj.sealed.split(":")
    nonce, ct, tag = (base64.b64decode(x) for x in (n, c, t))
    if not hmac.compare_digest(tag, hmac.new(mac, nonce + ct, hashlib.sha256).digest()):
        raise ValueError("सिल बिग्रिएको")
    return Decimal(bytes(a ^ b for a, b in zip(ct, _stream(enc, nonce, len(ct)))).decode())


def open_for_bids(s):
    return bool(s.approved_at and s.notice_date and s.bid_deadline and not s.award_at and
                s.notice_date <= date.today() <= s.bid_deadline and not s.cancelled_on)


def current_bidder(request):
    from .models import RevenueBidder

    bid = request.session.get(SESSION_KEY)
    return RevenueBidder.objects.filter(id=bid, is_active=True).first() if bid else None


def throttle(request, key, limit=5, seconds=900):
    """True = रोक्नुपर्ने."""
    from django.core.cache import cache

    ip = request.META.get("REMOTE_ADDR", "")
    k = f"revportal:{connection.schema_name}:{key}:{ip}"
    n = cache.get(k, 0)
    if n >= limit:
        return True
    cache.set(k, n + 1, seconds)
    return False


def reset_throttle(request, key):
    from django.core.cache import cache

    cache.delete(f"revportal:{connection.schema_name}:{key}:{request.META.get('REMOTE_ADDR', '')}")
