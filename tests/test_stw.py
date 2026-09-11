import unittest

from fortnite_research.client import APIResult, FortniteAPIError
from fortnite_research.stw import build_stw_report


class FakeClient:
    def get(self, path, params):
        if path in {"/v2/missions", "/v2/alerts", "/v2/stw/missions", "/v2/stw/alerts"}:
            raise FortniteAPIError("not found", status_code=404)
        if path == "/v2/news/stw":
            return APIResult(path, dict(params), 200, {"status": 200, "data": {"messages": [{"title": "STW"}]}})
        if path == "/v2/news":
            return APIResult(path, dict(params), 200, {"status": 200, "data": {"br": {}, "stw": {"messages": []}}})
        if path == "/v2/shop":
            return APIResult(path, dict(params), 200, {"status": 200, "data": {"entries": []}})
        raise AssertionError(path)


class StwReportTests(unittest.TestCase):
    def test_report_keeps_stw_response_and_marks_alert_candidates_missing(self):
        report = build_stw_report(FakeClient(), "es")
        self.assertTrue(report["findings"]["stwNewsEndpoint"]["available"])
        self.assertEqual(report["findings"]["stwNewsEndpoint"]["messageCount"], 1)
        self.assertTrue(report["findings"]["combinedNewsEndpoint"]["includesStwKey"])
        self.assertEqual(len(report["findings"]["missionAndVbuckAlerts"]["pathsNotAvailable"]), 4)
        self.assertIn("/v2/news/stw", report["responses"])


if __name__ == "__main__":
    unittest.main()
