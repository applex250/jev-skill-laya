import contextlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/jev/scripts"))
import jev


def request(kind="choice"):
    question = {"type": kind, "instructions": "Judge the evidence."}
    if kind == "choice":
        question["criteria"] = {"continue": "Enough evidence", "review": "Unclear"}
    elif kind == "score":
        question["criteria"] = ["Low", "Medium", "High"]
    return {"model": "auto", "state": {"evidence": "Synthetic"}, "questions": {"q": question}}


def choice(label="continue", probability=0.95):
    return {"answers": {"q": {"type": "choice", "choice": label,
                              "probabilities": {"continue": probability, "review": 1 - probability},
                              "confidence": 0.01}}, "usage": {"cost": 0.001}}


class RequestTests(unittest.TestCase):
    def test_all_types(self):
        for kind in ["choice", "score", "noul"]:
            self.assertEqual(jev.validate_request(request(kind)), request(kind))

    def test_noul_criteria(self):
        value = request("noul")
        value["questions"]["q"]["criteria"] = {"true": "Established", "false": "Not established"}
        jev.validate_request(value)
        value["questions"]["q"]["criteria"].pop("false")
        with self.assertRaises(jev.JevError):
            jev.validate_request(value)

    def test_reject_bad_requests(self):
        for payload in [[], {}, {**request(), "messages": []}, {**request(), "questions": {}},
                        {**request(), "state": None}, {**request(), "state": True},
                        {**request(), "state": 42}, {**request(), "model": ""}]:
            with self.subTest(payload=payload), self.assertRaises(jev.JevError):
                jev.validate_request(payload)
        for kind, criteria in [("choice", []), ("choice", {"one": "only"}),
                               ("score", ["one"]), ("score", list(range(11))),
                               ("noul", None), ("text", {}), ("score", [1, 2]),
                               ("choice", {"a": 1, "b": 2})]:
            payload = request()
            payload["questions"]["q"].update(type=kind, criteria=criteria)
            with self.subTest(kind=kind), self.assertRaises(jev.JevError):
                jev.validate_request(payload)

    def test_nonfinite_json(self):
        for value in ["NaN", "Infinity", "-Infinity"]:
            with self.assertRaises(jev.JevError):
                jev.load_json('{"value":' + value + '}')

    def test_assets_valid(self):
        assets = Path(__file__).resolve().parents[1] / "skills/jev/assets"
        for path in assets.glob("*.json"):
            payload = json.loads(path.read_text())
            if "questions" in payload:
                with self.subTest(path=path.name):
                    jev.validate_request({"model": "auto", **payload})


class ReportTests(unittest.TestCase):
    def test_uses_probability_not_api_confidence(self):
        report = jev.build_report(request(), choice())
        self.assertEqual(report["decisions"]["q"]["status"], "selected")
        self.assertFalse(report["policy"]["executes_actions"])
        self.assertEqual(report["response"]["usage"]["cost"], 0.001)

    def test_abstains_when_unclear(self):
        for response in [choice(probability=0.6), choice("review", 0.01), choice(probability=0.5)]:
            self.assertEqual(jev.build_report(request(), response)["decisions"]["q"]["status"], "needs_review")

    def test_margin(self):
        self.assertEqual(jev.build_report(request(), choice(probability=0.8), min_margin=0.7)
                         ["decisions"]["q"]["status"], "needs_review")

    def test_bad_response(self):
        for response in [{}, {"answers": {}}, {"answers": {"q": {"type": "score"}}},
                         choice("missing"), choice(probability=float("nan")), choice(probability=True),
                         choice(probability=1.5), choice("review", 0.99)]:
            with self.subTest(response=response), self.assertRaises(jev.JevError):
                jev.build_report(request(), response)

    def test_missing_distribution_label(self):
        response = choice()
        response["answers"]["q"]["probabilities"].pop("review")
        with self.assertRaises(jev.JevError):
            jev.build_report(request(), response)

    def test_invalid_distribution_not_selected(self):
        response = choice()
        response["answers"]["q"]["probabilities"] = {"continue": 1, "review": 0.5}
        with self.assertRaises(jev.JevError):
            jev.build_report(request(), response)

    def test_defer_needs_review(self):
        payload = request()
        payload["questions"]["q"]["criteria"] = {"work": "Work", "defer": "Not enough evidence"}
        response = {"answers": {"q": {"type": "choice", "choice": "defer",
                    "probabilities": {"work": 0, "defer": 1}, "confidence": 1}}}
        self.assertEqual(jev.build_report(payload, response)["decisions"]["q"]["status"], "needs_review")

    def test_large_candidate_set_cannot_hide_invalid_distribution(self):
        payload = request()
        payload["questions"]["q"]["criteria"] = {f"c{i}": "Candidate" for i in range(255)}
        response = {"answers": {"q": {"type": "choice", "choice": "c0", "confidence": 1,
                    "probabilities": {f"c{i}": 1 if i == 0 else 0.004 for i in range(255)}}}}
        with self.assertRaises(jev.JevError):
            jev.build_report(payload, response)

    def test_noul_true_false_and_uncertain(self):
        for probability, value, status in [(0.98, True, "selected"), (0.02, False, "selected"),
                                           (0.5, False, "needs_review"), (0.7, True, "needs_review")]:
            result = jev.build_report(request("noul"), {"answers": {"q": {"type": "noul", "noul": probability}}})
            self.assertEqual((result["decisions"]["q"]["value"], result["decisions"]["q"]["status"]), (value, status))

    def test_score_not_probability(self):
        def response(score):
            return {"answers": {"q": {"type": "score", "score": score,
                    "probabilities": {"0": 0, "1": 0.25, "2": 0.75},
                    "legend": {"0": "Low", "1": "Medium", "2": "High"}, "confidence": 0.5}}}
        result = jev.build_report(request("score"), response(1.75))
        self.assertEqual(result["decisions"]["q"], {"status": "scored", "value": 1.75, "levels": ["Low", "Medium", "High"]})
        for score in [True, -1, 3, float("inf")]:
            with self.assertRaises(jev.JevError):
                jev.build_report(request("score"), response(score))
        with self.assertRaises(jev.JevError):
            jev.build_report(request("score"), {"answers": {"q": {"type": "score", "score": 1}}})


class TransportTests(unittest.TestCase):
    def test_refuses_other_endpoints_and_redirects(self):
        with self.assertRaises(jev.JevError):
            jev.http_json("https://untrusted.example/", request())
        self.assertIsNone(jev.NoRedirect().redirect_request(None, None, 302, "", {}, "https://untrusted.example/"))

    def test_laya_endpoint_no_auth_header_no_retries(self):
        with patch("jev.urllib.request.build_opener") as opener:
            response = opener.return_value.open.return_value.__enter__.return_value
            response.read.return_value = json.dumps({"ok": True, "result": choice()}).encode()
            jev.request_decisions(request())
            sent = opener.return_value.open.call_args.args[0]
            self.assertEqual(sent.full_url, jev.LAYA_URL)
            self.assertIsNone(sent.get_header("Authorization"))
            self.assertEqual(json.loads(sent.data), request())
            opener.return_value.open.assert_called_once()

    def test_error_does_not_print_service_body(self):
        with patch("jev.urllib.request.build_opener") as opener:
            opener.return_value.open.side_effect = urllib.error.HTTPError(
                jev.LAYA_URL, 429, "private-record", {}, io.BytesIO(b"private-record"))
            with self.assertRaisesRegex(jev.JevError, "HTTP 429") as error:
                jev.request_decisions(request())
            self.assertNotIn("private-record", str(error.exception))
            self.assertEqual(error.exception.http_status, 429)
            opener.return_value.open.assert_called_once()


class CLITests(unittest.TestCase):
    def test_usage_error_is_not_review_exit(self):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors), self.assertRaises(SystemExit) as stopped:
            jev.main(["decide"])
        self.assertEqual(stopped.exception.code, 1)
        self.assertIn("error", json.loads(errors.getvalue()))

    def call(self, args, payload):
        output, errors = io.StringIO(), io.StringIO()
        with patch("sys.stdin", io.StringIO(json.dumps(payload))), contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = jev.main(args)
        return code, output.getvalue(), errors.getvalue()

    def test_dry_run_never_calls_network(self):
        with patch("jev.request_decisions") as api:
            code, output, _ = self.call(["decide", "-", "--dry-run"], request())
            self.assertEqual(code, 0)
            printed = json.loads(output)
            self.assertEqual(printed["model"], "english")
            self.assertEqual(printed["state"], request()["state"])
            self.assertEqual(printed["questions"], request()["questions"])
            api.assert_not_called()

    def test_bad_threshold_no_spend(self):
        with patch("jev.request_decisions") as api:
            code, _, _ = self.call(["decide", "-", "--min-probability", "nan"], request())
            self.assertEqual(code, 1)
            api.assert_not_called()

    def test_exit_review(self):
        with patch("jev.request_decisions", return_value=choice(probability=0.6)):
            code, output, _ = self.call(["decide", "-"], request())
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output)["decisions"]["q"]["status"], "needs_review")

    def test_empty_request(self):
        code, output, errors = self.call(["decide", "-"], [])
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertIn("error", json.loads(errors))


if __name__ == "__main__":
    unittest.main()
