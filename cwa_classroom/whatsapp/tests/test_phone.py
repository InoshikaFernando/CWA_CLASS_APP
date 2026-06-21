from django.test import SimpleTestCase

from whatsapp.phone import normalize_msisdn


class NormalizeMsisdnTests(SimpleTestCase):
    def test_blank_returns_none(self):
        self.assertIsNone(normalize_msisdn(''))
        self.assertIsNone(normalize_msisdn(None))

    def test_invalid_returns_none(self):
        self.assertIsNone(normalize_msisdn('not a phone'))
        self.assertIsNone(normalize_msisdn('12'))

    def test_nz_local_to_e164(self):
        self.assertEqual(normalize_msisdn('021 123 4567'), '+64211234567')

    def test_already_e164_preserved(self):
        self.assertEqual(normalize_msisdn('+64211234567'), '+64211234567')

    def test_local_and_e164_normalize_equal(self):
        # The dedupe-by-phone logic depends on these collapsing to one value.
        self.assertEqual(
            normalize_msisdn('021 123 4567'),
            normalize_msisdn('+64 21 1234 567'),
        )

    def test_region_override(self):
        # A UK number parsed against the GB region.
        self.assertEqual(normalize_msisdn('07911 123456', region='GB'),
                         '+447911123456')
