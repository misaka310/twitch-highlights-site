import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_twitch_live_status as ctls


class CheckTwitchLiveStatusTests(unittest.TestCase):
    def test_main_prints_live_true(self):
        with (
            mock.patch.object(
                ctls.uv,
                "fetch_current_stream_status",
                return_value={"channel": "dotitao", "live": True, "stream_id": "s1", "started_at": "2026-05-23T03:00:00Z"},
            ),
            mock.patch("builtins.print") as mocked_print,
        ):
            exit_code = ctls.main()
        self.assertEqual(exit_code, 0)
        printed = "\n".join(" ".join(str(arg) for arg in call.args) for call in mocked_print.call_args_list)
        self.assertIn("twitch_live_status: channel=dotitao live=true", printed)
        self.assertIn("stream_id=s1", printed)

    def test_main_prints_live_false(self):
        with (
            mock.patch.object(
                ctls.uv,
                "fetch_current_stream_status",
                return_value={"channel": "dotitao", "live": False, "stream_id": "", "started_at": ""},
            ),
            mock.patch("builtins.print") as mocked_print,
        ):
            exit_code = ctls.main()
        self.assertEqual(exit_code, 0)
        printed = "\n".join(" ".join(str(arg) for arg in call.args) for call in mocked_print.call_args_list)
        self.assertIn("twitch_live_status: channel=dotitao live=false", printed)


if __name__ == "__main__":
    unittest.main()
