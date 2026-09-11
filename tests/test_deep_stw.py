import unittest

from fortnite_research.deep_stw import extract_free_the_vbucks, extract_stw_planner


class DeepStwParserTests(unittest.TestCase):
    def test_extracts_free_the_vbucks_summary_and_expiration(self):
        source = """
        <title>Timed Missions</title>
        <link rel="canonical" href="https://freethevbucks.com/timed-missions/">
        <meta property="article:modified_time" content="2026-09-04T09:08:28+00:00">
        <div>50<img src="vbucks.png" alt="V-Bucks"><span>88<i></i></span>
        <span class="hidden-xs">Category 4 Storm</span>
        <span style="font-size: 0.75em"> in Twine Peaks</span></div>
        <script>var expirationDates = ["2026-09-10T00:00:00.000Z"];</script>
        """
        result = extract_free_the_vbucks(source)
        self.assertEqual(result["currentMission"]["vbucks"], 50)
        self.assertEqual(result["currentMission"]["powerLevel"], 88)
        self.assertEqual(result["currentMission"]["zone"], "Twine Peaks")
        self.assertEqual(result["expirationDates"], ["2026-09-10T00:00:00.000Z"])

    def test_extracts_stw_planner_special_mission(self):
        source = """
        <title>Mission Alerts</title>
        <link rel="canonical" href="https://example.test/mission-alerts">
        <span class="time-until" data-time-now="2026-09-09T07:53:54" data-time="2026-09-10T00:00:00"></span>
        <span class="special-title">50 vBucks Available!</span>
        <div class="mission-entry"><div class="mission-type category-4-fight-the-storm"></div>
        <div class="mission-pl">88</div><div class="mission-zone">Twine Peaks<br />Category 4 Fight the Storm - Forest</div></div>
        """
        result = extract_stw_planner(source)
        self.assertEqual(result["availableVbucksText"], "50 vBucks Available!")
        self.assertEqual(result["dataTimeExpires"], "2026-09-10T00:00:00")
        self.assertEqual(result["missionPowerLevel"], 88)
        self.assertEqual(result["missionZone"], "Twine Peaks")
        self.assertEqual(result["missionTypeClass"], "category-4-fight-the-storm")


if __name__ == "__main__":
    unittest.main()
