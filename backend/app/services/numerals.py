"""Arabic-Indic numeral formatting — the report and UI captions use ٠١٢٣٤٥٦٧٨٩."""

_MAP = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def to_arabic_indic(value) -> str:
    return str(value).translate(_MAP)


def fmt_int(value: int) -> str:
    return to_arabic_indic(f"{value}")


def fmt_percent(fraction: float) -> str:
    return to_arabic_indic(f"{round(fraction * 100)}") + "٪"


def fmt_seconds(seconds: float) -> str:
    """mm:ss or h:mm:ss with Arabic-Indic digits."""
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    text = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    return to_arabic_indic(text)


def entity_code(seq: int) -> str:
    """Internal citation code (Latin, stable for validators)."""
    return f"E-{seq:03d}"


def entity_label_ar(seq: int) -> str:
    return "دليل " + to_arabic_indic(f"{seq:03d}")
