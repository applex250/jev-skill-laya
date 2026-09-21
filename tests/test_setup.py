import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/jev/scripts"))
import jev


class SetupTests(unittest.TestCase):
    def test_setup_reports_laya_only_without_network(self):
        output = io.StringIO()
        with patch("jev.urllib.request.build_opener") as network, \
                contextlib.redirect_stdout(output):
            self.assertEqual(jev.main(["setup"]), 0)
            network.assert_not_called()
        result = json.loads(output.getvalue())
        self.assertEqual(result["route"], "L")
        self.assertEqual(result["endpoint"], jev.LAYA_URL)
        self.assertFalse(result["key_required"])
        self.assertIn("free", result["cost"])
        self.assertEqual(result["variants"], list(jev.LAYA_MODELS))
        self.assertFalse(result["jev_called"])
        self.assertNotIn("options", result)
        self.assertNotIn("key_pages", result)
