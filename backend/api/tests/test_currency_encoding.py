"""
Regression tests for INR currency rendering and text encoding.

The dashboard renders rupee amounts that travel through three layers: the
synthetic persona file, the JSON API and the browser. A single UTF-8 /
cp1252 round trip anywhere in that path turns the rupee sign into three
mangled characters, which corrupts the figure and triples its length - and
that is what pushed the Safe-to-Spend figures out of their panel.

These tests pin the encoding at each layer so the regression cannot come back.
"""

import json
import unittest
from pathlib import Path

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from api.views import PersonaListView

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
PERSONA_FILE = REPO_ROOT / "synthetic_data" / "personas.json"

RUPEE = "\u20b9"

# The exact character sequences that appear when UTF-8 bytes are decoded as
# cp1252. They are assembled from code points so this file does not contain
# the very sequences it looks for.
MOJIBAKE_MARKERS = (
    "\u00e2\u20ac",   # a euro sign where an em dash or rupee sign belongs
    "\u00e2\u201a",   # the first half of a mis-decoded rupee sign
)


def assert_no_mojibake(case, text, where):
    for marker in MOJIBAKE_MARKERS:
        case.assertNotIn(
            marker,
            text,
            msg=f"{where} contains a mis-decoded character sequence {marker!r}",
        )


class CurrencyEncodingTests(TestCase):
    """The rupee sign and the data behind it must survive intact."""

    def setUp(self):
        self.factory = APIRequestFactory()

    # -- the data file ------------------------------------------------------
    def test_01_persona_file_is_valid_utf8(self):
        raw = PERSONA_FILE.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:  # pragma: no cover - failure path
            self.fail(f"synthetic_data/personas.json is not valid UTF-8: {exc}")
        assert_no_mojibake(self, text, "synthetic_data/personas.json")

    def test_02_persona_file_carries_the_real_rupee_sign(self):
        data = json.loads(PERSONA_FILE.read_text(encoding="utf-8"))
        symbols = {p.get("currency_symbol") for p in data["personas"]}
        self.assertEqual(symbols, {RUPEE})
        self.assertIn(RUPEE, PERSONA_FILE.read_text(encoding="utf-8"))

    def test_03_persona_amounts_are_numbers_not_strings(self):
        data = json.loads(PERSONA_FILE.read_text(encoding="utf-8"))
        persona = data["personas"][0]
        self.assertIsInstance(persona["monthly_average_income"], (int, float))
        self.assertIsInstance(
            persona["account_summary"]["current_balance"], (int, float)
        )
        # The exact INR values the dashboard shows must not be altered.
        self.assertEqual(persona["monthly_average_income"], 82000)
        self.assertEqual(persona["account_summary"]["current_balance"], 54200)

    # -- the API ------------------------------------------------------------
    def test_04_persona_api_returns_the_real_rupee_sign(self):
        req = self.factory.get("/api/v1/personas/")
        resp = PersonaListView.as_view()(req)
        self.assertEqual(resp.status_code, 200)

        payload = json.loads(json.dumps(resp.data, ensure_ascii=False))
        symbols = {p.get("currency_symbol") for p in payload["personas"]}
        self.assertEqual(symbols, {RUPEE})
        assert_no_mojibake(self, json.dumps(payload, ensure_ascii=False), "the API response")

    def test_05_persona_api_response_is_utf8_encodable(self):
        req = self.factory.get("/api/v1/personas/")
        resp = PersonaListView.as_view()(req)
        raw = json.dumps(resp.data, ensure_ascii=False).encode("utf-8")
        decoded = raw.decode("utf-8")
        self.assertIn(RUPEE, decoded)
        assert_no_mojibake(self, decoded, "the serialised API response")

    def test_06_api_never_double_encodes_amounts(self):
        """The rendered amount must contain exactly one rupee sign."""
        req = self.factory.get("/api/v1/personas/")
        resp = PersonaListView.as_view()(req)
        payload = json.loads(json.dumps(resp.data, ensure_ascii=False))
        persona = payload["personas"][0]
        rendered = f"{persona['currency_symbol']}{persona['monthly_average_income']:,}"
        self.assertEqual(rendered, f"{RUPEE}82,000")
        self.assertEqual(rendered.count(RUPEE), 1)
        self.assertEqual(len(rendered), len(f"{RUPEE}82,000"))

    # -- the sources --------------------------------------------------------
    def test_07_backend_sources_have_no_mojibake(self):
        for path in BACKEND_ROOT.rglob("*.py"):
            if "__pycache__" in path.parts or "venv" in path.parts:
                continue
            if path.name == Path(__file__).name:
                continue
            text = path.read_text(encoding="utf-8")
            assert_no_mojibake(self, text, str(path.relative_to(REPO_ROOT)))

    def test_08_frontend_sources_have_no_mojibake(self):
        """The frontend is what renders the amounts, so it is checked too."""
        frontend = REPO_ROOT / "frontend" / "src"
        if not frontend.exists():  # pragma: no cover - defensive
            self.skipTest("frontend sources are not present")
        checked = 0
        for path in frontend.rglob("*"):
            if path.suffix not in (".jsx", ".js", ".css") or not path.is_file():
                continue
            raw = path.read_bytes()
            self.assertFalse(
                raw.startswith(b"\xef\xbb\xbf"),
                msg=f"{path.name} starts with a UTF-8 byte order mark",
            )
            text = raw.decode("utf-8")
            assert_no_mojibake(self, text, str(path.relative_to(REPO_ROOT)))
            checked += 1
        self.assertGreater(checked, 5)

    def test_09_frontend_sources_use_the_real_rupee_sign(self):
        """Where a rupee sign is written in a component, it is the real one."""
        frontend = REPO_ROOT / "frontend" / "src"
        hits = 0
        for path in frontend.rglob("*.jsx"):
            text = path.read_text(encoding="utf-8")
            if RUPEE in text:
                hits += 1
                self.assertNotIn("\u00e2\u201a\u00b9", text)
                self.assertNotIn("\u00e2\u20ac", text)
        self.assertGreater(hits, 5, "the dashboard is expected to render rupee amounts")


class HtmlCharsetTests(TestCase):
    """The document must declare UTF-8 so the browser decodes it correctly."""

    def test_01_index_html_declares_utf8(self):
        html = (REPO_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        self.assertIn('charset="UTF-8"', html.replace("utf-8", "UTF-8"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
