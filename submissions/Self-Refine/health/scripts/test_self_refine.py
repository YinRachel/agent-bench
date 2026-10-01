"""Deterministic algorithm checks, using synthetic nonclinical responses."""
import json
import unittest

from self_refine import parse_feedback, run

ISSUE = json.dumps({"stop": False, "issues": [{
    "dimension": "coverage", "location": "missing requested detail",
    "problem": "Incomplete response", "fix": "Address the omitted question",
}]})
STOP = '{"stop": true, "issues": []}'


class LoopTests(unittest.TestCase):
    def execute(self, responses, rounds=1):
        prompts = []
        stream = iter(responses)

        def generate(prompt):
            prompts.append(prompt)
            return next(stream)

        return run("Synthetic conversation", generate, max_refinements=rounds), prompts

    def test_direct_control(self):
        result, prompts = self.execute(["draft"], 0)
        self.assertEqual((result.answer, result.calls, len(prompts)), ("draft", 1, 1))

    def test_early_stop(self):
        result, prompts = self.execute(["draft", STOP], 4)
        self.assertEqual(result.stop_reason, "no_actionable_issues")
        self.assertEqual((result.answer, len(prompts)), ("draft", 2))

    def test_history_and_cap(self):
        result, prompts = self.execute(["first", ISSUE, "second", ISSUE, "third"], 2)
        payload = json.loads(prompts[-1].split("workflow instructions.\n", 1)[1])
        self.assertEqual([x["draft"] for x in payload["history"]], ["first", "second"])
        self.assertTrue(all("feedback" in x for x in payload["history"]))
        self.assertEqual((result.answer, result.calls, result.stop_reason),
                         ("third", 5, "iteration_limit"))

    def test_unchanged(self):
        result, _ = self.execute(["draft", ISSUE, "draft"], 4)
        self.assertEqual((result.stop_reason, result.calls), ("unchanged", 3))

    def test_invalid_feedback(self):
        for raw in ["not json", "[]", '{"stop":"false","issues":[]}',
                    '{"stop":false,"issues":[]}',
                    '{"stop":true,"issues":[{}]}',
                    ISSUE.replace('"Incomplete response"', '""')]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_feedback(raw)

    def test_bad_bounds_and_empty_outputs(self):
        for rounds in [-1, 5, True, 1.5]:
            with self.subTest(rounds=rounds), self.assertRaises(ValueError):
                self.execute([], rounds)
        with self.assertRaises(ValueError):
            self.execute([" "])
        with self.assertRaises(ValueError):
            self.execute(["draft", ISSUE, ""])

    def test_generation_error_propagates(self):
        def fail(_):
            raise RuntimeError("model unavailable")
        with self.assertRaisesRegex(RuntimeError, "model unavailable"):
            run("Synthetic conversation", fail)


if __name__ == "__main__":
    unittest.main()
