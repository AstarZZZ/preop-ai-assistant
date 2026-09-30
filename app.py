#!/usr/bin/env python3
"""Zero-dependency local web server for the pre-operative discussion prototype."""

import argparse
import cgi
import json
import mimetypes
import os
import re
import shutil
import sys
import tempfile
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from db import Database
from services import (
    DISCLAIMER, analyze_meeting, build_rule_comparison_items, evaluate_rules,
    get_asr_backend, get_llm_status, get_model_status,
)


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(ROOT_DIR, "static")
DEFAULT_DB = os.environ.get("PREOP_DB_PATH", os.path.join(ROOT_DIR, "data", "preop.db"))
DEFAULT_UPLOADS = os.environ.get("PREOP_UPLOAD_DIR", os.path.join(ROOT_DIR, "data", "uploads"))
MAX_UPLOAD_BYTES = 512 * 1024 * 1024


def safe_filename(filename):
    base = os.path.basename(filename or "audio.wav")
    cleaned = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", base, flags=re.UNICODE).strip("._")
    return cleaned or "audio.wav"


class PreopHandler(BaseHTTPRequestHandler):
    db = None
    upload_dir = None
    server_version = "PreopAssistant/0.3"

    def _upload_root(self):
        configured = self.db.get_settings().get("storage_path", "").strip()
        root = os.path.abspath(os.path.expanduser(configured)) if configured else os.path.abspath(self.upload_dir)
        os.makedirs(root, exist_ok=True)
        return root

    def log_message(self, fmt, *args):
        if os.environ.get("PREOP_QUIET") != "1":
            super().log_message(fmt, *args)

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=None).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status, message, detail=""):
        self._send_json({"error": message, "detail": detail}, status)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 2 * 1024 * 1024:
            raise ValueError("JSON请求过大")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _serve_file(self, path, cache=False):
        if not os.path.isfile(path):
            self.send_error(404)
            return
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as handle:
            body = handle.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=3600" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _meeting_or_404(self, meeting_id):
        meeting = self.db.get_meeting(meeting_id)
        if not meeting:
            self._send_error_json(404, "未找到讨论记录")
            return None
        if meeting.get("audio_filename"):
            meeting["audio_url"] = "/media/{}/{}".format(meeting_id, meeting["audio_filename"])
        else:
            meeting["audio_url"] = ""
        return meeting

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        try:
            if path == "/" or path == "/index.html":
                return self._serve_file(os.path.join(STATIC_DIR, "index.html"))
            if path.startswith("/static/"):
                relative = os.path.normpath(path[len("/static/"):]).lstrip("/")
                target = os.path.abspath(os.path.join(STATIC_DIR, relative))
                if not target.startswith(os.path.abspath(STATIC_DIR) + os.sep):
                    return self.send_error(403)
                return self._serve_file(target, cache=True)
            if path == "/assets/hospital-logo.png":
                return self._serve_file(os.path.join(ROOT_DIR, "东阳市人民医院logo.png"), cache=True)
            if path == "/assets/university-logo.png":
                return self._serve_file(os.path.join(ROOT_DIR, "杭州电子科技大学logo.png"), cache=True)
            if path.startswith("/media/"):
                parts = path.strip("/").split("/", 2)
                if len(parts) != 3:
                    return self.send_error(404)
                meeting_id, filename = parts[1], safe_filename(parts[2])
                target = os.path.abspath(os.path.join(self._upload_root(), meeting_id, filename))
                base = os.path.abspath(os.path.join(self._upload_root(), meeting_id))
                if not target.startswith(base + os.sep):
                    return self.send_error(403)
                return self._serve_file(target)

            if path == "/api/health":
                return self._send_json({
                    "status": "ok",
                    "version": "0.3.0",
                    "asr_backend": get_asr_backend().name,
                    "llm_backend": "local-openai-compatible" if os.environ.get("PREOP_LLM_URL") else "deterministic-template",
                    "database": self.db.path,
                    "model": get_model_status(),
                    "llm": get_llm_status(),
                    "knowledge": self.db.knowledge_summary(),
                    "disclaimer": DISCLAIMER,
                })
            if path == "/api/settings":
                settings = self.db.get_settings()
                settings.setdefault("storage_path", os.path.abspath(self.upload_dir))
                settings.setdefault("microphone_id", "default")
                settings.setdefault("microphone_label", "系统默认麦克风")
                settings.setdefault("sample_rate", "48000")
                settings["default_storage_path"] = os.path.abspath(self.upload_dir)
                return self._send_json(settings)
            if path == "/api/dashboard":
                return self._send_json(self.db.dashboard())
            if path == "/api/meetings":
                return self._send_json({"items": self.db.list_meetings((query.get("q") or [""])[0])})
            if path == "/api/rules":
                return self._send_json({
                    "items": self.db.list_rules(),
                    "summary": self.db.knowledge_summary(),
                })
            if path == "/api/rules/summary":
                return self._send_json(self.db.knowledge_summary())
            if path == "/api/rules/export":
                payload = {
                    "schema_version": "preop-knowledge-1",
                    "exported_at": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
                    "knowledge_version": self.db.knowledge_version(),
                    "items": self.db.list_rules(),
                }
                body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="preop-knowledge.json"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
            match = re.fullmatch(r"/api/rules/([^/]+)", path)
            if match:
                rule = self.db.get_rule(match.group(1))
                if not rule:
                    return self._send_error_json(404, "未找到知识条目")
                return self._send_json(rule)
            match = re.fullmatch(r"/api/meetings/([^/]+)", path)
            if match:
                meeting = self._meeting_or_404(match.group(1))
                if meeting:
                    return self._send_json(meeting)
                return
            match = re.fullmatch(r"/api/meetings/([^/]+)/export", path)
            if match:
                meeting = self._meeting_or_404(match.group(1))
                if not meeting:
                    return
                body = json.dumps(meeting, ensure_ascii=False, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="{}.json"'.format(meeting["meeting_no"]))
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
            return self._send_error_json(404, "接口不存在")
        except Exception as exc:
            self._handle_exception(exc)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path == "/api/meetings":
                meeting = self.db.create_meeting(self._read_json())
                return self._send_json(meeting, 201)
            if path == "/api/rules":
                return self._send_json(self.db.create_rule(self._read_json()), 201)
            if path == "/api/rules/import":
                payload = self._read_json()
                items = payload.get("items") if isinstance(payload, dict) else None
                return self._send_json(self.db.import_rules(items, bool(payload.get("overwrite"))))
            if path == "/api/rules/test":
                payload = self._read_json()
                rule = self.db.get_rule(str(payload.get("rule_id") or ""))
                if not rule:
                    draft = payload.get("rule")
                    if not isinstance(draft, dict):
                        return self._send_error_json(400, "请选择条目或提供待测试规则")
                    rule = self.db.validate_rule(draft)
                    rule["id"] = str(draft.get("id") or "DRAFT-RULE")
                    rule["updated_at"] = ""
                transcript = str(payload.get("transcript") or "").strip()
                segment = {
                    "id": "test-segment-1", "start_ms": 0, "end_ms": max(1000, len(transcript) * 200),
                    "speaker_id": "speaker_1", "speaker_role": "", "corrected_text": transcript,
                    "original_text": transcript,
                }
                meeting = {
                    "surgery_name": str(payload.get("surgery_name") or ""),
                    "patient_history": str(payload.get("patient_history") or ""),
                }
                alerts = evaluate_rules(meeting, [segment], [rule])
                comparisons = build_rule_comparison_items(meeting, [segment], [rule])
                return self._send_json({
                    "matched": bool(alerts),
                    "alerts": alerts,
                    "comparison_items": comparisons,
                    "explanation": "规则已触发，实际使用时将生成待人工复核提示。" if alerts else "当前测试资料未触发该规则。",
                })
            if path == "/api/settings":
                payload = self._read_json()
                if "storage_path" in payload:
                    candidate = os.path.abspath(os.path.expanduser(str(payload.get("storage_path") or self.upload_dir)))
                    os.makedirs(candidate, exist_ok=True)
                    try:
                        with tempfile.NamedTemporaryFile(prefix="preop-write-test-", dir=candidate, delete=True):
                            pass
                    except OSError as exc:
                        return self._send_error_json(400, "存储目录不可写", str(exc))
                    payload["storage_path"] = candidate
                settings = self.db.update_settings(payload)
                settings.setdefault("storage_path", os.path.abspath(self.upload_dir))
                settings["default_storage_path"] = os.path.abspath(self.upload_dir)
                return self._send_json(settings)

            match = re.fullmatch(r"/api/meetings/([^/]+)/upload", path)
            if match:
                return self._handle_upload(match.group(1))
            match = re.fullmatch(r"/api/meetings/([^/]+)/live-transcribe", path)
            if match:
                return self._handle_live_transcribe(match.group(1))
            match = re.fullmatch(r"/api/meetings/([^/]+)/process", path)
            if match:
                meeting_id = match.group(1)
                payload = self._read_json()
                meeting = self._meeting_or_404(meeting_id)
                if not meeting:
                    return
                hint = payload.get("transcript_hint", meeting.get("transcript_hint", ""))
                if hint != meeting.get("transcript_hint", ""):
                    self.db.set_audio(
                        meeting_id, meeting.get("audio_filename", ""),
                        meeting.get("audio_original_name", ""), hint,
                    )
                    meeting = self.db.get_meeting(meeting_id)
                audio_path = ""
                if meeting.get("audio_filename"):
                    audio_path = os.path.join(self._upload_root(), meeting_id, meeting["audio_filename"])
                backend = get_asr_backend()
                expected = meeting.get("expected_speaker_max") or meeting.get("expected_speaker_min") or 2
                hotwords = ",".join(filter(None, [
                    meeting.get("surgery_name", ""),
                    meeting.get("department", ""),
                    meeting.get("surgery_site", ""),
                ]))
                segments = backend.transcribe(audio_path, hint, expected, hotwords)
                self.db.replace_segments(meeting_id, segments)
                meeting = self.db.get_meeting(meeting_id)
                report, alerts, llm_backend, prompt_version = analyze_meeting(meeting, self.db.list_rules())
                self.db.replace_analysis(
                    meeting_id, report, alerts, llm_backend, prompt_version,
                    self.db.knowledge_version(),
                )
                result = self._meeting_or_404(meeting_id)
                result["processing"] = {"asr_backend": backend.name, "llm_backend": llm_backend}
                return self._send_json(result)
            match = re.fullmatch(r"/api/meetings/([^/]+)/reanalyze", path)
            if match:
                meeting = self._meeting_or_404(match.group(1))
                if not meeting:
                    return
                report, alerts, backend, prompt_version = analyze_meeting(meeting, self.db.list_rules())
                self.db.replace_analysis(
                    meeting["id"], report, alerts, backend, prompt_version,
                    self.db.knowledge_version(),
                )
                return self._send_json(self._meeting_or_404(meeting["id"]))
            match = re.fullmatch(r"/api/meetings/([^/]+)/confirm", path)
            if match:
                payload = self._read_json()
                actor = payload.get("actor", "").strip()
                if not actor:
                    return self._send_error_json(400, "确认人姓名不能为空")
                meeting = self._meeting_or_404(match.group(1))
                if not meeting:
                    return
                if not meeting.get("report"):
                    return self._send_error_json(409, "请先完成转写和分析")
                return self._send_json(self.db.confirm_meeting(match.group(1), actor))
            return self._send_error_json(404, "接口不存在")
        except ValueError as exc:
            self._send_error_json(400, str(exc))
        except Exception as exc:
            self._handle_exception(exc)

    def do_PUT(self):
        path = unquote(urlparse(self.path).path)
        try:
            match = re.fullmatch(r"/api/rules/([^/]+)", path)
            if match:
                result = self.db.update_rule(match.group(1), self._read_json())
                if not result:
                    return self._send_error_json(404, "未找到知识条目")
                return self._send_json(result)
            match = re.fullmatch(r"/api/segments/([^/]+)", path)
            if match:
                result = self.db.update_segment(match.group(1), self._read_json())
                if not result:
                    return self._send_error_json(404, "未找到转写片段")
                return self._send_json(result)
            match = re.fullmatch(r"/api/meetings/([^/]+)/report", path)
            if match:
                if not self.db.get_meeting(match.group(1)):
                    return self._send_error_json(404, "未找到讨论记录")
                result = self.db.update_report(match.group(1), self._read_json())
                if not result:
                    return self._send_error_json(409, "请先完成转写和分析")
                return self._send_json(result)
            match = re.fullmatch(r"/api/meetings/([^/]+)", path)
            if match:
                if not self.db.get_meeting(match.group(1)):
                    return self._send_error_json(404, "未找到讨论记录")
                return self._send_json(self.db.update_meeting(match.group(1), self._read_json()))
            return self._send_error_json(404, "接口不存在")
        except ValueError as exc:
            self._send_error_json(400, str(exc))
        except Exception as exc:
            self._handle_exception(exc)

    def do_DELETE(self):
        path = unquote(urlparse(self.path).path)
        try:
            match = re.fullmatch(r"/api/rules/([^/]+)", path)
            if match:
                deleted = self.db.delete_rule(match.group(1))
                if not deleted:
                    return self._send_error_json(404, "未找到知识规则")
                return self._send_json({"deleted": True})
            return self._send_error_json(404, "接口不存在")
        except ValueError as exc:
            self._send_error_json(400, str(exc))
        except Exception as exc:
            self._handle_exception(exc)

    def _handle_upload(self, meeting_id):
        meeting = self._meeting_or_404(meeting_id)
        if not meeting:
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > MAX_UPLOAD_BYTES:
            return self._send_error_json(413, "文件超过512MB限制")
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            return self._send_error_json(415, "请使用multipart/form-data上传")
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": str(length),
            },
        )
        hint = form.getfirst("transcript_hint", "")
        file_item = form["audio"] if "audio" in form else None
        stored_name = meeting.get("audio_filename", "")
        original_name = meeting.get("audio_original_name", "")
        if file_item is not None and getattr(file_item, "filename", ""):
            original_name = safe_filename(file_item.filename)
            extension = os.path.splitext(original_name)[1].lower() or ".wav"
            stored_name = "audio-{}{}".format(uuid.uuid4().hex[:10], extension)
            meeting_dir = os.path.join(self._upload_root(), meeting_id)
            os.makedirs(meeting_dir, exist_ok=True)
            target = os.path.join(meeting_dir, stored_name)
            with open(target, "wb") as output:
                shutil.copyfileobj(file_item.file, output)
        if not stored_name:
            return self._send_error_json(400, "请上传真实音频文件")
        self.db.set_audio(meeting_id, stored_name, original_name, hint)
        return self._send_json(self._meeting_or_404(meeting_id))

    def _handle_live_transcribe(self, meeting_id):
        meeting = self._meeting_or_404(meeting_id)
        if not meeting:
            return
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            return self._send_error_json(415, "请使用multipart/form-data上传录音片段")
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 96 * 1024 * 1024:
            return self._send_error_json(413, "实时识别片段过大")
        form = cgi.FieldStorage(
            fp=self.rfile, headers=self.headers,
            environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type, "CONTENT_LENGTH": str(length)},
        )
        hint = form.getfirst("transcript_hint", "")
        file_item = form["audio"] if "audio" in form else None
        suffix = ".webm"
        temp_path = ""
        try:
            if file_item is not None and getattr(file_item, "filename", ""):
                suffix = os.path.splitext(safe_filename(file_item.filename))[1] or suffix
                with tempfile.NamedTemporaryFile(prefix="preop-live-", suffix=suffix, delete=False) as output:
                    shutil.copyfileobj(file_item.file, output)
                    temp_path = output.name
            backend = get_asr_backend()
            expected = meeting.get("expected_speaker_max") or meeting.get("expected_speaker_min") or 2
            hotwords = ",".join(filter(None, [
                meeting.get("surgery_name", ""),
                meeting.get("department", ""),
                meeting.get("surgery_site", ""),
            ]))
            segments = backend.transcribe(temp_path, hint, expected, hotwords)
            return self._send_json({"segments": segments, "backend": backend.name, "partial": True})
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

    def _handle_exception(self, exc):
        if os.environ.get("PREOP_DEBUG") == "1":
            traceback.print_exc()
        self._send_error_json(500, "服务器处理失败", str(exc))


def build_server(host="127.0.0.1", port=8765, db_path=None, upload_dir=None):
    database = Database(db_path or DEFAULT_DB)
    uploads = os.path.abspath(upload_dir or DEFAULT_UPLOADS)
    os.makedirs(uploads, exist_ok=True)
    handler = type("ConfiguredPreopHandler", (PreopHandler,), {"db": database, "upload_dir": uploads})
    return ThreadingHTTPServer((host, port), handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description="本地术前讨论AI辅助原型")
    parser.add_argument("--host", default=os.environ.get("PREOP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PREOP_PORT", "8765")))
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--uploads", default=DEFAULT_UPLOADS)
    args = parser.parse_args(argv)
    server = build_server(args.host, args.port, args.db, args.uploads)
    print("术前讨论AI辅助原型已启动：http://{}:{}".format(args.host, server.server_port))
    print("当前ASR后端：{}".format(get_asr_backend().name))
    print("按 Ctrl+C 停止服务")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止服务……")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
