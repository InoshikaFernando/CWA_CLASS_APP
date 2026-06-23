"""Phone-number normalization for WhatsApp sends.

WhatsApp addresses recipients by E.164 number, and our dedupe-by-phone logic
only works if numbers are normalized *before* comparison (``021 555 1234`` and
``+6421 5551234`` are the same parent). We delegate parsing to ``phonenumbers``
rather than hand-rolling regexes.
"""
from django.conf import settings

import phonenumbers


def default_region():
    return getattr(settings, 'WHATSAPP_DEFAULT_REGION', 'NZ')


def normalize_msisdn(raw, region=None):
    """Return ``raw`` as an E.164 string (e.g. ``+64211234567``) or None.

    None means the number was blank, unparseable, or not a valid number for the
    region — the caller should treat that recipient as undeliverable.
    """
    if not raw:
        return None
    region = region or default_region()
    try:
        num = phonenumbers.parse(str(raw), region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(num):
        return None
    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
