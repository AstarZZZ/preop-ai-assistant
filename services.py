"""Audio, diarization, rule analysis and optional local-LLM services."""

import json
import os
import re
import urllib.error
import urllib.request
import uuid

from prompts import PROMPT_VERSION, REPORT_TASK_TEMPLATE, SYSTEM_PROMPT


DISCLAIMER = (
    "本系统为医疗机构内部使用的术前讨论记录整理、信息核对与辅助提示工具。"
    "AI生成内容可能存在识别错误、信息遗漏或理解偏差，仅供具备相应资质的医务人员参考；"
    "不构成诊断、治疗、麻醉或手术决策，不替代临床判断、会诊意见、知情同意程序及现行制度，"
    "也不得作为医疗责任认定或具有法律效力结论的独立依据。所有重要信息须经医务人员核对确认。"
)


def split_sentences(text):
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return []
    parts = re.split(r"(?<=[。！？!?；;])\s*|\n+", cleaned)
    return [part.strip() for part in parts if part.strip()]


class DeterministicTestASRBackend:
    """A deterministic stub available only to the automated test process."""

    name = "test-stub"

    def transcribe(self, audio_path, transcript_hint, expected_speakers, hotwords=""):
        sentences = split_sentences(transcript_hint)
        if not sentences:
            raise ValueError("测试转写文本不能为空")
        speaker_count = max(1, min(int(expected_speakers or 2), 8))
        segments = []
        cursor = 0
        for index, sentence in enumerate(sentences):
            duration = max(1800, min(15000, len(sentence) * 240))
            segments.append(
                {
                    "id": str(uuid.uuid4()),
                    "start_ms": cursor,
                    "end_ms": cursor + duration,
                    "speaker_id": "speaker_{}".format((index % speaker_count) + 1),
                    "speaker_role": "",
                    "text": sentence,
                    "corrected_text": sentence,
                    "overlap": False,
                    "review_status": "unreviewed",
                }
            )
            cursor += duration + 350
        return segments


class RemoteASRBackend:
    """Client for the isolated, always-real local ASR service."""

    name = "local-sensevoice-campp"

    def __init__(self):
        self.base_url = os.environ.get("PREOP_ASR_URL", "http://127.0.0.1:8766").rstrip("/")

    def transcribe(self, audio_path, transcript_hint, expected_speakers, hotwords=""):
        if not audio_path or not os.path.exists(audio_path):
            raise ValueError("真实语音识别需要先上传音频文件")
        boundary = "----PreopASR{}".format(uuid.uuid4().hex)
        filename = os.path.basename(audio_path)
        with open(audio_path, "rb") as handle:
            audio = handle.read()
        body = b"".join([
            ("--{}\r\n".format(boundary)).encode(),
            ('Content-Disposition: form-data; name="audio"; filename="{}"\r\n'.format(filename)).encode(),
            b"Content-Type: application/octet-stream\r\n\r\n",
            audio,
            b"\r\n",
            ("--{}\r\n".format(boundary)).encode(),
            b'Content-Disposition: form-data; name="expected_speakers"\r\n\r\n',
            str(max(1, min(int(expected_speakers or 2), 8))).encode(),
            b"\r\n",
            ("--{}\r\n".format(boundary)).encode(),
            b'Content-Disposition: form-data; name="hotwords"\r\n\r\n',
            (hotwords or "").encode("utf-8"),
            b"\r\n",
            ("--{}--\r\n".format(boundary)).encode(),
        ])
        request = urllib.request.Request(
            self.base_url + "/v1/transcribe",
            data=body,
            headers={"Content-Type": "multipart/form-data; boundary={}".format(boundary)},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=int(os.environ.get("PREOP_ASR_TIMEOUT", "900"))) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError("本地ASR服务识别失败：{}".format(detail[:500])) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError("本地ASR服务不可用，请先启动模型服务") from exc
        segments = payload.get("segments") or []
        if not segments:
            raise RuntimeError("真实识别结果中没有可用语音")
        for segment in segments:
            segment.setdefault("id", str(uuid.uuid4()))
            segment.setdefault("speaker_role", "")
            segment.setdefault("corrected_text", segment.get("text", ""))
            segment.setdefault("overlap", False)
            segment.setdefault("review_status", "unreviewed")
        return segments


def get_asr_backend():
    backend = os.environ.get("PREOP_ASR_BACKEND", "remote").strip().lower()
    if backend == "test" and os.environ.get("PREOP_TESTING") == "1":
        return DeterministicTestASRBackend()
    if backend != "remote":
        raise RuntimeError("无效的ASR后端配置；生产环境只允许 remote")
    return RemoteASRBackend()


def get_model_status():
    backend = os.environ.get("PREOP_ASR_BACKEND", "remote").strip().lower()
    if backend == "test" and os.environ.get("PREOP_TESTING") == "1":
        return {"state": "ready", "backend": "test-stub", "testing": True}
    base_url = os.environ.get("PREOP_ASR_URL", "http://127.0.0.1:8766").rstrip("/")
    try:
        with urllib.request.urlopen(base_url + "/health", timeout=2) as response:
            status = json.loads(response.read().decode("utf-8"))
        if status.get("state") != "ready":
            status.setdefault("state", "unavailable")
        return status
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return {
            "state": "unavailable",
            "backend": "local-sensevoice-campp",
            "endpoint": base_url,
            "detail": str(exc),
        }


def get_llm_status():
    base_url = os.environ.get("PREOP_LLM_URL", "").strip().rstrip("/")
    model = os.environ.get("PREOP_LLM_MODEL", "qwen3:4b")
    if not base_url:
        return {"state": "unconfigured", "backend": "deterministic-template", "model": ""}
    models_url = base_url + "/models" if base_url.endswith("/v1") else base_url + "/v1/models"
    try:
        with urllib.request.urlopen(models_url, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        available = [item.get("id", "") for item in (payload.get("data") or [])]
        return {
            "state": "ready" if model in available else "missing_model",
            "backend": "local-openai-compatible",
            "model": model,
            "available_models": available,
        }
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return {"state": "unavailable", "backend": "local-openai-compatible", "model": model, "detail": str(exc)}


def _rule_applies_to_surgery(rule, surgery_name):
    keywords = rule.get("surgery_keywords") or []
    return not keywords or any(term.lower() in (surgery_name or "").lower() for term in keywords)


def _matched_terms(text, terms):
    lowered = (text or "").lower()
    return [term for term in terms if term.lower() in lowered]


def _patient_evidence(patient, terms):
    evidence = []
    for term in _matched_terms(patient, terms):
        index = patient.lower().find(term.lower())
        start = max(0, index - 28)
        end = min(len(patient), index + len(term) + 42)
        evidence.append({
            "source": "patient_history",
            "matched_term": term,
            "excerpt": patient[start:end].strip(),
        })
    return evidence


def _segment_evidence(segments, terms):
    evidence = []
    for item in segments:
        text = item.get("corrected_text") or item.get("original_text", "")
        matches = _matched_terms(text, terms)
        if matches:
            evidence.append({
                "segment_id": item.get("id", ""),
                "start_ms": item.get("start_ms", 0),
                "speaker": item.get("speaker_role") or item.get("speaker_id", ""),
                "matched_terms": matches,
                "text": text,
            })
    return evidence


def evaluate_rules(meeting, segments, rules):
    transcript = "\n".join((item.get("corrected_text") or item.get("original_text") or "") for item in segments)
    patient = meeting.get("patient_history", "") or ""
    alerts = []
    for rule in rules:
        if not rule.get("enabled") or not _rule_applies_to_surgery(rule, meeting.get("surgery_name", "")):
            continue
        rule_type = rule.get("rule_type")
        triggered = False
        patient_evidence = []
        meeting_evidence = []
        required = rule.get("required_terms") or []
        triggers = rule.get("trigger_terms") or []
        if rule_type == "required_discussion":
            triggered = bool(required) and not _matched_terms(transcript, required)
        elif rule_type == "conditional_term":
            patient_evidence = _patient_evidence(patient, triggers)
            triggered = bool(patient_evidence) and not _matched_terms(transcript, required)
        elif rule_type == "contraindication_term":
            patient_evidence = _patient_evidence(patient, triggers)
            # A keyword match can only request clinical review; it must never assert a diagnosis.
            triggered = bool(patient_evidence)
        elif rule_type == "patient_data_required":
            triggered = not patient.strip()
        if triggered:
            meeting_evidence = _segment_evidence(segments, triggers + required)
            alerts.append(
                {
                    "rule_id": rule["id"],
                    "severity": rule.get("severity", "warning"),
                    "status": "requires_review",
                    "title": rule.get("name", "待核对事项"),
                    "message": rule.get("message", "请人工核对。"),
                    "patient_evidence": patient_evidence,
                    "meeting_evidence": meeting_evidence,
                    "knowledge_evidence": [{
                        "rule_id": rule.get("id", ""),
                        "name": rule.get("name", ""),
                        "category": rule.get("category", ""),
                        "source": rule.get("source", ""),
                        "version": rule.get("version", ""),
                        "updated_at": rule.get("updated_at", ""),
                    }],
                }
            )
    return alerts


def build_rule_comparison_items(meeting, segments, rules):
    """Turn deterministic knowledge rules into traceable report comparison rows."""
    patient = meeting.get("patient_history", "") or ""
    items = []
    for rule in rules:
        if not rule.get("enabled") or not _rule_applies_to_surgery(rule, meeting.get("surgery_name", "")):
            continue
        rule_type = rule.get("rule_type")
        required = rule.get("required_terms") or []
        triggers = rule.get("trigger_terms") or []
        patient_matches = _patient_evidence(patient, triggers)
        if rule_type == "patient_data_required":
            continue
        if rule_type in {"conditional_term", "contraindication_term"} and not patient_matches:
            continue
        evidence_terms = required or triggers
        evidence = _segment_evidence(segments, evidence_terms)
        items.append({
            "item": rule.get("name", "知识规则核对"),
            "status": "discussed" if evidence else "not_found",
            "evidence": evidence[:5],
            "patient_evidence": patient_matches[:5],
            "rule_id": rule.get("id", ""),
            "category": rule.get("category", ""),
            "source": rule.get("source", ""),
            "version": rule.get("version", ""),
        })
    return items


def merge_rule_comparisons(report, rule_items):
    comparison = list(report.get("comparison_items") or [])
    by_rule = {item.get("rule_id"): index for index, item in enumerate(comparison) if item.get("rule_id")}
    by_name = {item.get("item"): index for index, item in enumerate(comparison)}
    for item in rule_items:
        index = by_rule.get(item.get("rule_id"), by_name.get(item.get("item")))
        if index is None:
            comparison.append(item)
        else:
            comparison[index] = item
    report["comparison_items"] = comparison
    missing = list(report.get("missing_information") or [])
    for item in rule_items:
        text = "未在转写中找到{}相关内容，需人工核对。".format(item["item"])
        if item["status"] == "not_found" and text not in missing:
            missing.append(text)
    report["missing_information"] = missing
    return report


DISCUSSION_ITEMS = [
    ("手术指征", ["手术指征", "适应证", "手术目的"]),
    ("麻醉风险", ["麻醉", "气道", "ASA"]),
    ("过敏史", ["过敏"]),
    ("用药与抗凝", ["用药", "抗凝", "华法林", "阿司匹林", "停药"]),
    ("检查与影像", ["检查", "检验", "CT", "磁共振", "超声", "影像"]),
    ("并发症风险", ["并发症", "出血", "感染", "风险"]),
    ("术后计划", ["术后", "恢复", "监护", "复查"]),
]


def build_deterministic_report(meeting, segments, alerts):
    transcript = "".join((item.get("corrected_text") or item.get("original_text") or "") for item in segments)
    patient_sentences = split_sentences(meeting.get("patient_history", ""))
    transcript_sentences = split_sentences(transcript)
    comparison = []
    missing = []
    for item_name, terms in DISCUSSION_ITEMS:
        evidence = []
        for segment in segments:
            text = segment.get("corrected_text") or segment.get("original_text", "")
            if any(term.lower() in text.lower() for term in terms):
                evidence.append({
                    "segment_id": segment["id"],
                    "start_ms": segment["start_ms"],
                    "speaker": segment.get("speaker_role") or segment.get("speaker_id"),
                    "text": text,
                })
        status = "discussed" if evidence else "not_found"
        if not evidence:
            missing.append("未在转写中找到{}相关内容，需人工核对。".format(item_name))
        comparison.append({"item": item_name, "status": status, "evidence": evidence[:3]})

    key_points = []
    for segment in segments:
        text = segment.get("corrected_text") or segment.get("original_text", "")
        if text and text not in key_points:
            key_points.append(text)
        if len(key_points) >= 6:
            break
    patient_summary = "；".join(patient_sentences[:8]) if patient_sentences else "未录入患者历史资料，无法生成患者摘要。"
    discussion_summary = "；".join(transcript_sentences[:8]) if transcript_sentences else "尚无可用的讨论转写。"
    conclusion = (
        "本次讨论围绕{}形成了可供复核的记录，共识别{}名讲话人、{}条发言，系统产生{}条待核对提示。"
        "最终结论需由医务人员确认。"
    ).format(
        meeting.get("surgery_name", "拟行手术"),
        len({item.get("speaker_id") for item in segments}), len(segments), len(alerts),
    )
    return {
        "patient_summary": patient_summary,
        "discussion_summary": discussion_summary,
        "key_points": key_points,
        "comparison_items": comparison,
        "discussion_conclusion": conclusion,
        "missing_information": missing,
        "disclaimer": DISCLAIMER,
    }


def _validate_llm_report(data):
    required = {
        "patient_summary": str,
        "discussion_summary": str,
        "key_points": list,
        "comparison_items": list,
        "discussion_conclusion": str,
        "missing_information": list,
    }
    if not isinstance(data, dict):
        return False
    for key, expected_type in required.items():
        if key not in data or not isinstance(data[key], expected_type):
            return False
    if len(data["key_points"]) > 6:
        return False
    if not all(isinstance(item, str) for item in data["key_points"] + data["missing_information"]):
        return False
    for item in data["comparison_items"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("item"), str)
            or item.get("status") not in {"discussed", "not_found", "uncertain"}
            or not isinstance(item.get("evidence"), list)
        ):
            return False
        if item["status"] == "discussed" and not item["evidence"]:
            return False
        for evidence in item["evidence"]:
            if not isinstance(evidence, dict) or not isinstance(evidence.get("text"), str):
                return False
    if not data["discussion_conclusion"].endswith("最终结论需由医务人员确认"):
        return False
    return True


def _normalize_medical_term_typography(data, source_text):
    terms = {term for _name, values in DISCUSSION_ITEMS for term in values if len(term) >= 3}

    def normalize(value):
        if isinstance(value, str):
            value = re.sub(r"([\u4e00-\u9fff])\s*[:：]\s*\1", r"\1", value)
            for term in terms:
                if term not in source_text:
                    continue
                pattern = "[\\s:：·]*".join(re.escape(char) for char in term)
                value = re.sub(pattern, term, value, flags=re.I)
            return value
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        return value

    return normalize(data)


def _extract_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型未返回JSON对象")
    return json.loads(text[start:end + 1])


def call_local_llm(meeting, segments, alerts):
    base_url = os.environ.get("PREOP_LLM_URL", "").strip()
    if not base_url:
        return None, "deterministic-template"
    transcript_payload = [
        {
            "segment_id": item["id"],
            "start_ms": item["start_ms"],
            "end_ms": item["end_ms"],
            "speaker": item.get("speaker_role") or item["speaker_id"],
            "text": item.get("corrected_text") or item.get("original_text", ""),
        }
        for item in segments
    ]
    task = REPORT_TASK_TEMPLATE.format(
        meeting_json=json.dumps({
            "surgery_name": meeting.get("surgery_name"),
            "surgery_site": meeting.get("surgery_site"),
            "department": meeting.get("department"),
            "focus_questions": meeting.get("focus_questions"),
        }, ensure_ascii=False),
        patient_history=meeting.get("patient_history", ""),
        transcript_json=json.dumps(transcript_payload, ensure_ascii=False),
        alerts_json=json.dumps(alerts, ensure_ascii=False),
    )
    payload = {
        "model": os.environ.get("PREOP_LLM_MODEL", "qwen3:4b"),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ],
        "temperature": 0,
        "max_tokens": 1800,
        "response_format": {"type": "json_object"},
    }
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    last_content = ""
    for attempt in range(2):
        request_payload = dict(payload)
        if attempt:
            request_payload["messages"] = payload["messages"] + [
                {"role": "assistant", "content": last_content[:12000]},
                {"role": "user", "content": "上一次输出未通过 JSON 结构校验。/no_think 请仅输出修正后的 JSON，不要解释。"},
            ]
        request = urllib.request.Request(
            url,
            data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                body = json.loads(response.read().decode("utf-8"))
            last_content = body["choices"][0]["message"]["content"]
            data = _extract_json(last_content)
            if _validate_llm_report(data):
                source_text = meeting.get("patient_history", "") + "".join(
                    item.get("corrected_text") or item.get("original_text", "") for item in segments
                )
                data = _normalize_medical_term_typography(data, source_text)
                data["disclaimer"] = DISCLAIMER
                return data, "local-qwen-schema-validated"
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError, json.JSONDecodeError):
            if attempt:
                return None, "local-llm-error-fallback"
    return None, "local-llm-schema-fallback"


def analyze_meeting(meeting, rules):
    segments = meeting.get("segments") or []
    alerts = evaluate_rules(meeting, segments, rules)
    llm_report, backend = call_local_llm(meeting, segments, alerts)
    report = llm_report or build_deterministic_report(meeting, segments, alerts)
    report = merge_rule_comparisons(report, build_rule_comparison_items(meeting, segments, rules))
    return report, alerts, backend, PROMPT_VERSION
