"""Pruebas de las utilidades de evidencia y vigencia de datos."""

import unittest
from datetime import datetime, timedelta, timezone

from fortnite_research.evidence import (
    int_or_none,
    int_or_zero,
    parse_utc,
    probe_interpretation,
    probe_status_kind,
    staleness,
    staleness_notice,
    sum_bytes,
)

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


class CoercionTests(unittest.TestCase):
    def test_int_or_none_accepts_common_shapes(self):
        self.assertEqual(int_or_none(7), 7)
        self.assertEqual(int_or_none("12"), 12)
        self.assertEqual(int_or_none("1,234"), 1234)
        self.assertEqual(int_or_none(3.9), 3)

    def test_int_or_none_rejects_unparseable_values(self):
        for value in ("3:45", None, "", "n/d", True, float("inf")):
            with self.subTest(value=value):
                self.assertIsNone(int_or_none(value))

    def test_int_or_zero_uses_zero_as_neutral(self):
        self.assertEqual(int_or_zero(None), 0)
        self.assertEqual(int_or_zero("3:45"), 0)

    def test_sum_bytes_ignores_broken_entries(self):
        entries = [{"bytes": "120"}, {"bytes": None}, {}, {"bytes": 3.9}]

        self.assertEqual(sum_bytes(entries), 123)


class ProbeDiagnosisTests(unittest.TestCase):
    def test_only_not_found_is_reported_as_missing(self):
        text = probe_interpretation(
            {"httpStatus": 404, "available": False},
            not_found="NO PUBLICADA",
        )

        self.assertEqual(text, "NO PUBLICADA")

    def test_rate_limit_is_not_conclusive(self):
        text = probe_interpretation(
            {"httpStatus": 429, "available": False},
            not_found="NO PUBLICADA",
        )

        self.assertNotEqual(text, "NO PUBLICADA")
        self.assertIn("429", text)
        self.assertIn("no concluyente" if "no concluyente" in text else "concluir", text)

    def test_credentials_and_server_error_are_not_conclusive(self):
        for status in (401, 403, 500, 503):
            with self.subTest(status=status):
                text = probe_interpretation(
                    {"httpStatus": status, "available": False},
                    not_found="NO PUBLICADA",
                )
                self.assertIn(str(status), text)
                self.assertNotIn("NO PUBLICADA", text)

    def test_no_response_is_not_conclusive(self):
        text = probe_interpretation({"httpStatus": None}, not_found="NO PUBLICADA")

        self.assertIn("Sin respuesta", text)

    def test_retired_route_is_not_reported_as_missing(self):
        text = probe_interpretation(
            {"httpStatus": 410, "available": False},
            not_found="NO PUBLICADA",
        )

        self.assertIn("retirada", text.lower())
        self.assertNotIn("NO PUBLICADA", text)

    def test_status_kinds(self):
        self.assertEqual(probe_status_kind(404), "not_found")
        self.assertEqual(probe_status_kind(410), "retired")
        self.assertEqual(probe_status_kind(429), "rate_limited")
        self.assertEqual(probe_status_kind(200), "ok")
        self.assertEqual(probe_status_kind("n/d"), "no_response")


class StalenessTests(unittest.TestCase):
    def test_recent_verification_is_not_stale(self):
        days, stale = staleness("2026-09-15", now=NOW, max_age_days=10)

        self.assertEqual(days, 5)
        self.assertFalse(stale)

    def test_old_verification_is_stale(self):
        days, stale = staleness("2026-08-01", now=NOW, max_age_days=10)

        self.assertTrue(stale)
        self.assertGreater(days, 10)

    def test_missing_verification_counts_as_stale(self):
        for value in (None, "", "sin-fecha"):
            with self.subTest(value=value):
                days, stale = staleness(value, now=NOW, max_age_days=10)
                self.assertIsNone(days)
                self.assertTrue(stale)

    def test_notice_warns_loudly_when_stale(self):
        notice = staleness_notice(
            "datos competitivos",
            "2026-08-01",
            now=NOW,
            max_age_days=10,
        )

        self.assertIn("REVALIDAR ANTES DE PUBLICAR", notice)

    def test_notice_is_informative_when_fresh(self):
        notice = staleness_notice(
            "datos competitivos",
            "2026-09-15",
            now=NOW,
            max_age_days=10,
        )

        self.assertIn("Vigencia", notice)
        self.assertNotIn("REVALIDAR ANTES DE PUBLICAR", notice)

    def test_parse_utc_accepts_iso_and_epoch(self):
        self.assertEqual(
            parse_utc("2026-09-15T00:00:00Z"),
            datetime(2026, 9, 15, tzinfo=timezone.utc),
        )
        self.assertEqual(
            parse_utc((NOW - timedelta(hours=1)).timestamp()),
            NOW - timedelta(hours=1),
        )
        self.assertIsNone(parse_utc("no es una fecha"))


if __name__ == "__main__":
    unittest.main()
