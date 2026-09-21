import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/jev/scripts"))
import jev


def payload(state, kinds=("choice",)):
    questions = {}
    for kind in kinds:
        if kind == "choice":
            questions["q_choice"] = {"type": "choice", "instructions": "Judge.",
                                     "criteria": {"yes": "evidence supports", "no": "rest"}}
        elif kind == "score":
            questions["q_score"] = {"type": "score", "instructions": "Rate.",
                                    "criteria": ["low", "mid", "high"]}
        else:
            questions["q_noul"] = {"type": "noul", "instructions": "Claim holds?"}
    return {"state": state, "questions": questions}


def choice_answer():
    return {"type": "choice", "choice": "yes", "probabilities": {"yes": 0.9, "no": 0.1},
            "confidence": 0.5}


def score_answer(value):
    return {"type": "score", "score": value, "probabilities": {"0": 0.2, "1": 0.5, "2": 0.3},
            "legend": {"0": "low", "1": "mid", "2": "high"}, "confidence": 0.5}


class AutoRouteTests(unittest.TestCase):
    def test_chinese_mixed_splits(self):
        routes, language = jev.auto_route(payload("选课系统登录失败，今天截止", ("choice", "score")))
        self.assertEqual(language, "chinese")
        self.assertEqual([model for model, _ in routes], ["multilingual", "typed-decisions"])
        self.assertEqual(routes[0][1], {"choice"})
        self.assertEqual(routes[1][1], {"score"})

    def test_english_choice_only(self):
        routes, language = jev.auto_route(payload("Cannot log in, deadline today", ("choice",)))
        self.assertEqual((language, [model for model, _ in routes]), ("english", ["english"]))

    def test_score_goes_to_typed_decisions(self):
        routes, _ = jev.auto_route(payload("数据库宕机", ("score",)))
        self.assertEqual([model for model, _ in routes], ["typed-decisions"])

    def test_mostly_english_with_quote_stays_english(self):
        _, language = jev.auto_route(payload("The invoice shows the amount 中文 twice", ("choice",)))
        self.assertEqual(language, "english")


class DryRunRoutingTests(unittest.TestCase):
    def call(self, args, body):
        output, errors = io.StringIO(), io.StringIO()
        with patch("sys.stdin", io.StringIO(json.dumps(body))), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = jev.main(args)
        return code, output.getvalue(), errors.getvalue()

    def test_mixed_request_prints_two_sub_requests(self):
        with patch("jev.urllib.request.build_opener") as network:
            code, output, _ = self.call(["decide", "-", "--dry-run"],
                                        payload("选课系统登录失败，今天截止", ("choice", "score")))
        self.assertEqual(code, 0)
        network.assert_not_called()
        subs = json.loads(output)
        self.assertEqual([sub["model"] for sub in subs], ["multilingual", "typed-decisions"])
        self.assertEqual(list(subs[0]["questions"]), ["q_choice"])
        self.assertEqual(list(subs[1]["questions"]), ["q_score"])

    def test_single_route_prints_one_resolved_request(self):
        code, output, _ = self.call(["decide", "-", "--dry-run"], payload("Hello", ("choice",)))
        self.assertEqual(json.loads(output)["model"], "english")

    def test_explicit_model_wins(self):
        code, output, _ = self.call(["decide", "-", "--dry-run", "--model", "multilingual"],
                                    payload("Hello", ("choice", "score")))
        body = json.loads(output)
        self.assertEqual(body["model"], "multilingual")
        self.assertEqual(len(body["questions"]), 2)

    def test_unknown_model_flag_is_rejected(self):
        code, _, errors = self.call(["decide", "-", "--dry-run", "--model", "gpt-x"],
                                    payload("Hello", ("choice",)))
        self.assertEqual(code, 1)
        self.assertIn("error", json.loads(errors))

    def test_bundled_model_id_auto_routes(self):
        body = payload("选课系统登录失败", ("choice",))
        body["model"] = jev.DEFAULT_MODEL
        code, output, _ = self.call(["decide", "-", "--dry-run"], body)
        self.assertEqual(json.loads(output)["model"], "multilingual")

    def test_default_provider_is_laya(self):
        args = jev.parser().parse_args(["decide", "-"])
        self.assertEqual(args.provider, "laya")


class MergeTests(unittest.TestCase):
    def test_merge_dicts_and_lists(self):
        first = {"answers": {"a": {"type": "choice"}}}
        second = {"answers": {"b": {"type": "score"}}}
        merged = jev.merge_laya_parts([first, second])
        self.assertEqual(set(merged["answers"]), {"a", "b"})
        lists = jev.merge_laya_parts([[first, first], [second, second]])
        self.assertEqual([sorted(item["answers"]) for item in lists], [["a", "b"]] * 2)

    def test_mismatched_batch_lengths_raise(self):
        with self.assertRaises(jev.JevError):
            jev.merge_laya_parts([[{"answers": {}}], [{"answers": {}}, {"answers": {}}]])


class SplitLiveTests(unittest.TestCase):
    def run_main(self, args, body, fake):
        output, errors = io.StringIO(), io.StringIO()
        with patch("sys.stdin", io.StringIO(json.dumps(body))), \
                patch.object(jev, "request_decisions", side_effect=fake), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = jev.main(args)
        return code, json.loads(output.getvalue()) if output.getvalue().strip() else None

    def test_split_calls_two_models_and_merges(self):
        sent = []

        def fake(sub, timeout=30, provider="laya"):
            sent.append(sub["model"])
            if sub["model"] == "typed-decisions":
                return {"answers": {"q_score": score_answer(1.2)}}
            return {"answers": {"q_choice": choice_answer()}}

        code, report = self.run_main(["decide", "-"], payload("选课系统登录失败，今天截止", ("choice", "score")), fake)
        self.assertEqual(code, 0)
        self.assertEqual(sent, ["multilingual", "typed-decisions"])
        self.assertEqual(report["routing"], {"strategy": "auto", "language": "chinese",
                                             "requests": 2, "models": ["multilingual", "typed-decisions"]})
        self.assertEqual(report["backend"], "multilingual+typed-decisions")
        self.assertEqual(report["mode"], "laya_api")
        self.assertTrue(report["laya_called"])
        self.assertFalse(report["jev_called"])
        self.assertEqual(set(report["decisions"]), {"q_choice", "q_score"})

    def test_split_batch_merges_per_record(self):
        def fake(sub, timeout=30, provider="laya"):
            if sub["model"] == "typed-decisions":
                return [{"answers": {"q_score": score_answer(1.0)}},
                        {"answers": {"q_score": score_answer(1.5)}}]
            return [{"answers": {"q_choice": choice_answer()}},
                    {"answers": {"q_choice": choice_answer()}}]

        code, report = self.run_main(["decide", "-"], payload(["无法登录", "登录又失败"], ("choice", "score")), fake)
        self.assertEqual(code, 0)
        self.assertEqual(len(report["items"]), 2)
        self.assertEqual(report["backend"], "multilingual+typed-decisions")
        self.assertEqual(set(report["items"][0]["decisions"]), {"q_choice", "q_score"})

    def test_explicit_model_report_routing(self):
        def fake(sub, timeout=30, provider="laya"):
            return {"answers": {"q_choice": choice_answer()}}

        code, report = self.run_main(["decide", "-", "--model", "multilingual"],
                                     payload("Hello", ("choice",)), fake)
        self.assertEqual(code, 0)
        self.assertEqual(report["routing"], {"strategy": "explicit", "requests": 1,
                                             "models": ["multilingual"]})


if __name__ == "__main__":
    unittest.main()
