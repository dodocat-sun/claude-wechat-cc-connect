import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("status", Path(__file__).with_name("claude-status.py"))
status = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(status)


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_state = status.STATE
        status.STATE = Path(self.temp.name)
        self.state = {
            "model": "claude-opus-5-5",
            "effort": "high",
            "usage": {
                "input_tokens": 2,
                "cache_read_input_tokens": 63000,
                "cache_creation_input_tokens": 998,
            },
            "has_text": True,
        }
        self.result = {
            "type": "result",
            "subtype": "success",
            "result": "完成",
            "duration_ms": 1500,
            "usage": {"input_tokens": 9999999},
            "modelUsage": {"claude-opus-5-5": {"contextWindow": 1000000}},
        }

    def tearDown(self):
        status.STATE = self.old_state
        self.temp.cleanup()

    def test_footer_uses_latest_call(self):
        footer = status.status_footer(
            self.state["model"], self.state["effort"], self.state["usage"], self.result,
            {"five_hour": 94, "weekly": 42},
        )
        self.assertIn("Claude Opus 5.5 · 推理：HIGH · 上下文：6.4%", footer)
        self.assertIn("耗时：1.5秒 · 额度剩余：五小时 94% · 本周 42%", footer)

    def test_each_output_path_has_one_footer(self):
        events = status.adapt(self.result, self.state, lambda: None)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["message"]["content"][0]["text"].count("模型："), 1)
        self.assertEqual(events[1]["result"].count("模型："), 1)
        self.assertIn("暂不可读", events[1]["result"])

    def test_errors_and_silent_replies_are_untouched(self):
        for result in (
            dict(self.result, subtype="compact"),
            dict(self.result, is_error=True),
            dict(self.result, result="NO_REPLY"),
        ):
            self.assertEqual(status.adapt(result, self.state, lambda: None), [result])

    def test_missing_data_is_not_invented(self):
        footer = status.status_footer("claude-opus-5-5", "default", {}, {}, None)
        self.assertIn("推理：UNKNOWN · 上下文：未读取", footer)

    def test_new_turn_clears_old_usage(self):
        status.adapt(self.result, self.state, lambda: None)
        self.assertFalse(self.state["has_text"])
        self.assertEqual(self.state["usage"], {})

    def test_effort_matches_exact_message(self):
        root = Path(self.temp.name)
        project = root / ".claude/projects/project"
        project.mkdir(parents=True)
        session = "1234-abcd"
        (project / f"{session}.jsonl").write_text("\n".join(json.dumps(item) for item in (
            {"type": "assistant", "effort": "high", "message": {"id": "old"}},
            {"type": "assistant", "effort": "medium", "message": {"id": "new"}},
        )), encoding="utf-8")
        with patch.object(status.Path, "home", return_value=root):
            self.assertEqual(status.actual_effort(session, "new"), "medium")
            self.assertEqual(status.actual_effort(session, "missing"), "")


if __name__ == "__main__":
    unittest.main()
