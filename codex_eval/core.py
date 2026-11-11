from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import time
import uuid
from decimal import Decimal
from pathlib import Path
from .models import COUNTERS, breakdown, counter_completeness, identity, sum_counters
from .checks import assessment
from .version import application

LIMIT = 128 * 1024
RETENTION = 30 * 86400
IDENTIFIER = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
TOOLS = {"shell", "file", "browser", "mcp", "weather", "unknown"}
REASONS = {"prompt_injection", "sensitive_data", "unapproved_origin", "inspection_error", "policy_mismatch"}
SAMPLE_CASES = {'desktop', 'multi', 'subagents', 'repair', 'blocked', 'partial'}


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError("Expected an explicit UUID identifier")
    return value


def new_id():
    return str(uuid.uuid4())


def integer(value):
    if type(value) is not int or not 0 <= value <= 10**15:
        raise ValueError("Invalid nonnegative counter")
    return value


def timestamp(value):
    if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
        raise ValueError("Invalid timestamp")
    return float(value)


def private_directory(path):
    path = Path(path).absolute()
    for parent in [*reversed(path.parents), path]:
        if parent.is_symlink():
            raise ValueError("Symlinked state paths are not supported")
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ValueError("State directory must be owned by this user with mode 0700")
    return path


def private_file(path):
    flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    info = os.fstat(descriptor)
    os.close(descriptor)
    if info.st_uid != os.getuid() or info.st_mode & 0o077 or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("State file must be owner-only")


def normalize(event):
    """Reject ambiguous accounting; discard content and unknown attributes."""
    result = {key: identifier(event[key]) for key in ("event_id", "thread_id", "execution_id")}
    result["occurred_at"] = timestamp(event["occurred_at"])
    kind = event.get("kind")
    if kind not in {"execution", "usage", "tool", "check", "security", "changes"}:
        raise ValueError("Unsupported event kind")
    result["kind"] = kind
    if kind == "execution":
        result["parent_id"] = identifier(event["parent_id"]) if event.get("parent_id") else None
        result["status"] = event.get("status")
        if result["status"] not in {"running", "completed", "failed", "interrupted"}:
            raise ValueError("Invalid execution status")
    elif kind == "usage":
        if event.get("scope") != "self" or event.get("mode") != "cumulative":
            raise ValueError("Only cumulative own-execution usage is supported; do not supply inclusive totals")
        result.update(scope="self", mode="cumulative")
        for key in ("input", "cached", "output", "reasoning"):
            result[key] = integer(event[key]) if event.get(key) is not None else None
        if result["input"] is not None and result["cached"] is not None and result["cached"] > result["input"]:
            raise ValueError("Cached input exceeds input")
        if result["output"] is not None and result["reasoning"] is not None and result["reasoning"] > result["output"]:
            raise ValueError("Reasoning exceeds output")
        result.update(identity(event))
        result['request_id'] = identifier(event['request_id']) if event.get('request_id') is not None else None
    elif kind == 'changes':
        if event.get('scope') != 'recording' or event.get('mode') != 'snapshot':
            raise ValueError('Line changes must be a recording-level net-diff snapshot')
        result.update(scope='recording', mode='snapshot', added=integer(event['added']), removed=integer(event['removed']))
    elif kind == "tool":
        result["tool"] = event.get("tool") if event.get("tool") in TOOLS else "unknown"
        result["status"] = event.get("status")
        if result["status"] not in {"completed", "failed"}:
            raise ValueError("Invalid tool status")
        result["duration_ms"] = integer(event["duration_ms"]) if event.get("duration_ms") is not None else None
    elif kind == "check":
        result.update(assessment(event))
    else:
        if event.get("action") not in {"allow", "block"}:
            raise ValueError("Invalid security decision")
        result["action"] = event["action"]
        result["reasons"] = sorted(set(event.get("reasons", [])) & REASONS)
        result["duration_ms"] = integer(event.get("duration_ms", 0))
        result["policy_digest"] = event.get("policy_digest")
        if not re.fullmatch(r"[0-9a-f]{64}", result["policy_digest"] or ""):
            raise ValueError("Invalid policy digest")
    return result


class Store:
    def __init__(self, state):
        self.state = private_directory(state)
        path = self.state / "metrics.sqlite3"
        private_file(path)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        if self.db.execute('PRAGMA user_version').fetchone()[0] not in (0,1):
            self.db.close()
            raise ValueError('Unsupported storage schema; no downgrade performed')
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, created REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS recordings(
            id TEXT PRIMARY KEY, task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
            thread_id TEXT NOT NULL, source TEXT NOT NULL, started REAL NOT NULL, finished REAL,
            gap INTEGER NOT NULL DEFAULT 0);
          CREATE UNIQUE INDEX IF NOT EXISTS one_active ON recordings((1)) WHERE finished IS NULL;
          CREATE TABLE IF NOT EXISTS events(
            event_id TEXT PRIMARY KEY, recording_id TEXT REFERENCES recordings(id) ON DELETE CASCADE,
            occurred REAL NOT NULL, data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS analyses(
            recording_id TEXT REFERENCES recordings(id) ON DELETE CASCADE,
            version INTEGER, digest TEXT, data TEXT, PRIMARY KEY(recording_id,version));
          CREATE TABLE IF NOT EXISTS sample_cases(
            recording_id TEXT PRIMARY KEY REFERENCES recordings(id) ON DELETE CASCADE,
            name TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS recording_builds(
            recording_id TEXT PRIMARY KEY REFERENCES recordings(id) ON DELETE CASCADE,
            data TEXT NOT NULL);
          PRAGMA user_version=1;
        """)
        self.purge()

    def close(self):
        self.db.close()

    def purge(self):
        cutoff = time.time() - RETENTION
        with self.db:
            self.db.execute("DELETE FROM recordings WHERE started < ?", (cutoff,))
            self.db.execute("DELETE FROM tasks WHERE NOT EXISTS(SELECT 1 FROM recordings WHERE task_id=tasks.id)")

    def start(self, thread_id, task_id=None, source="desktop-unverified", now=None, sample_case=None):
        identifier(thread_id)
        if source not in {"desktop-unverified", "controlled-simulation"}:
            raise ValueError("Unsupported source")
        if sample_case is not None and (sample_case not in SAMPLE_CASES or source != 'controlled-simulation'):
            raise ValueError('Only reviewed sample cases may be named')
        active = self.db.execute("SELECT * FROM recordings WHERE finished IS NULL").fetchone()
        if active:
            if active["thread_id"] == thread_id and (task_id is None or active["task_id"] == task_id):
                return dict(active)
            raise ValueError("Finish the active recording before switching")
        now = time.time() if now is None else timestamp(now)
        with self.db:
            if task_id:
                identifier(task_id)
                if not self.db.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone():
                    raise ValueError("Task does not exist")
            else:
                task_id = new_id()
                self.db.execute("INSERT INTO tasks VALUES (?,?)", (task_id, now))
            record = dict(id=new_id(), task_id=task_id, thread_id=thread_id, source=source, started=now, finished=None)
            self.db.execute("INSERT INTO recordings(id,task_id,thread_id,source,started,finished) VALUES (:id,:task_id,:thread_id,:source,:started,:finished)", record)
            self.db.execute('INSERT INTO recording_builds VALUES (?,?)', (record['id'], json.dumps(application(), sort_keys=True)))
            if sample_case is not None:
                self.db.execute('INSERT INTO sample_cases VALUES (?,?)', (record['id'], sample_case))
        return record

    def finish(self, now=None, thread_id=None):
        active = self.db.execute("SELECT id,thread_id FROM recordings WHERE finished IS NULL").fetchone()
        if not active:
            raise ValueError("No active recording")
        if thread_id is not None and active['thread_id'] != identifier(thread_id):
            raise ValueError("Active recording belongs to another chat")
        with self.db:
            self.db.execute("UPDATE recordings SET finished=? WHERE id=?", (time.time() if now is None else timestamp(now), active["id"]))
        return self.report(active["id"])

    def interrupt(self):
        with self.db:
            self.db.execute('UPDATE recordings SET finished=?,gap=1 WHERE finished IS NULL', (time.time(),))

    def ingest(self, payload):
        record_id = identifier(payload["recording_id"])
        record = self.recording(record_id)
        event = normalize(payload["event"])
        if event["thread_id"] != record["thread_id"]:
            raise ValueError("Event is not correlated to the selected chat")
        at = event["occurred_at"]
        if at < record["started"] or (record["finished"] is not None and at > record["finished"]) or at > time.time() + 5:
            raise ValueError("Event outside the recording boundary")
        data = json.dumps(event, sort_keys=True, separators=(",", ":"))
        old = self.db.execute("SELECT data FROM events WHERE event_id=?", (event["event_id"],)).fetchone()
        if old:
            if normalize(json.loads(old['data'])) != event:
                raise ValueError("Conflicting duplicate event")
            return False
        if event['kind'] == 'usage':
            mixed = self.db.execute("SELECT 1 FROM events WHERE recording_id=? AND json_extract(data,'$.kind')='usage' AND json_extract(data,'$.execution_id')=? AND ((json_extract(data,'$.request_id') IS NULL) != ?) LIMIT 1", (record_id, event['execution_id'], event['request_id'] is None)).fetchone()
            if mixed:
                raise ValueError('Do not mix per-call usage and whole-execution totals for one execution')
            if event['request_id'] is not None and self.db.execute("SELECT 1 FROM events WHERE recording_id=? AND json_extract(data,'$.kind')='usage' AND json_extract(data,'$.request_id')=? AND json_extract(data,'$.execution_id')!=? LIMIT 1", (record_id, event['request_id'], event['execution_id'])).fetchone():
                raise ValueError('One model call cannot belong to multiple executions')
            if event['fixture_profile'] and record['source'] != 'controlled-simulation':
                raise ValueError('Synthetic pricing is only valid for sample recordings')
        count = self.db.execute("SELECT count(*) FROM events WHERE recording_id=?", (record_id,)).fetchone()[0]
        if count >= 10000:
            raise ValueError("Recording event capacity reached; collection is incomplete")
        with self.db:
            self.db.execute("INSERT INTO events VALUES (?,?,?,?)", (event["event_id"], record_id, at, data))
        return True

    def recording(self, record_id):
        row = self.db.execute("SELECT * FROM recordings WHERE id=?", (identifier(record_id),)).fetchone()
        if not row:
            raise ValueError("Recording not found")
        return self.describe(dict(row))

    def describe(self, record):
        build = self.db.execute('SELECT data FROM recording_builds WHERE recording_id=?', (record['id'],)).fetchone()
        record['application'] = json.loads(build['data']) if build else None
        sample = self.db.execute('SELECT name FROM sample_cases WHERE recording_id=?', (record['id'],)).fetchone()
        record['sample_case'] = sample['name'] if sample else None
        record['number'] = self.db.execute('SELECT COUNT(*) FROM recordings WHERE task_id=? AND rowid <= (SELECT rowid FROM recordings WHERE id=?)', (record['task_id'], record['id'])).fetchone()[0]
        record['task_number'] = self.db.execute('SELECT rowid FROM tasks WHERE id=?', (record['task_id'],)).fetchone()[0]
        return record

    def list(self):
        self.purge()
        return [self.describe(dict(row)) for row in self.db.execute("SELECT * FROM recordings ORDER BY started DESC,rowid DESC LIMIT 200")]

    def latest_report(self, thread_id):
        self.purge()
        row = self.db.execute('SELECT id FROM recordings WHERE thread_id=? ORDER BY started DESC,rowid DESC LIMIT 1', (identifier(thread_id),)).fetchone()
        if not row:
            raise ValueError('No recording for this chat')
        return self.report(row['id'])

    def report(self, record_id):
        self.purge()
        record = self.recording(record_id)
        events = [json.loads(row[0]) for row in self.db.execute("SELECT data FROM events WHERE recording_id=? ORDER BY occurred,event_id", (record_id,))]
        report = analyze(record, events)
        serialized = json.dumps(report, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(serialized.encode()).hexdigest()
        last = self.db.execute("SELECT version,digest FROM analyses WHERE recording_id=? ORDER BY version DESC LIMIT 1", (record_id,)).fetchone()
        version = last["version"] if last else 0
        if not last or last["digest"] != digest:
            version += 1
            with self.db:
                self.db.execute("INSERT INTO analyses VALUES (?,?,?,?)", (record_id, version, digest, serialized))
        report["analysis_version"] = version
        attempts=[]
        for row in self.db.execute('SELECT * FROM recordings WHERE task_id=? ORDER BY started', (record['task_id'],)):
            attempt=dict(row)
            history=[json.loads(item[0]) for item in self.db.execute('SELECT data FROM events WHERE recording_id=? ORDER BY occurred,event_id',(attempt['id'],))]
            summary=analyze(attempt,history)
            attempts.append({'recording_id':attempt['id'],'outcome':summary['outcome'],'totals':summary['totals'],'coverage':summary['coverage'],'counter_complete':summary['counter_complete']})
        report['task_summary']={'attempts':attempts,'observed_totals':{k:sum(a['totals'][k] for a in attempts if a['totals'][k] is not None) if any(a['totals'][k] is not None for a in attempts) else None for k in ('input','cached','output','reasoning')},
                                'counter_complete':{k:all(a['counter_complete'][k] for a in attempts) for k in COUNTERS},
                                'comparison_note':'Same task does not establish equivalent prompts, settings, or check coverage.'}
        return report


def analyze(record, events):
    nodes, checks, security = {}, {}, []
    assessments = {}
    usage_buckets, ambiguous = {}, set()
    changes = {'added': None, 'removed': None}
    warnings = set()
    if record.get('gap'):
        warnings.add('Collector stopped or restarted; recording closed with a collection gap')
    for event in events:
        if event['kind'] == 'changes':
            changes = {k: event[k] for k in ('added', 'removed')}
            continue
        node = nodes.setdefault(event["execution_id"], dict(id=event["execution_id"], parent_id=None, status="unknown", usage=None, tools=0, failures=0, tool_ms=0, declared=False))
        kind = event["kind"]
        if kind == "execution":
            if node["declared"] and node["parent_id"] != event["parent_id"]:
                warnings.add("Conflicting execution parent")
            node.update(parent_id=event["parent_id"], status=event["status"], declared=True)
        elif kind == "usage":
            key = (event['execution_id'], event.get('request_id'))
            usage = {k: event[k] for k in COUNTERS} | identity(event)
            previous = usage_buckets.get(key)
            if previous:
                if any(usage[k] is not None and previous[k] is not None and usage[k] < previous[k] for k in COUNTERS):
                    warnings.add("Usage counter regressed; totals are incomplete")
                if any(previous[k] is not None and usage[k] is not None and previous[k] != usage[k] for k in ('provider', 'model', 'harness', 'fixture_profile', 'adapter')):
                    ambiguous.add(key)
                    warnings.add('Model identity changed inside cumulative usage; per-model attribution unavailable')
            usage_buckets[key] = usage
        elif kind == "tool":
            node["tools"] += 1
            node["failures"] += event["status"] == "failed"
            node["tool_ms"] += event["duration_ms"] or 0
        elif kind == "check":
            item = assessment(event) | {'execution_id': event['execution_id']}
            assessments[(event['execution_id'], item['grader'], item['check'])] = item
        else:
            security.append({k:event[k] for k in ("action", "reasons", "duration_ms", "policy_digest")})
    for key in ambiguous:
        usage_buckets[key].update(provider=None, model=None, model_source='unknown', fixture_profile=None)
    for node in nodes.values():
        usages = [u for (execution_id, _), u in usage_buckets.items() if execution_id == node['id']]
        node['models'] = breakdown(usages)
        if usages:
            node['usage'] = sum_counters(usages)
            node['counter_complete'] = counter_completeness(usages)
            for key in ('provider', 'model', 'harness', 'model_source', 'fixture_profile', 'adapter'):
                values = {u[key] for u in usages}
                node['usage'][key] = next(iter(values)) if len(values) == 1 else None
            if any(any(u[k] is None for k in COUNTERS) for u in usages):
                warnings.add('Token breakdown incomplete')
        visited, cursor = set(), node
        while cursor:
            if cursor["id"] in visited:
                warnings.add("Invalid execution cycle")
                break
            visited.add(cursor["id"])
            parent = cursor["parent_id"]
            if parent and parent not in nodes:
                warnings.add("Missing parent execution")
            cursor = nodes.get(parent)
        if not node["declared"]:
            warnings.add("Activity without an execution boundary")
    if not nodes:
        warnings.add("No telemetry received")
    if any(n["status"] in {"running", "unknown", "interrupted"} for n in nodes.values()):
        warnings.add("Unfinished activity; final usage is unavailable")
    if record["source"] == "desktop-unverified" or record.get('sample_case') == 'desktop':
        warnings.add("Desktop adapter unverified; subagent and collection coverage unknown")
    usage_nodes = [n for n in nodes.values() if n["usage"]]
    if len(usage_nodes) != len(nodes):
        warnings.add("Missing execution usage")
    totals = {}
    for key in ("input", "cached", "output", "reasoning"):
        known = [n["usage"][key] for n in usage_nodes if n["usage"][key] is not None]
        totals[key] = sum(known) if known else None
        if len(known) != len(nodes):
            warnings.add("Token breakdown incomplete")
    for node in nodes.values():
        u = node["usage"]
        node["own_tokens"] = u["input"] + u["output"] if u and u["input"] is not None and u["output"] is not None else None
        node["simulated_usd"] = None
        if record['source'] == 'controlled-simulation' and u and u['fixture_profile'] == 'weather-v1' and all(u[k] is not None for k in ("input", "cached", "output")):
            # Test-only rates: $1/$0.25/$4 per million uncached/cached/output tokens.
            node["simulated_usd"] = str((Decimal(u["input"] - u["cached"]) + Decimal(u["cached"]) / 4 + Decimal(u["output"]) * 4) / 1000000)
    ranked = sorted(nodes.values(), key=lambda n: (n["own_tokens"] is not None, n["own_tokens"] or 0), reverse=True)
    for node in ranked:
        subtree, seen, pending = [],set(),[node]
        cycle=False
        while pending:
            item=pending.pop()
            if item['id'] in seen:
                cycle=True
                break
            seen.add(item['id'])
            subtree.append(item['own_tokens'])
            pending.extend(n for n in ranked if n['parent_id']==item['id'])
        node['observed_subtree_tokens']=sum(subtree) if not cycle and all(n is not None for n in subtree) else None
    known_cost = [Decimal(n["simulated_usd"]) for n in ranked if n["simulated_usd"] is not None]
    for item in assessments.values():
        name = item['check'] if item['grader'] == 'weather-fixture-v1' else item['grader'] + ':' + item['check']
        previous = checks.get(name, 'passed')
        checks[name] = max((previous, item['status']), key={'passed': 0, 'failed': 1, 'error': 2}.get)
    outcome = "Ungraded"
    if checks:
        outcome = "Infrastructure error" if "error" in checks.values() else "Failed" if "failed" in checks.values() else "Passed supplied checks"
    findings = []
    if ranked and ranked[0]["own_tokens"] is not None:
        findings.append({"execution_id": ranked[0]["id"], "observation": "Largest recorded own-token consumption", "tokens": ranked[0]["own_tokens"]})
    failures = sum(n["failures"] for n in nodes.values())
    if failures:
        findings.append({"observation": "Recorded failed tool calls; causal effect on answer quality is unknown", "count": failures})
    return dict(recording=record, totals=totals, changes=changes, models=breakdown(usage_buckets.values()), elapsed_seconds=(record["finished"] - record["started"]) if record["finished"] else None,
                simulated_usd=str(sum(known_cost)) if known_cost else None, pricing_version="synthetic-v1", api_equivalent_usd=None, actual_billed_usd=None,
                outcome=outcome, checks=checks, assessments=list(assessments.values()),
                counter_complete={k: bool(nodes) and all(n.get("counter_complete", {}).get(k, False) for n in nodes.values()) for k in COUNTERS}, executions=ranked, security=security, tool_failures=failures,
                findings=findings, coverage="incomplete" if warnings else "available-events-consistent", warnings=sorted(warnings))
