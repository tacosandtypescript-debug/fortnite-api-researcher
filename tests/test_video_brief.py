"""Prueba que el guion de vídeo avisa cuando sus datos competitivos envejecen."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fortnite_research import video_brief
from fortnite_research.video_brief import build_video_brief


class FakeClient:
    base_url = "https://fortnite-api.com"

    def get(self, path, params):
        return SimpleNamespace(status_code=200, payload={"data": []})


class VideoBriefStalenessTests(unittest.TestCase):
    def _build(self, temporary: str):
        with patch("fortnite_research.video_brief._read_public_post", return_value=([], None)):
            return build_video_brief(FakeClient(), Path(temporary), language="es")

    def test_report_includes_verification_notice(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifacts = self._build(temporary)
            report = artifacts.report_path.read_text(encoding="utf-8")

        self.assertIn("Vigencia", report)
        self.assertIn(video_brief.WEEZY_FACTS_VERIFIED_AT, report)

    def test_snapshot_records_verification_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifacts = self._build(temporary)
            snapshot = json.loads(artifacts.snapshot_path.read_text(encoding="utf-8"))

        verification = snapshot["eventEvidence"]["verification"]
        self.assertEqual(verification["verifiedAt"], video_brief.WEEZY_FACTS_VERIFIED_AT)
        self.assertFalse(verification["revalidatedInThisRun"])
        self.assertIn("ageDays", verification)

    def test_notice_warns_once_the_snapshot_is_old(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch(
                "fortnite_research.video_brief.WEEZY_FACTS_VERIFIED_AT",
                "2020-01-01",
            ):
                artifacts = self._build(temporary)
            report = artifacts.report_path.read_text(encoding="utf-8")

        self.assertIn("REVALIDAR ANTES DE PUBLICAR", report)

    def test_staleness_helper_marks_missing_date_as_stale(self):
        days, stale = video_brief.staleness(
            "",
            now=datetime(2026, 9, 20, tzinfo=timezone.utc),
            max_age_days=video_brief.WEEZY_FACTS_MAX_AGE_DAYS,
        )

        self.assertIsNone(days)
        self.assertTrue(stale)


if __name__ == "__main__":
    unittest.main()
