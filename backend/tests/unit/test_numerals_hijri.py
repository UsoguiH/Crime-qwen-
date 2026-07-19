from datetime import date

from app.services.hijri import dual_date_str, hijri_str
from app.services.numerals import (entity_code, entity_label_ar, fmt_percent,
                                   fmt_seconds, to_arabic_indic)


def test_arabic_indic_digits():
    assert to_arabic_indic(2026) == "٢٠٢٦"
    assert to_arabic_indic("E-001") == "E-٠٠١"


def test_percent_and_seconds():
    assert fmt_percent(0.87) == "٨٧٪"
    assert fmt_seconds(65) == "١:٠٥"
    assert fmt_seconds(3671) == "١:٠١:١١"


def test_entity_codes():
    assert entity_code(7) == "E-007"
    assert entity_label_ar(7) == "دليل ٠٠٧"


def test_hijri_known_date():
    # hijridate documented example: 2023-12-28 CE == 1445-06-15 AH
    assert hijri_str(date(2023, 12, 28)) == "١٥ جمادى الآخرة ١٤٤٥هـ"


def test_dual_date_contains_both():
    text = dual_date_str(date(2026, 7, 19))
    assert "هـ" in text and "م" in text and "الموافق" in text


def test_out_of_range_falls_back():
    assert hijri_str(date(1800, 1, 1)) is None
    assert "م" in dual_date_str(date(1800, 1, 1))
