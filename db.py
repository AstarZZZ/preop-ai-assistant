"""SQLite persistence for the local pre-operative discussion prototype."""

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Database:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._migration_lock = threading.Lock()
        self.init_schema()

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def init_schema(self):
        with self._migration_lock, self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meetings (
                    id TEXT PRIMARY KEY,
                    meeting_no TEXT NOT NULL UNIQUE,
                    meeting_date TEXT NOT NULL,
                    patient_code TEXT NOT NULL,
                    surgery_name TEXT NOT NULL,
                    surgery_site TEXT DEFAULT '',
                    planned_surgery_date TEXT DEFAULT '',
                    department TEXT DEFAULT '',
                    expected_speaker_min INTEGER NOT NULL DEFAULT 2,
                    expected_speaker_max INTEGER NOT NULL DEFAULT 4,
                    focus_questions TEXT DEFAULT '',
                    patient_history TEXT DEFAULT '',
                    audio_filename TEXT DEFAULT '',
                    audio_original_name TEXT DEFAULT '',
                    transcript_hint TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft',
                    confirmed_by TEXT DEFAULT '',
                    confirmed_at TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS transcript_segments (
                    id TEXT PRIMARY KEY,
                    meeting_id TEXT NOT NULL,
                    sort_order INTEGER NOT NULL,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    speaker_id TEXT NOT NULL,
                    speaker_role TEXT DEFAULT '',
                    original_text TEXT NOT NULL,
                    corrected_text TEXT NOT NULL,
                    overlap INTEGER NOT NULL DEFAULT 0,
                    review_status TEXT NOT NULL DEFAULT 'unreviewed',
                    FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY,
                    meeting_id TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    patient_evidence TEXT DEFAULT '[]',
                    meeting_evidence TEXT DEFAULT '[]',
                    knowledge_evidence TEXT DEFAULT '[]',
                    clinician_comment TEXT DEFAULT '',
                    confirmed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS reports (
                    meeting_id TEXT PRIMARY KEY,
                    report_json TEXT NOT NULL,
                    model_backend TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    knowledge_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS knowledge_rules (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT '通用核对',
                    rule_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    surgery_keywords TEXT DEFAULT '[]',
                    trigger_terms TEXT DEFAULT '[]',
                    required_terms TEXT DEFAULT '[]',
                    message TEXT NOT NULL,
                    source TEXT DEFAULT '',
                    version TEXT NOT NULL DEFAULT 'local-1',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT '',
                    created_by TEXT NOT NULL DEFAULT 'local-user'
                );

                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meeting_id TEXT,
                    action TEXT NOT NULL,
                    detail TEXT DEFAULT '',
                    actor TEXT DEFAULT 'local-user',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_segments_meeting
                    ON transcript_segments(meeting_id, sort_order);
                CREATE INDEX IF NOT EXISTS idx_alerts_meeting
                    ON alerts(meeting_id, severity);
                CREATE INDEX IF NOT EXISTS idx_meetings_date
                    ON meetings(meeting_date DESC);
                """
            )
            self._ensure_column(conn, "knowledge_rules", "category", "TEXT NOT NULL DEFAULT '通用核对'")
            self._ensure_column(conn, "knowledge_rules", "updated_at", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "knowledge_rules", "created_by", "TEXT NOT NULL DEFAULT 'local-user'")
            conn.execute("UPDATE knowledge_rules SET updated_at = created_at WHERE updated_at = ''")
            self._seed_rules(conn)

    @staticmethod
    def _ensure_column(conn, table, column, definition):
        columns = {row["name"] for row in conn.execute("PRAGMA table_info({})".format(table))}
        if column not in columns:
            conn.execute("ALTER TABLE {} ADD COLUMN {} {}".format(table, column, definition))

    def _seed_rules(self, conn):
        existing = conn.execute("SELECT COUNT(*) AS count FROM knowledge_rules").fetchone()["count"]
        if existing:
            return
        rules = [
            {
                "id": "CHECK-INDICATION",
                "name": "手术指征讨论完整性",
                "rule_type": "required_discussion",
                "severity": "warning",
                "required_terms": ["手术指征", "手术目的", "适应证", "为什么做手术"],
                "message": "转写中未明确找到手术指征或手术目的，建议人工核对是否已充分讨论。",
                "source": "原型内置完整性检查（非临床禁忌规则）",
            },
            {
                "id": "CHECK-ALLERGY",
                "name": "过敏史核对",
                "rule_type": "required_discussion",
                "severity": "high",
                "required_terms": ["过敏", "无过敏", "药物过敏"],
                "message": "转写中未明确找到过敏史核对内容，需人工确认患者过敏信息。",
                "source": "原型内置完整性检查（需院方审核后使用）",
            },
            {
                "id": "CHECK-ANESTHESIA",
                "name": "麻醉风险讨论",
                "rule_type": "required_discussion",
                "severity": "high",
                "required_terms": ["麻醉", "气道", "ASA", "麻醉风险"],
                "message": "转写中未明确找到麻醉方式或麻醉风险讨论，建议相关人员复核。",
                "source": "原型内置完整性检查（需院方审核后使用）",
            },
            {
                "id": "CHECK-ANTICOAGULATION",
                "name": "抗凝/抗血小板用药讨论",
                "rule_type": "conditional_term",
                "severity": "high",
                "trigger_terms": ["抗凝", "华法林", "利伐沙班", "阿哌沙班", "阿司匹林", "氯吡格雷"],
                "required_terms": ["抗凝", "停药", "出血", "凝血", "桥接"],
                "message": "患者资料疑似涉及抗凝或抗血小板用药，但讨论转写中未找到相应围术期核对内容。",
                "source": "原型演示规则（不得替代院内规范）",
            },
            {
                "id": "CHECK-PATIENT-DATA",
                "name": "患者历史资料完整性",
                "rule_type": "patient_data_required",
                "severity": "warning",
                "message": "未录入患者历史资料，无法进行患者信息与知识规则比对。",
                "source": "系统完整性检查",
            },
        ]
        stamp = now_iso()
        for rule in rules:
            conn.execute(
                """
                INSERT INTO knowledge_rules
                (id, name, category, rule_type, severity, surgery_keywords, trigger_terms,
                 required_terms, message, source, version, enabled, created_at, updated_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, 'system')
                """,
                (
                    rule["id"], rule["name"], "原型内置检查", rule["rule_type"], rule["severity"],
                    json.dumps(rule.get("surgery_keywords", []), ensure_ascii=False),
                    json.dumps(rule.get("trigger_terms", []), ensure_ascii=False),
                    json.dumps(rule.get("required_terms", []), ensure_ascii=False),
                    rule["message"], rule.get("source", ""), "builtin-1", stamp, stamp,
                ),
            )

    def _meeting_number(self, meeting_date):
        compact = (meeting_date or datetime.now().strftime("%Y-%m-%d")).replace("-", "")
        with self.connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS count FROM meetings WHERE meeting_date = ?", (meeting_date,)
            ).fetchone()["count"]
        return "MTG-{}-{:02d}".format(compact, count + 1)

    def create_meeting(self, payload):
        meeting_id = str(uuid.uuid4())
        meeting_date = payload.get("meeting_date") or datetime.now().strftime("%Y-%m-%d")
        minimum = max(1, int(payload.get("expected_speaker_min", 2)))
        maximum = max(minimum, int(payload.get("expected_speaker_max", minimum)))
        stamp = now_iso()
        values = (
            meeting_id,
            self._meeting_number(meeting_date),
            meeting_date,
            payload.get("patient_code", "").strip(),
            payload.get("surgery_name", "").strip(),
            payload.get("surgery_site", "").strip(),
            payload.get("planned_surgery_date", "").strip(),
            payload.get("department", "").strip(),
            minimum,
            maximum,
            payload.get("focus_questions", "").strip(),
            payload.get("patient_history", "").strip(),
            stamp,
            stamp,
        )
        if not values[3] or not values[4]:
            raise ValueError("患者编号和手术名称为必填项")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO meetings
                (id, meeting_no, meeting_date, patient_code, surgery_name, surgery_site,
                 planned_surgery_date, department, expected_speaker_min,
                 expected_speaker_max, focus_questions, patient_history,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            self._audit(conn, meeting_id, "meeting_created", "创建术前讨论档案")
        return self.get_meeting(meeting_id)

    def list_meetings(self, query=""):
        sql = "SELECT * FROM meetings"
        params = []
        if query:
            sql += " WHERE meeting_no LIKE ? OR patient_code LIKE ? OR surgery_name LIKE ?"
            term = "%{}%".format(query)
            params = [term, term, term]
        sql += " ORDER BY meeting_date DESC, created_at DESC"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["alert_count"] = conn.execute(
                    "SELECT COUNT(*) AS count FROM alerts WHERE meeting_id = ?", (row["id"],)
                ).fetchone()["count"]
                item["segment_count"] = conn.execute(
                    "SELECT COUNT(*) AS count FROM transcript_segments WHERE meeting_id = ?", (row["id"],)
                ).fetchone()["count"]
                result.append(item)
            return result

    def get_meeting(self, meeting_id):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
            if not row:
                return None
            meeting = dict(row)
            meeting["segments"] = [dict(item) for item in conn.execute(
                "SELECT * FROM transcript_segments WHERE meeting_id = ? ORDER BY sort_order",
                (meeting_id,),
            ).fetchall()]
            meeting["alerts"] = [self._decode_alert(dict(item)) for item in conn.execute(
                "SELECT * FROM alerts WHERE meeting_id = ? ORDER BY CASE severity WHEN 'high' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END, created_at",
                (meeting_id,),
            ).fetchall()]
            report = conn.execute("SELECT * FROM reports WHERE meeting_id = ?", (meeting_id,)).fetchone()
            if report:
                report_data = dict(report)
                report_data["content"] = json.loads(report_data.pop("report_json"))
                meeting["report"] = report_data
            else:
                meeting["report"] = None
            meeting["audit_logs"] = [dict(item) for item in conn.execute(
                "SELECT * FROM audit_logs WHERE meeting_id = ? ORDER BY id DESC LIMIT 30",
                (meeting_id,),
            ).fetchall()]
            return meeting

    def update_meeting(self, meeting_id, payload):
        allowed = {
            "meeting_date", "patient_code", "surgery_name", "surgery_site",
            "planned_surgery_date", "department", "expected_speaker_min",
            "expected_speaker_max", "focus_questions", "patient_history",
        }
        updates = []
        values = []
        for key, value in payload.items():
            if key in allowed:
                updates.append("{} = ?".format(key))
                values.append(value)
        if not updates:
            return self.get_meeting(meeting_id)
        updates.append("updated_at = ?")
        values.append(now_iso())
        values.append(meeting_id)
        with self.connect() as conn:
            conn.execute("UPDATE meetings SET {} WHERE id = ?".format(", ".join(updates)), values)
            self._audit(conn, meeting_id, "meeting_updated", "更新讨论基础信息")
        return self.get_meeting(meeting_id)

    def set_audio(self, meeting_id, stored_name, original_name, transcript_hint=""):
        with self.connect() as conn:
            conn.execute(
                """UPDATE meetings SET audio_filename = ?, audio_original_name = ?,
                   transcript_hint = ?, status = 'uploaded', updated_at = ? WHERE id = ?""",
                (stored_name, original_name, transcript_hint, now_iso(), meeting_id),
            )
            self._audit(conn, meeting_id, "audio_uploaded", original_name or "仅录入测试转写")

    def replace_segments(self, meeting_id, segments):
        with self.connect() as conn:
            conn.execute("DELETE FROM transcript_segments WHERE meeting_id = ?", (meeting_id,))
            for index, segment in enumerate(segments):
                conn.execute(
                    """
                    INSERT INTO transcript_segments
                    (id, meeting_id, sort_order, start_ms, end_ms, speaker_id,
                     speaker_role, original_text, corrected_text, overlap, review_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        segment.get("id", str(uuid.uuid4())), meeting_id, index,
                        int(segment.get("start_ms", 0)), int(segment.get("end_ms", 0)),
                        segment.get("speaker_id", "speaker_unknown"),
                        segment.get("speaker_role", ""), segment.get("text", ""),
                        segment.get("corrected_text", segment.get("text", "")),
                        1 if segment.get("overlap") else 0,
                        segment.get("review_status", "unreviewed"),
                    ),
                )
            conn.execute(
                "UPDATE meetings SET status = 'transcribed', updated_at = ? WHERE id = ?",
                (now_iso(), meeting_id),
            )
            self._audit(conn, meeting_id, "transcription_completed", "生成{}条讲话人片段".format(len(segments)))

    def update_segment(self, segment_id, payload):
        allowed = {"speaker_role", "corrected_text", "overlap", "review_status"}
        updates = []
        values = []
        for key, value in payload.items():
            if key in allowed:
                updates.append("{} = ?".format(key))
                values.append(1 if key == "overlap" and value else value)
        if not updates:
            raise ValueError("没有可更新的字段")
        values.append(segment_id)
        with self.connect() as conn:
            row = conn.execute("SELECT meeting_id FROM transcript_segments WHERE id = ?", (segment_id,)).fetchone()
            if not row:
                return None
            conn.execute("UPDATE transcript_segments SET {} WHERE id = ?".format(", ".join(updates)), values)
            conn.execute("UPDATE meetings SET status = 'reviewing', updated_at = ? WHERE id = ?", (now_iso(), row["meeting_id"]))
            self._audit(conn, row["meeting_id"], "segment_reviewed", segment_id)
            return dict(conn.execute("SELECT * FROM transcript_segments WHERE id = ?", (segment_id,)).fetchone())

    def replace_analysis(self, meeting_id, report, alerts, model_backend, prompt_version, knowledge_version=None):
        stamp = now_iso()
        knowledge_version = knowledge_version or self.knowledge_version()
        with self.connect() as conn:
            conn.execute("DELETE FROM alerts WHERE meeting_id = ?", (meeting_id,))
            for alert in alerts:
                conn.execute(
                    """
                    INSERT INTO alerts
                    (id, meeting_id, rule_id, severity, status, title, message,
                     patient_evidence, meeting_evidence, knowledge_evidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()), meeting_id, alert["rule_id"], alert["severity"],
                        alert.get("status", "requires_review"), alert["title"], alert["message"],
                        json.dumps(alert.get("patient_evidence", []), ensure_ascii=False),
                        json.dumps(alert.get("meeting_evidence", []), ensure_ascii=False),
                        json.dumps(alert.get("knowledge_evidence", []), ensure_ascii=False), stamp,
                    ),
                )
            conn.execute(
                """
                INSERT INTO reports
                (meeting_id, report_json, model_backend, prompt_version, knowledge_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(meeting_id) DO UPDATE SET
                    report_json = excluded.report_json,
                    model_backend = excluded.model_backend,
                    prompt_version = excluded.prompt_version,
                    knowledge_version = excluded.knowledge_version,
                    updated_at = excluded.updated_at
                """,
                (
                    meeting_id, json.dumps(report, ensure_ascii=False), model_backend,
                    prompt_version, knowledge_version, stamp, stamp,
                ),
            )
            conn.execute("UPDATE meetings SET status = 'analyzed', updated_at = ? WHERE id = ?", (stamp, meeting_id))
            self._audit(conn, meeting_id, "analysis_completed", "生成报告和{}条提示".format(len(alerts)))

    def update_report(self, meeting_id, payload):
        allowed = {
            "patient_summary": str,
            "discussion_summary": str,
            "discussion_conclusion": str,
            "key_points": list,
            "missing_information": list,
        }
        with self.connect() as conn:
            row = conn.execute("SELECT report_json FROM reports WHERE meeting_id = ?", (meeting_id,)).fetchone()
            if not row:
                return None
            report = json.loads(row["report_json"])
            changed = []
            for key, expected_type in allowed.items():
                if key in payload:
                    if not isinstance(payload[key], expected_type):
                        raise ValueError("报告字段{}格式不正确".format(key))
                    report[key] = payload[key]
                    changed.append(key)
            if not changed:
                raise ValueError("没有可更新的报告字段")
            stamp = now_iso()
            conn.execute(
                "UPDATE reports SET report_json = ?, updated_at = ? WHERE meeting_id = ?",
                (json.dumps(report, ensure_ascii=False), stamp, meeting_id),
            )
            conn.execute(
                "UPDATE meetings SET status = 'reviewing', updated_at = ? WHERE id = ?",
                (stamp, meeting_id),
            )
            self._audit(conn, meeting_id, "report_reviewed", "人工修订：{}".format("、".join(changed)))
        return self.get_meeting(meeting_id)

    def confirm_meeting(self, meeting_id, actor):
        stamp = now_iso()
        with self.connect() as conn:
            conn.execute(
                "UPDATE meetings SET status = 'confirmed', confirmed_by = ?, confirmed_at = ?, updated_at = ? WHERE id = ?",
                (actor.strip(), stamp, stamp, meeting_id),
            )
            self._audit(conn, meeting_id, "meeting_confirmed", "由{}确认".format(actor.strip()), actor.strip())
        return self.get_meeting(meeting_id)

    def dashboard(self):
        with self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS count FROM meetings").fetchone()["count"]
            confirmed = conn.execute("SELECT COUNT(*) AS count FROM meetings WHERE status = 'confirmed'").fetchone()["count"]
            pending = conn.execute("SELECT COUNT(*) AS count FROM meetings WHERE status != 'confirmed'").fetchone()["count"]
            high_alerts = conn.execute("SELECT COUNT(*) AS count FROM alerts WHERE severity = 'high'").fetchone()["count"]
        return {
            "total": total,
            "confirmed": confirmed,
            "pending": pending,
            "high_alerts": high_alerts,
            "recent": self.list_meetings()[:6],
        }

    def get_settings(self):
        with self.connect() as conn:
            rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
            return {row["key"]: row["value"] for row in rows}

    def update_settings(self, payload):
        allowed = {"storage_path", "microphone_id", "microphone_label", "sample_rate"}
        stamp = now_iso()
        with self.connect() as conn:
            for key, value in payload.items():
                if key not in allowed:
                    continue
                conn.execute(
                    """
                    INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                    """,
                    (key, str(value or ""), stamp),
                )
            self._audit(conn, None, "settings_updated", "更新录音与存储设置")
        return self.get_settings()

    def list_rules(self):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_rules ORDER BY enabled DESC, updated_at DESC, created_at DESC, name"
            ).fetchall()
            return [self._decode_rule(dict(row)) for row in rows]

    def get_rule(self, rule_id):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM knowledge_rules WHERE id = ?", (rule_id,)).fetchone()
            return self._decode_rule(dict(row)) if row else None

    @staticmethod
    def _normalize_rule_terms(value):
        if isinstance(value, str):
            value = value.replace("，", ",").replace("、", ",").replace("\n", ",").split(",")
        if not isinstance(value, list):
            return []
        result = []
        for item in value:
            term = str(item or "").strip()
            if term and term not in result:
                result.append(term)
        return result[:100]

    def _validated_rule(self, payload, existing=None):
        data = dict(existing or {})
        data.update(payload or {})
        allowed_types = {"required_discussion", "conditional_term", "contraindication_term", "patient_data_required"}
        allowed_severity = {"high", "warning", "info"}
        data["name"] = str(data.get("name") or "").strip()
        data["message"] = str(data.get("message") or "").strip()
        data["source"] = str(data.get("source") or "").strip()
        data["category"] = str(data.get("category") or "通用核对").strip()[:40]
        data["version"] = str(data.get("version") or "local-1").strip()[:40]
        data["created_by"] = str(data.get("created_by") or "local-user").strip()[:80]
        data["rule_type"] = str(data.get("rule_type") or "required_discussion")
        data["severity"] = str(data.get("severity") or "warning")
        data["surgery_keywords"] = self._normalize_rule_terms(data.get("surgery_keywords"))
        data["trigger_terms"] = self._normalize_rule_terms(data.get("trigger_terms"))
        data["required_terms"] = self._normalize_rule_terms(data.get("required_terms"))
        data["enabled"] = bool(data.get("enabled", True))
        if not data["name"]:
            raise ValueError("知识条目名称不能为空")
        if data["rule_type"] not in allowed_types:
            raise ValueError("不支持的规则类型")
        if data["severity"] not in allowed_severity:
            raise ValueError("不支持的提示级别")
        if not data["message"]:
            raise ValueError("请填写触发后的人工复核提示")
        if not data["source"]:
            raise ValueError("请填写知识依据或来源")
        if data["rule_type"] == "required_discussion" and not data["required_terms"]:
            raise ValueError("讨论必填项至少需要一个覆盖关键词")
        if data["rule_type"] == "conditional_term" and (not data["trigger_terms"] or not data["required_terms"]):
            raise ValueError("条件性核对需要同时填写患者触发词和讨论覆盖词")
        if data["rule_type"] == "contraindication_term" and not data["trigger_terms"]:
            raise ValueError("疑似禁忌/高风险条件至少需要一个患者触发词")
        return data

    def validate_rule(self, payload, existing=None):
        """Validate and normalize a rule without persisting it."""
        return self._validated_rule(payload, existing)

    def create_rule(self, payload):
        data = self._validated_rule(payload)
        rule_id = payload.get("id") or "LOCAL-{}".format(uuid.uuid4().hex[:8].upper())
        if self.get_rule(rule_id):
            raise ValueError("知识条目编号已存在")
        stamp = now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_rules
                (id, name, category, rule_type, severity, surgery_keywords, trigger_terms,
                 required_terms, message, source, version, enabled, created_at, updated_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule_id, data["name"], data["category"], data["rule_type"], data["severity"],
                    json.dumps(data["surgery_keywords"], ensure_ascii=False),
                    json.dumps(data["trigger_terms"], ensure_ascii=False),
                    json.dumps(data["required_terms"], ensure_ascii=False),
                    data["message"], data["source"], data["version"], int(data["enabled"]),
                    stamp, stamp, data["created_by"],
                ),
            )
            self._audit(conn, None, "knowledge_rule_created", "{}：{}".format(rule_id, data["name"]))
        return self.get_rule(rule_id)

    def update_rule(self, rule_id, payload):
        existing = self.get_rule(rule_id)
        if not existing:
            return None
        data = self._validated_rule(payload, existing)
        stamp = now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE knowledge_rules SET
                    name = ?, category = ?, rule_type = ?, severity = ?, surgery_keywords = ?,
                    trigger_terms = ?, required_terms = ?, message = ?, source = ?, version = ?,
                    enabled = ?, updated_at = ?, created_by = ?
                WHERE id = ?
                """,
                (
                    data["name"], data["category"], data["rule_type"], data["severity"],
                    json.dumps(data["surgery_keywords"], ensure_ascii=False),
                    json.dumps(data["trigger_terms"], ensure_ascii=False),
                    json.dumps(data["required_terms"], ensure_ascii=False),
                    data["message"], data["source"], data["version"], int(data["enabled"]),
                    stamp, data["created_by"], rule_id,
                ),
            )
            self._audit(conn, None, "knowledge_rule_updated", "{}：{}".format(rule_id, data["name"]))
        return self.get_rule(rule_id)

    def delete_rule(self, rule_id):
        if rule_id.startswith("CHECK-"):
            raise ValueError("内置检查规则不可删除")
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM knowledge_rules WHERE id = ?", (rule_id,))
            if cursor.rowcount:
                self._audit(conn, None, "knowledge_rule_deleted", rule_id)
            return cursor.rowcount > 0

    def knowledge_version(self):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count, MAX(updated_at) AS updated_at FROM knowledge_rules WHERE enabled = 1"
            ).fetchone()
        stamp = (row["updated_at"] or "empty").replace(":", "").replace("-", "")
        return "local-kb-{}-{}".format(row["count"], stamp)

    def knowledge_summary(self):
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END) AS enabled,
                       SUM(CASE WHEN severity = 'high' THEN 1 ELSE 0 END) AS high,
                       SUM(CASE WHEN id NOT LIKE 'CHECK-%' THEN 1 ELSE 0 END) AS custom
                FROM knowledge_rules
                """
            ).fetchone()
            categories = [item["category"] for item in conn.execute(
                "SELECT DISTINCT category FROM knowledge_rules WHERE category != '' ORDER BY category"
            ).fetchall()]
        return {
            "total": row["total"] or 0,
            "enabled": row["enabled"] or 0,
            "high": row["high"] or 0,
            "custom": row["custom"] or 0,
            "categories": categories,
            "version": self.knowledge_version(),
        }

    def import_rules(self, items, overwrite=False):
        if not isinstance(items, list) or not items:
            raise ValueError("导入文件中没有可用的知识条目")
        if len(items) > 500:
            raise ValueError("单次最多导入500条知识条目")
        result = {"created": 0, "updated": 0, "skipped": 0, "errors": [], "items": []}
        for index, raw in enumerate(items):
            if not isinstance(raw, dict):
                result["errors"].append({"index": index, "message": "条目必须是JSON对象"})
                continue
            payload = dict(raw)
            requested_id = str(payload.get("id") or "").strip()
            existing = self.get_rule(requested_id) if requested_id else None
            try:
                if existing and overwrite:
                    item = self.update_rule(requested_id, payload)
                    result["updated"] += 1
                elif existing:
                    payload.pop("id", None)
                    item = self.create_rule(payload)
                    result["created"] += 1
                else:
                    item = self.create_rule(payload)
                    result["created"] += 1
                result["items"].append(item)
            except ValueError as exc:
                result["errors"].append({"index": index, "id": requested_id, "message": str(exc)})
        result["skipped"] = len(result["errors"])
        return result

    def _audit(self, conn, meeting_id, action, detail="", actor="local-user"):
        conn.execute(
            "INSERT INTO audit_logs (meeting_id, action, detail, actor, created_at) VALUES (?, ?, ?, ?, ?)",
            (meeting_id, action, detail, actor or "local-user", now_iso()),
        )

    @staticmethod
    def _decode_rule(rule):
        for key in ("surgery_keywords", "trigger_terms", "required_terms"):
            rule[key] = json.loads(rule.get(key) or "[]")
        rule["enabled"] = bool(rule["enabled"])
        return rule

    @staticmethod
    def _decode_alert(alert):
        for key in ("patient_evidence", "meeting_evidence", "knowledge_evidence"):
            alert[key] = json.loads(alert.get(key) or "[]")
        alert["confirmed"] = bool(alert["confirmed"])
        return alert
