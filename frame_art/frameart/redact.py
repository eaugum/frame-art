"""The API's key kept out of the add-on's log and the event log (AUG-1777).

aiohttp logs a malformed request with its raw request line and headers, and a caller can put the key anywhere, so
every log record (through the record factory, whichever logger or handler) and every event's text go through text().
"""
import logging
import re
import urllib.parse

SHORT = 8  # a shorter key is hidden only where it's plainly a key (Bearer …, key=…), not inside every word
_FORMS = re.compile(r"(?i)(\bbearer\s+|[?&]key=)[^\s&'\"]+")
_key = ""
_forms = None  # the key as typed, as aiohttp logs its bytes (H\xc3\xb8...) and percent-encoded


def hide(key):
    """From now on, key is in no log record and no event."""
    global _key, _forms
    _key = key or ""
    forms = {_key, repr(_key.encode())[2:-1], urllib.parse.quote(_key, safe=""), urllib.parse.quote_plus(_key)}
    _forms = re.compile("|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True)), re.IGNORECASE) \
        if len(_key) >= SHORT else None
    _install()


def holds(value):
    """Whether value holds the key: anywhere and in any case, or, for a short key, as the whole value."""
    v, k = str(value or "").strip().lower(), _key.lower()
    return bool(k) and (v == k or (len(k) >= SHORT and k in v))


def text(s):
    s = _FORMS.sub(lambda m: m.group(1) + "…", s)
    return _forms.sub("…", s) if _forms else s


def _install():
    make = logging.getLogRecordFactory()
    if getattr(make, "redacts", False):
        return

    def record(*args, **kwargs):
        r = make(*args, **kwargs)
        try:
            msg = r.getMessage()
            if r.exc_info and r.exc_info[0]:  # the exception's text too: aiohttp's has the raw request in it
                msg += "\n" + logging.Formatter().formatException(r.exc_info).rstrip()
        except Exception:
            return r
        r.msg, r.args, r.exc_info, r.exc_text = text(msg), None, None, None
        return r

    record.redacts = True
    logging.setLogRecordFactory(record)
