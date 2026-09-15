import unittest
from unittest.mock import patch

from fortnite_research.deep_icon_cup_research import _public_media_urls


class PublicMediaResolutionTests(unittest.TestCase):
    @patch(
        "fortnite_research.deep_icon_cup_research._safe_public_json",
        return_value=(
            {"url": "https://api.fxtwitter.com/status/teaser", "httpStatus": 200},
            {
                "tweet": {
                    "media": {
                        "all": [
                            {
                                "type": "video",
                                "url": "https://cdn.example.test/actual.mp4",
                                "thumbnail_url": "https://cdn.example.test/actual.jpg",
                                "width": 1920,
                            }
                        ]
                    }
                }
            },
        ),
    )
    @patch(
        "fortnite_research.deep_icon_cup_research._read_public_post",
        return_value=(
            [{"url": "https://api.fxtwitter.com/status/post", "httpStatus": 200}],
            {"photos": [{"url": "https://cdn.example.test/poster.jpg"}]},
        ),
    )
    def test_prefers_media_urls_resolved_from_public_payload(
        self,
        mocked_post,
        mocked_teaser,
    ):
        _, _, _, poster, video, thumbnail = _public_media_urls(5)
        self.assertEqual(poster, "https://cdn.example.test/poster.jpg")
        self.assertEqual(video, "https://cdn.example.test/actual.mp4")
        self.assertEqual(thumbnail, "https://cdn.example.test/actual.jpg")


if __name__ == "__main__":
    unittest.main()
