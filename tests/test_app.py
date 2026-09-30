import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from app import build_server


class PrototypeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["PREOP_TESTING"] = "1"
        os.environ["PREOP_ASR_BACKEND"] = "test"
        os.environ["PREOP_QUIET"] = "1"
        cls.server = build_server(
            "127.0.0.1", 0,
            os.path.join(cls.temp.name, "test.db"),
            os.path.join(cls.temp.name, "uploads"),
        )
        cls.base = "http://127.0.0.1:{}".format(cls.server.server_port)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.temp.cleanup()

    def request(self, path, method="GET", body=None, headers=None):
        data = None
        request_headers = headers or {}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(
            self.base + path, data=data, headers=request_headers, method=method
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def multipart(self, fields, filename="sample.wav", file_bytes=b"RIFFtest"):
        boundary = "----PreopBoundary7MA4YWxkTrZu0gW"
        chunks = []
        for key, value in fields.items():
            chunks.extend([
                "--{}\r\n".format(boundary).encode(),
                'Content-Disposition: form-data; name="{}"\r\n\r\n'.format(key).encode(),
                str(value).encode("utf-8"), b"\r\n",
            ])
        chunks.extend([
            "--{}\r\n".format(boundary).encode(),
            'Content-Disposition: form-data; name="audio"; filename="{}"\r\n'.format(filename).encode(),
            b"Content-Type: audio/wav\r\n\r\n", file_bytes, b"\r\n",
            "--{}--\r\n".format(boundary).encode(),
        ])
        return b"".join(chunks), "multipart/form-data; boundary={}".format(boundary)

    def test_full_meeting_workflow(self):
        status, health = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["asr_backend"], "test-stub")

        status, meeting = self.request("/api/meetings", "POST", {
            "meeting_date": "2026-08-05",
            "patient_code": "P-AUTO-001",
            "surgery_name": "腹腔镜胆囊切除术",
            "surgery_site": "腹部",
            "department": "普外科",
            "expected_speaker_min": 2,
            "expected_speaker_max": 3,
            "patient_history": "患者既往使用阿司匹林，青霉素过敏。",
        })
        self.assertEqual(status, 201)
        meeting_id = meeting["id"]

        upload_body, content_type = self.multipart({
            "transcript_hint": "患者拟行腹腔镜胆囊切除术。手术指征明确。麻醉医生建议评估气道与麻醉风险。术后加强观察。"
        })
        request = urllib.request.Request(
            self.base + "/api/meetings/{}/upload".format(meeting_id),
            data=upload_body,
            headers={"Content-Type": content_type, "Content-Length": str(len(upload_body))},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            uploaded = json.loads(response.read().decode("utf-8"))
        self.assertTrue(uploaded["audio_filename"].endswith(".wav"))

        status, processed = self.request(
            "/api/meetings/{}/process".format(meeting_id), "POST", {}
        )
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(processed["segments"]), 4)
        self.assertIsNotNone(processed["report"])
        self.assertEqual(processed["processing"]["asr_backend"], "test-stub")
        self.assertTrue(any(item["rule_id"] == "CHECK-ANTICOAGULATION" for item in processed["alerts"]))

        first = processed["segments"][0]
        status, segment = self.request(
            "/api/segments/{}".format(first["id"]), "PUT",
            {"speaker_role": "主刀医生", "corrected_text": first["corrected_text"], "review_status": "reviewed"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(segment["speaker_role"], "主刀医生")
        self.assertEqual(segment["review_status"], "reviewed")

        status, reanalyzed = self.request(
            "/api/meetings/{}/reanalyze".format(meeting_id), "POST", {}
        )
        self.assertEqual(status, 200)
        self.assertIsNotNone(reanalyzed["report"])

        status, reviewed = self.request(
            "/api/meetings/{}/report".format(meeting_id), "PUT",
            {"discussion_conclusion": "经人工校对的测试结论。", "key_points": ["人工关键点1", "人工关键点2"]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(reviewed["report"]["content"]["discussion_conclusion"], "经人工校对的测试结论。")
        self.assertEqual(reviewed["status"], "reviewing")

        status, confirmed = self.request(
            "/api/meetings/{}/confirm".format(meeting_id), "POST", {"actor": "测试医生001"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(confirmed["confirmed_by"], "测试医生001")

        status, dashboard = self.request("/api/dashboard")
        self.assertGreaterEqual(dashboard["total"], 1)
        self.assertGreaterEqual(dashboard["confirmed"], 1)

    def test_rule_crud_and_validation(self):
        status, rule = self.request("/api/rules", "POST", {
            "name": "测试讨论项",
            "category": "集成测试",
            "rule_type": "required_discussion",
            "severity": "warning",
            "required_terms": ["测试关键字"],
            "message": "请核对测试讨论项。",
            "source": "测试规则1.0",
        })
        self.assertEqual(status, 201)
        self.assertTrue(rule["id"].startswith("LOCAL-"))
        status, updated = self.request("/api/rules/{}".format(rule["id"]), "PUT", {
            "enabled": False, "version": "test-2",
        })
        self.assertEqual(status, 200)
        self.assertFalse(updated["enabled"])
        self.assertEqual(updated["version"], "test-2")
        status, updated = self.request("/api/rules/{}".format(rule["id"]), "PUT", {"enabled": True})
        self.assertTrue(updated["enabled"])

        status, tested = self.request("/api/rules/test", "POST", {
            "rule_id": rule["id"],
            "surgery_name": "测试手术",
            "patient_history": "无特殊",
            "transcript": "本次未讨论指定项目。",
        })
        self.assertEqual(status, 200)
        self.assertTrue(tested["matched"])
        self.assertEqual(tested["alerts"][0]["rule_id"], rule["id"])

        status, exported = self.request("/api/rules/export")
        self.assertEqual(exported["schema_version"], "preop-knowledge-1")
        self.assertTrue(any(item["id"] == rule["id"] for item in exported["items"]))

        status, imported = self.request("/api/rules/import", "POST", {
            "items": [{
                "name": "导入测试项", "category": "导入测试",
                "rule_type": "conditional_term", "severity": "high",
                "trigger_terms": ["特殊用药"], "required_terms": ["停药"],
                "message": "请核对特殊用药。", "source": "测试知识文件",
            }],
        })
        self.assertEqual(imported["created"], 1)
        self.assertEqual(imported["skipped"], 0)

        status, rules = self.request("/api/rules")
        self.assertTrue(any(item["id"] == rule["id"] for item in rules["items"]))
        self.assertGreaterEqual(rules["summary"]["custom"], 2)
        status, deleted = self.request("/api/rules/{}".format(rule["id"]), "DELETE")
        self.assertTrue(deleted["deleted"])

        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request("/api/rules", "POST", {
                "name": "无效条件规则", "rule_type": "conditional_term",
                "message": "无效", "source": "测试",
            })
        self.assertEqual(context.exception.code, 400)

        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request("/api/meetings", "POST", {"patient_code": "", "surgery_name": ""})
        self.assertEqual(context.exception.code, 400)

    def test_frontend_and_assets_are_served(self):
        for path, expected_type in [
            ("/", "text/html"),
            ("/assets/hospital-logo.png", "image/png"),
        ]:
            with urllib.request.urlopen(self.base + path, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(expected_type, response.headers.get("Content-Type", ""))
                self.assertGreater(len(response.read()), 50)

        with urllib.request.urlopen(self.base + "/", timeout=5) as response:
            html = response.read().decode("utf-8")
        self.assertIn('id="app"', html)
        self.assertIn('/static/assets/index-', html)

    def test_local_recording_settings(self):
        status, settings = self.request("/api/settings")
        self.assertEqual(status, 200)
        self.assertTrue(settings["storage_path"].endswith("uploads"))
        status, saved = self.request("/api/settings", "POST", {
            "microphone_id": "test-device",
            "microphone_label": "测试会议麦克风",
            "sample_rate": "48000",
        })
        self.assertEqual(status, 200)
        self.assertEqual(saved["microphone_label"], "测试会议麦克风")


if __name__ == "__main__":
    unittest.main(verbosity=2)
