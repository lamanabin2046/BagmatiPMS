"""साइट (मोबाइल) — GPS सहितको फोटो, भौतिक प्रगति र दूरी जाँच.

  * फोटोमा मिति-समय (सर्भरको), GPS र योजनाको नाम (अङ्ग्रेजी अक्षरमा) छापिन्छ — पछि फोटो डाउनलोड भए पनि प्रमाण रहन्छ
  * ठूलो फोटो १६०० px सम्म सानो पारिन्छ (मोबाइल डाटा र सर्भर ठाउँ बचत)
  * योजना स्थल नतोकिएको भए पहिलो GPS फोटोबाट तोक्न सकिन्छ; त्यसपछि टाढाबाट खिचेको फोटो रोकिन्छ (कारण लेखे मात्र)
"""
import io
import math
from decimal import Decimal

MAX_SIDE = 1600
MAX_UPLOAD = 15 * 1024 * 1024


def distance_m(lat1, lng1, lat2, lng2):
    """दुई GPS बिन्दुबीचको दूरी (मिटर, haversine)."""
    r = 6371000
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp, dl = p2 - p1, math.radians(float(lng2) - float(lng1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return int(2 * r * math.asin(math.sqrt(a)))


def parse_coord(lat, lng, acc=None):
    """फारमबाट आएका GPS मान — मान्य भए (Decimal lat, Decimal lng, int acc), नत्र (None, None, None)."""
    try:
        la, lo = Decimal(str(lat)).quantize(Decimal("0.000001")), Decimal(str(lng)).quantize(Decimal("0.000001"))
    except Exception:
        return None, None, None
    if not (-90 <= la <= 90 and -180 <= lo <= 180) or (la == 0 and lo == 0):
        return None, None, None
    try:
        a = int(float(acc)) if acc not in (None, "") else None
    except ValueError:
        a = None
    return la, lo, a


def stamp(fileobj, lines):
    """फोटो खोल्ने, घुमाउने (EXIF), सानो पार्ने, तल छाप लगाउने → JPEG bytes. फोटो नभए ValueError."""
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    try:
        img = Image.open(fileobj)
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
    except Exception:
        raise ValueError("फोटो खुलेन — JPG वा PNG फोटो पठाउनुहोस्।")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    w, h = img.size
    size = max(14, w // 55)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", size)
    except Exception:
        font = ImageFont.load_default()
    pad = size // 2
    bar = (size + pad) * len(lines) + pad
    draw = ImageDraw.Draw(img, "RGBA")
    draw.rectangle([0, h - bar, w, h], fill=(0, 0, 0, 150))
    y = h - bar + pad
    for line in lines:
        draw.text((pad, y), line, fill=(255, 255, 255, 255), font=font)
        y += size + pad
    out = io.BytesIO()
    img.save(out, "JPEG", quality=82, optimize=True)
    return out.getvalue()


def ascii_name(text, limit=60):
    """छापका लागि — देवनागरी फन्ट नभएको सर्भरमा पनि पढिने (अङ्क/अङ्ग्रेजी मात्र राख्ने, नत्र योजना नं.)."""
    s = "".join(ch for ch in (text or "") if ord(ch) < 128).strip()
    return s[:limit]


def latest_progress(project):
    t = project.timelines.exclude(progress_pct__isnull=True).order_by("-created_at").first()
    return t.progress_pct if t else None
