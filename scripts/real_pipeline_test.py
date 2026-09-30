#!/usr/bin/env python3
"""Exercise the running app with real audio and real local model services."""

import json
import os
import urllib.request
import uuid
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
BASE_URL = os.environ.get("PREOP_BASE_URL", "http://127.0.0.1:8765").rstrip("/")
AUDIO_PATH = Path(os.environ.get("PREOP_TEST_AUDIO", ROOT_DIR / "tests/fixtures/two-speaker-preop.wav"))


def json_request(path, method="GET", payload=None):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        BASE_URL + path,
        data=body,
        headers={"Content-Type": "application/json"} if body else {},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def upload(meeting_id):
    boundary = "----PreopReal{}".format(uuid.uuid4().hex)
    body = b"".join([
        ("--{}\r\n".format(boundary)).encode(),
        ('Content-Disposition: form-data; name="audio"; filename="{}"\r\n'.format(AUDIO_PATH.name)).encode(),
        b"Content-Type: audio/wav\r\n\r\n",
        AUDIO_PATH.read_bytes(),
        b"\r\n",
        ("--{}--\r\n".format(boundary)).encode(),
    ])
    request = urllib.request.Request(
        BASE_URL + "/api/meetings/{}/upload".format(meeting_id),
        data=body,
        headers={"Content-Type": "multipart/form-data; boundary={}".format(boundary)},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    health = json_request("/api/health")
    if health.get("model", {}).get("state") != "ready":
        raise SystemExit("ASR模型未就绪：{}".format(health.get("model")))
    meeting = json_request("/api/meetings", "POST", {
        "meeting_date": "2026-08-05",
        "patient_code": "LOCAL-E2E-001",
        "surgery_name": "腹腔镜胆囊切除术",
        "surgery_site": "腹部",
        "department": "普外科",
        "expected_speaker_min": 2,
        "expected_speaker_max": 2,
        "patient_history": "患者长期服用阿司匹林，需核对停药时机。",
    })
    upload(meeting["id"])
    processed = json_request("/api/meetings/{}/process".format(meeting["id"]), "POST", {})
    transcript = "".join(item.get("corrected_text", "") for item in processed.get("segments", []))
    if "胆囊" not in transcript or "阿司匹林" not in transcript:
        raise SystemExit("真实转写未通过关键词验证：{}".format(transcript))
    if processed.get("processing", {}).get("asr_backend") != "local-sensevoice-campp":
        raise SystemExit("ASR后端不是真实本地服务")
    if not processed.get("report"):
        raise SystemExit("未生成结构化报告")
    print(json.dumps({
        "meeting_id": meeting["id"],
        "asr_backend": processed["processing"]["asr_backend"],
        "llm_backend": processed["processing"]["llm_backend"],
        "segments": len(processed["segments"]),
        "speakers": sorted({item["speaker_id"] for item in processed["segments"]}),
        "transcript": transcript,
        "alerts": len(processed.get("alerts", [])),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
