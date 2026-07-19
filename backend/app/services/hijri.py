"""Dual Hijri/Gregorian date formatting (hijridate, Umm al-Qura 1924–2077)."""
from datetime import date

from hijridate import Gregorian

from app.services.numerals import to_arabic_indic

HIJRI_MONTHS = [
    "محرم", "صفر", "ربيع الأول", "ربيع الآخر", "جمادى الأولى", "جمادى الآخرة",
    "رجب", "شعبان", "رمضان", "شوال", "ذو القعدة", "ذو الحجة",
]
GREGORIAN_MONTHS_AR = [
    "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
    "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
]


def hijri_str(g: date) -> str | None:
    try:
        h = Gregorian(g.year, g.month, g.day).to_hijri()
        return f"{to_arabic_indic(h.day)} {HIJRI_MONTHS[h.month - 1]} {to_arabic_indic(h.year)}هـ"
    except (ValueError, OverflowError):
        return None


def gregorian_str_ar(g: date) -> str:
    return f"{to_arabic_indic(g.day)} {GREGORIAN_MONTHS_AR[g.month - 1]} {to_arabic_indic(g.year)}م"


def dual_date_str(g: date) -> str:
    hij = hijri_str(g)
    greg = gregorian_str_ar(g)
    return f"{hij} الموافق {greg}" if hij else greg
