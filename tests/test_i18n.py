from __future__ import annotations

import unittest
from unittest.mock import patch

from i18n import TRANSLATIONS, detect_system_language, get_language, set_language, tr, trn


class TranslationTests(unittest.TestCase):
    def tearDown(self):
        set_language("it")

    def test_catalogs_have_the_same_keys(self):
        self.assertEqual(set(TRANSLATIONS["it"]), set(TRANSLATIONS["en"]))

    def test_switches_language(self):
        set_language("en")

        self.assertEqual(get_language(), "en")
        self.assertEqual(tr("gallery.title"), "Gallery")

    def test_uses_english_plural_forms(self):
        set_language("en")

        self.assertEqual(trn("count.photos", 1), "1 photo")
        self.assertEqual(trn("count.photos", 2), "2 photos")

    def test_rejects_unsupported_language(self):
        with self.assertRaises(ValueError):
            set_language("fr")

    @patch("i18n.locale.getlocale", return_value=("Italian_Italy", "1252"))
    def test_detects_windows_italian_locale(self, _getlocale):
        self.assertEqual(detect_system_language(), "it")


if __name__ == "__main__":
    unittest.main()
