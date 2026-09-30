import os
import unittest

from services import (
    _normalize_medical_term_typography, _validate_llm_report, analyze_meeting,
    evaluate_rules, get_asr_backend,
)


class ModelGuardrailTests(unittest.TestCase):
    def test_discussed_item_requires_evidence(self):
        report = {
            "patient_summary": "摘要",
            "discussion_summary": "讨论",
            "key_points": [],
            "comparison_items": [{"item": "手术指征", "status": "discussed", "evidence": []}],
            "discussion_conclusion": "最终结论需由医务人员确认",
            "missing_information": [],
        }
        self.assertFalse(_validate_llm_report(report))

    def test_medical_term_typography_is_normalized(self):
        result = _normalize_medical_term_typography(
            {"key_points": ["患者服用阿: 阿司匹林", "需核对阿司:匹林"]},
            "患者服用阿司匹林",
        )
        self.assertEqual(result["key_points"], ["患者服用阿司匹林", "需核对阿司匹林"])

    def test_production_rejects_non_remote_backend(self):
        previous = os.environ.get("PREOP_ASR_BACKEND")
        previous_testing = os.environ.pop("PREOP_TESTING", None)
        os.environ["PREOP_ASR_BACKEND"] = "test"
        try:
            with self.assertRaises(RuntimeError):
                get_asr_backend()
        finally:
            if previous is None:
                os.environ.pop("PREOP_ASR_BACKEND", None)
            else:
                os.environ["PREOP_ASR_BACKEND"] = previous
            if previous_testing is not None:
                os.environ["PREOP_TESTING"] = previous_testing

    def test_contraindication_rule_keeps_three_source_evidence(self):
        rule = {
            "id": "LOCAL-RISK", "name": "疑似高风险因素", "category": "院内规则",
            "rule_type": "contraindication_term", "severity": "high", "enabled": True,
            "surgery_keywords": ["胆囊"], "trigger_terms": ["严重凝血异常"],
            "required_terms": ["凝血"], "message": "请人工复核凝血相关风险。",
            "source": "院内制度X", "version": "2026.1", "updated_at": "2026-08-07",
        }
        meeting = {"surgery_name": "腹腔镜胆囊切除术", "patient_history": "既往检查提示严重凝血异常。"}
        segments = [{
            "id": "s1", "start_ms": 0, "speaker_id": "speaker_1",
            "corrected_text": "本次需重点复核凝血功能。",
        }]
        alerts = evaluate_rules(meeting, segments, [rule])
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["patient_evidence"][0]["matched_term"], "严重凝血异常")
        self.assertEqual(alerts[0]["meeting_evidence"][0]["segment_id"], "s1")
        self.assertEqual(alerts[0]["knowledge_evidence"][0]["source"], "院内制度X")

    def test_knowledge_comparison_is_merged_without_llm(self):
        previous = os.environ.pop("PREOP_LLM_URL", None)
        try:
            meeting = {
                "surgery_name": "测试手术", "patient_history": "无特殊",
                "segments": [{"id": "s1", "start_ms": 0, "speaker_id": "speaker_1", "corrected_text": "讨论了专项要点。"}],
            }
            rules = [{
                "id": "LOCAL-KB", "name": "院内专项要点", "category": "院内制度",
                "rule_type": "required_discussion", "severity": "warning", "enabled": True,
                "surgery_keywords": [], "trigger_terms": [], "required_terms": ["专项要点"],
                "message": "请核对。", "source": "文件A", "version": "v1",
            }]
            report, alerts, _backend, _prompt = analyze_meeting(meeting, rules)
            item = next(item for item in report["comparison_items"] if item.get("rule_id") == "LOCAL-KB")
            self.assertEqual(item["status"], "discussed")
            self.assertEqual(item["source"], "文件A")
            self.assertEqual(alerts, [])
        finally:
            if previous is not None:
                os.environ["PREOP_LLM_URL"] = previous


if __name__ == "__main__":
    unittest.main()
