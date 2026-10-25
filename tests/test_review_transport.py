"""Exercise review gates with a real, local fake CLI, never a model call."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review_grok.py"
spec = importlib.util.spec_from_file_location("adaptive_review_transport", SCRIPT)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def test_utf8_chunks_preserve_bytes_and_never_split_codepoints():
    original = "Strahlung ☀️: Grüße aus Köln 🙂\n" * 17
    chunks = review.split_utf8(original, 17)
    assert "".join(chunks) == original
    assert all(0 < len(chunk.encode("utf-8")) <= 17 for chunk in chunks)
    assert review.split_utf8("") == []


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_utf8_rejects_invalid_limits(limit):
    with pytest.raises(ValueError):
        review.split_utf8("text", limit)


def test_utf8_rejects_single_codepoint_wider_than_limit():
    with pytest.raises(ValueError):
        review.split_utf8("🙂", 3)


@pytest.mark.parametrize("raw", [
    '{}',
    '{"verdict":"mergeable","findings":[],"summary":""}',
    '{"verdict":"mergeable","findings":[],"summary":"ok","verdict":"blocked"}',
    '{"verdict":"mergeable","findings":[{}],"summary":"ok"}',
    '{"verdict":"blocked","findings":[{"id":"X","severity":"high","file":"a.py","line":true,"problem":"x","recommendation":"y"}],"summary":"ok"}',
    'Review follows: {"verdict":"mergeable","findings":[],"summary":"ok"}',
])
def test_review_parse_rejects_incomplete_or_ambiguous_receipts(raw):
    with pytest.raises((ValueError, json.JSONDecodeError)):
        review.parse_review(raw)


def test_review_parse_accepts_complete_result_and_blocks_findings():
    clean = {"verdict": "mergeable", "findings": [], "summary": "Geprüft."}
    assert review.parse_review(json.dumps(clean)) == clean
    finding = {"id": "AS-001", "severity": "medium", "file": "a.py", "line": 2,
               "problem": "Falsche Einheit", "recommendation": "Umrechnen"}
    with pytest.raises(ValueError, match="Findings"):
        review.parse_review(json.dumps({**clean, "findings": [finding]}))
    assert review.parse_review(json.dumps({**clean, "verdict": "blocked", "findings": [finding]}))["verdict"] == "blocked"


@pytest.fixture
def transport_workspace(tmp_path):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copyfile(SCRIPT, root / "scripts/review_grok.py")
    (root / "README.md").write_text("# Testprojekt\nNur synthetischer Review.\n")
    (root / ".gitignore").write_text("reviews/\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"], cwd=root, check=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "grok"
    fake.write_text(f"#!{sys.executable}\n" + r'''
import json
import os
from pathlib import Path
import re
import sys
import time

mode = os.environ.get("FAKE_GROK_MODE", "success")
if "--version" in sys.argv:
    if mode == "version_timeout":
        time.sleep(3)
    if mode == "version_fail":
        raise SystemExit(8)
    print("fake-grok 1.0")
    raise SystemExit(0)
args = sys.argv[1:]
root = Path.cwd()
with (root / "reviews/private/argv.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\n")
prompt_file = Path(args[args.index("--prompt-file") + 1])
prompt = prompt_file.read_bytes().decode("utf-8")
if mode == "fail":
    print("Deliberate fake CLI failure", file=sys.stderr)
    raise SystemExit(7)
if mode == "timeout":
    time.sleep(3)
assert os.environ["GROK_AUTO_COMPACT_THRESHOLD_PERCENT"] == "100"
assert os.environ["GROK_DISABLE_AUTOUPDATER"] == "1"
session = args[args.index("--session-id" if "--session-id" in args else "--resume") + 1]
updates = Path(os.environ["GROK_HOME"]) / "sessions/test-project" / session / "updates.jsonl"
if mode != "missing_updates":
    updates.parent.mkdir(parents=True, exist_ok=True)
    previous = [json.loads(line) for line in updates.read_text().splitlines()] if updates.exists() else []
    indices = [row["params"]["update"].get("_meta", {}).get("promptIndex") for row in previous
               if row["params"]["update"]["sessionUpdate"] == "user_message_chunk"]
    index = max(indices, default=-1) + 1
    captured = prompt + " " if mode == "altered_prompt" else prompt
    if mode == "changed_unicode":
        captured = captured.replace("ü", "u", 1)
    if mode == "tag_removed":
        captured = captured.replace("<review-data>", "", 1)
    rows = []
    for text in (captured[:len(captured)//2], captured[len(captured)//2:]):
        update = {"sessionUpdate": "user_message_chunk", "content": {"type": "text", "text": text},
                  "_meta": {"promptIndex": index}}
        if mode == "missing_meta":
            del update["_meta"]
        params = {"sessionId": session, "update": update}
        if mode == "params_meta_only":
            params["_meta"] = update.pop("_meta")
        if mode == "foreign_session":
            params["sessionId"] = "00000000-0000-0000-0000-000000000000"
        rows.append({"timestamp": 1792886400000, "method": "session/update", "params": params})
    if mode == "compaction":
        for kind in ("auto_compact_started", "compaction_checkpoint", "auto_compact_completed"):
            rows.append({"timestamp": 1792886400001, "method": "_x.ai/session/update",
                         "params": {"sessionId": session, "update": {"sessionUpdate": kind}}})
    rows.append({"timestamp": 1792886400001, "method": "session/update",
                 "params": {"sessionId": session, "update": {"sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "PRIVATE_HISTORY_SENTINEL"}}}})
    rows.append({"timestamp": 1792886400002, "method": "_x.ai/session/update",
                 "params": {"sessionId": session, "update": {"sessionUpdate": "turn_completed",
                            "prompt_id": f"prompt-{index}", "stop_reason": "end_turn", "usage": {}, "elapsed_ms": 10}}})
    rows.append({"timestamp": 1792886400003, "method": "_x.ai/session/update",
                 "params": {"sessionId": session, "update": {"sessionUpdate": "background_tasks", "tasks": []}}})
    with updates.open("a") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")
    if mode == "truncated_updates":
        updates.write_bytes(updates.read_bytes()[:-1])
    if mode == "duplicate_session":
        duplicate = updates.parents[2] / "other-project" / session / "updates.jsonl"
        duplicate.parent.mkdir(parents=True)
        duplicate.write_bytes(updates.read_bytes())
if mode == "prompt_file_change":
    prompt_file.write_bytes(prompt_file.read_bytes() + b"changed")
if prompt.startswith("Store context chunk"):
    ack = re.search(r"OK CHUNK \d+", prompt).group()
    if mode == "bad_ack":
        print(ack + ".")
    elif mode == "early_review":
        print('{"verdict":"mergeable","findings":[],"summary":"too early"}')
    else:
        print(ack)
    if mode == "mutate":
        with (root / "README.md").open("a") as source:
            source.write("Changed during review\n")
    if mode == "binary_change":
        with Path(__file__).open("a") as binary:
            binary.write("\n# executable drift\n")
else:
    if mode == "invalid_review":
        print("Successful process, invalid review JSON")
    else:
        print(json.dumps({"verdict":"mergeable","findings":[],"summary":"Synthetic transport test only"}))
''')
    fake.chmod(0o755)
    return root, bin_dir


def run_fake(workspace, mode, timeout=10, transport="chunks", extra=()):
    root, bin_dir = workspace
    output = root / "reviews/private/test-run"
    env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""), "FAKE_GROK_MODE": mode,
           "GROK_HOME": str(root.parent / "fake-grok-home")}
    argv = [sys.executable, str(root / "scripts/review_grok.py"), "--output-dir", str(output),
            "--timeout", str(timeout), *extra]
    if transport is not None:
        argv.extend(["--transport", transport])
    run = subprocess.run(argv,
                         cwd=root, env=env, capture_output=True, text=True, timeout=20)
    receipt = json.loads((output / "receipt.json").read_text())
    return run, receipt, output


def test_fake_cli_success_binds_flags_hashes_and_process_exit(transport_workspace):
    run, receipt, output = run_fake(transport_workspace, "success")
    assert run.returncode == 0, run.stderr
    assert receipt["status"] == "accepted"
    assert receipt["requested_model"] == "grok-4.7"
    assert receipt["cli_sha256"] and receipt["payload_sha256"] and receipt["review_sha256"]
    assert receipt["files"]["README.md"]
    assert receipt["calls"][-1]["label"] == "final"
    for record in receipt["calls"]:
        assert record["returncode"] == 0
        argv = record["argv"]
        assert argv[argv.index("--model") + 1] == "grok-4.7"
        assert argv[argv.index("--tools") + 1] == ""
        assert {"--disable-web-search", "--no-subagents", "--no-memory"}.issubset(argv)
    assert (output / "review.json").exists()
    assert receipt["transport"] == "chunks"
    assert receipt["context_audit"]["prompt_count"] == len(receipt["calls"])
    assert receipt["context_audit"]["compaction_count"] == 0


@pytest.mark.parametrize("mode,reason", [
    ("bad_ack", "exact receipt"),
    ("early_review", "exact receipt"),
    ("fail", "Grok failed (7)"),
    ("mutate", "Source scope changed"),
    ("binary_change", "executable changed"),
    ("timeout", "process deadline"),
    ("version_timeout", "version check failed"),
    ("version_fail", "version check failed"),
])
def test_fake_cli_failure_and_drift_fail_closed(transport_workspace, mode, reason):
    run, receipt, output = run_fake(transport_workspace, mode, timeout=1 if mode in {"timeout", "version_timeout"} else 10)
    assert run.returncode != 0
    assert receipt["status"] == "failed"
    assert reason in receipt["error"]
    assert not (output / "review.json").exists()
    if mode == "fail":
        assert receipt["calls"][-1]["returncode"] == 7
    if mode == "timeout":
        assert receipt["calls"][-1]["returncode"] == "timeout"


def test_raw_payload_preserves_all_bytes_and_documents_exact_offsets(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "ROOT", tmp_path)
    originals = {"unicode.py": "# Grüße ☀️\r\nprint('🙂')".encode(), "empty.md": b"",
                 "trailing.md": b"first\n\n\t ", "ordinary.txt": b"1: original source\n"}
    for name, data in originals.items():
        (tmp_path / name).write_bytes(data)
    payload, manifest = review.build_payload({name: review.digest(data) for name, data in originals.items()})
    assert payload == payload.strip()
    assert payload.endswith(b"</review-data>")
    assert len(manifest) == len(originals)
    for metadata in manifest:
        data = originals[metadata["path"]]
        assert payload[metadata["byte_start"]:metadata["byte_end"]] == data
        assert metadata["byte_length"] == len(data)
        assert metadata["sha256"] == review.digest(data)


def test_raw_payload_rejects_source_changed_since_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "ROOT", tmp_path)
    (tmp_path / "source.py").write_text("changed")
    with pytest.raises(ValueError, match="Source changed"):
        review.build_payload({"source.py": review.digest(b"original")})


def test_default_single_transport_has_one_fresh_session_and_exact_raw_payload(transport_workspace):
    run, receipt, output = run_fake(transport_workspace, "success", transport=None)
    assert run.returncode == 0, run.stderr
    assert receipt["status"] == "accepted"
    assert receipt["transport"] == "single"
    assert len(receipt["calls"]) == 1
    call = receipt["calls"][0]
    assert call["label"] == "single"
    assert "--session-id" in call["argv"] and "--resume" not in call["argv"]
    payload = (output / "payload.md").read_bytes()
    assert payload == (output / "single-prompt.md").read_bytes()
    assert payload == payload.strip()
    assert receipt["payload_byte_length"] == len(payload)
    assert receipt["context_audit"]["prompt_sha256"] == [review.digest(payload)]
    assert receipt["context_audit"]["user_chunk_count"] == 2
    assert receipt["context_audit"]["event_count"] == 5
    assert receipt["context_audit"]["turn_completed_count"] == 1
    assert "PRIVATE_HISTORY_SENTINEL" not in (output / "receipt.json").read_text()
    root, _ = transport_workspace
    assert set(item["path"] for item in receipt["file_manifest"]) == set(receipt["files"])
    for item in receipt["file_manifest"]:
        assert payload[item["byte_start"]:item["byte_end"]] == (root / item["path"]).read_bytes()


@pytest.mark.parametrize("mode,reason", [
    ("missing_updates", "exactly one"),
    ("compaction", "detected compaction"),
    ("altered_prompt", "prompt bytes differ"),
    ("changed_unicode", "prompt bytes differ"),
    ("tag_removed", "prompt bytes differ"),
    ("missing_meta", "prompt metadata"),
    ("params_meta_only", "prompt metadata"),
    ("foreign_session", "foreign session"),
    ("truncated_updates", "truncated"),
    ("duplicate_session", "exactly one"),
    ("prompt_file_change", "Prompt file changed"),
])
def test_successful_cli_exit_cannot_bypass_context_audit(transport_workspace, mode, reason):
    run, receipt, output = run_fake(transport_workspace, mode, transport="single")
    assert run.returncode != 0
    assert receipt["calls"][0]["returncode"] == 0
    assert receipt["status"] == "failed"
    assert reason in receipt["error"]
    assert not (output / "review.json").exists()


def test_single_payload_limit_fails_without_truncation_or_cli_execution(transport_workspace):
    root, _ = transport_workspace
    (root / "README.md").write_bytes(b"x" * review.MAX_SINGLE_PAYLOAD_BYTES)
    run, receipt, output = run_fake(transport_workspace, "success", transport="single")
    assert run.returncode != 0
    assert receipt["status"] == "failed"
    assert "no files omitted" in receipt["error"]
    assert receipt["payload_byte_length"] > review.MAX_SINGLE_PAYLOAD_BYTES
    assert not receipt["calls"]
    assert not (output / "review.json").exists()
    payload = (output / "payload.md").read_bytes()
    item = next(row for row in receipt["file_manifest"] if row["path"] == "README.md")
    assert payload[item["byte_start"]:item["byte_end"]] == (root / "README.md").read_bytes()


def test_multiple_chunk_prompts_are_all_audited_in_sequence(transport_workspace):
    root, _ = transport_workspace
    (root / "README.md").write_text("# Grüße ☀️\n" * 12000)
    run, receipt, _ = run_fake(transport_workspace, "success", transport="chunks")
    assert run.returncode == 0, run.stderr
    assert receipt["chunk_count"] > 1
    assert receipt["context_audit"]["prompt_count"] == receipt["chunk_count"] + 1
    assert receipt["context_audit"]["prompt_sha256"] == [row["prompt_sha256"] for row in receipt["calls"]]


def test_successful_cli_is_audited_even_when_review_json_is_invalid(transport_workspace):
    run, receipt, output = run_fake(transport_workspace, "invalid_review", transport="single")
    assert run.returncode != 0
    assert receipt["status"] == "failed"
    assert receipt["calls"][0]["returncode"] == 0
    assert receipt["context_audit"]["turn_completed_count"] == 1
    assert not (output / "review.json").exists()


@pytest.fixture
def context_updates(tmp_path):
    session = "00000000-0000-4000-8000-000000000001"
    path = tmp_path / "sessions/project" / session / "updates.jsonl"
    path.parent.mkdir(parents=True)

    def write(updates, complete=True):
        if complete:
            updates = [*updates, completed_update()]
        rows = [{"timestamp": 1792886400000,
                 "method": "_x.ai/session/update" if update["sessionUpdate"] in {
                     "turn_completed", "background_tasks", "auto_compact_started", "compaction_checkpoint",
                     "auto_compact_completed"} else "session/update",
                 "params": {"sessionId": session, "update": update}} for update in updates]
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return path

    return tmp_path, session, write


def user_update(text="prompt", index=0):
    return {"sessionUpdate": "user_message_chunk", "content": {"type": "text", "text": text},
            "_meta": {"promptIndex": index}}


def completed_update(index=0):
    return {"sessionUpdate": "turn_completed", "prompt_id": f"prompt-{index}", "stop_reason": "end_turn",
            "usage": {}, "elapsed_ms": 10}


@pytest.mark.parametrize("kind", ["auto_compact_started", "compaction_checkpoint", "auto_compact_completed"])
def test_each_compaction_event_individually_rejects_context(context_updates, kind):
    home, session, write = context_updates
    write([user_update(), {"sessionUpdate": kind}])
    with pytest.raises(ValueError, match="detected compaction"):
        review.audit_context(session, [b"prompt"], grok_home=home)


@pytest.mark.parametrize("start", [0, 1])
def test_audit_accepts_only_exact_ordered_prompt_bytes_and_reads_current_session(context_updates, start):
    home, session, write = context_updates
    path = write([user_update("Gr", start), user_update("üße", start), completed_update(start),
                  user_update("next", start + 1), completed_update(start + 1)], complete=False)
    # Another session is intentionally unreadable JSON, and auth/trace paths are irrelevant.
    unrelated = home / "sessions/project" / "00000000-0000-4000-8000-000000000002" / "updates.jsonl"
    unrelated.parent.mkdir()
    unrelated.write_text("NEVER READ THIS HISTORY")
    (home / "auth.json").write_text("NEVER READ AUTH")
    result = review.audit_context(session, ["Grüße".encode(), b"next"], grok_home=home)
    assert result["prompt_count"] == 2
    assert result["updates_sha256"] == review.digest(path.read_bytes())
    assert result["prompt_sha256"] == [review.digest("Grüße".encode()), review.digest(b"next")]


@pytest.mark.parametrize("indices", [[2], [0, 2], [0, 1, 0], [True], [-1], ["0"]])
def test_unknown_or_ambiguous_prompt_indices_fail_closed(context_updates, indices):
    home, session, write = context_updates
    write([user_update(index=index) for index in indices])
    with pytest.raises(ValueError, match="metadata|groups|ordering"):
        review.audit_context(session, [b"prompt"] * len(indices), grok_home=home)


@pytest.mark.parametrize("mutation", ["missing_timestamp", "missing_method", "missing_update", "duplicate_key",
                                     "nontext", "missing_text", "missing_index", "bool_index", "blank_line"])
def test_malformed_or_missing_metadata_is_not_silently_ignored(context_updates, mutation):
    home, session, write = context_updates
    path = write([user_update()])
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    row = rows[0]
    if mutation.startswith("missing_") and mutation in {"missing_timestamp", "missing_method"}:
        del row[mutation.removeprefix("missing_")]
    elif mutation == "missing_update":
        del row["params"]["update"]
    elif mutation == "nontext":
        row["params"]["update"]["content"]["type"] = "image"
    elif mutation == "missing_text":
        del row["params"]["update"]["content"]["text"]
    elif mutation == "missing_index":
        del row["params"]["update"]["_meta"]["promptIndex"]
    elif mutation == "bool_index":
        row["params"]["update"]["_meta"]["promptIndex"] = True
    path.write_text("".join(json.dumps(item) + "\n" for item in rows))
    if mutation == "duplicate_key":
        path.write_text(path.read_text().replace('"promptIndex": 0', '"promptIndex": 0, "promptIndex": 0'))
    elif mutation == "blank_line":
        path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError):
        review.audit_context(session, [b"prompt"], grok_home=home)


@pytest.mark.parametrize("expected,actual", [(b"prompt", " prompt"), (b"prompt", "prompt\n"),
                                            (b"<tag>prompt</tag>", "prompt"), ("ü".encode(), "u")])
def test_audit_never_normalizes_whitespace_tags_or_unicode(context_updates, expected, actual):
    home, session, write = context_updates
    write([user_update(actual)])
    with pytest.raises(ValueError, match="prompt bytes differ"):
        review.audit_context(session, [expected], grok_home=home)


@pytest.mark.parametrize("kind", ["tool_call", "tool_call_update", "future_unknown_update"])
def test_tools_and_unknown_update_types_are_rejected(context_updates, kind):
    home, session, write = context_updates
    write([user_update(), {"sessionUpdate": kind}])
    with pytest.raises(ValueError, match="forbidden tool call|unknown event type"):
        review.audit_context(session, [b"prompt"], grok_home=home)


def test_unknown_method_cannot_masquerade_as_known_update(context_updates):
    home, session, write = context_updates
    path = write([user_update()])
    path.write_text(path.read_text().replace('"method": "session/update"', '"method": "unknown/update"'))
    with pytest.raises(ValueError, match="unknown event type or method"):
        review.audit_context(session, [b"prompt"], grok_home=home)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "not_end_turn", "missing_id", "duplicate_id",
                                     "missing_usage", "invalid_elapsed", "text_after_end", "string_timestamp"])
def test_only_complete_native_end_turn_metadata_is_accepted(context_updates, mutation):
    home, session, write = context_updates
    completion = completed_update()
    updates = [user_update(), completion]
    if mutation == "missing":
        updates.pop()
    elif mutation == "duplicate":
        updates.append(completed_update())
    elif mutation == "not_end_turn":
        completion["stop_reason"] = "max_turns"
    elif mutation == "missing_id":
        del completion["prompt_id"]
    elif mutation == "duplicate_id":
        updates.extend([user_update("second", 1), completed_update()])
    elif mutation == "missing_usage":
        del completion["usage"]
    elif mutation == "invalid_elapsed":
        completion["elapsed_ms"] = True
    elif mutation == "text_after_end":
        updates.append(user_update("extra"))
    path = write(updates, complete=False)
    if mutation == "string_timestamp":
        path.write_text(path.read_text().replace("1792886400000", '"1792886400000"'))
    with pytest.raises(ValueError, match="metadata|completion|groups"):
        review.audit_context(session, [b"prompt"], grok_home=home)


@pytest.mark.parametrize("tasks", [None, {}, False, [{"task_id": "not-permitted"}]])
def test_unknown_or_active_background_tasks_reject_the_review(context_updates, tasks):
    home, session, write = context_updates
    write([user_update(), {"sessionUpdate": "background_tasks", "tasks": tasks}])
    with pytest.raises(ValueError, match="background tasks"):
        review.audit_context(session, [b"prompt"], grok_home=home)


def test_audit_rejects_session_symlinks_instead_of_reading_another_history(context_updates):
    home, session, write = context_updates
    path = write([user_update()])
    real = home / "unrelated-history.jsonl"
    path.rename(real)
    path.symlink_to(real)
    with pytest.raises(ValueError, match="regular, unambiguous"):
        review.audit_context(session, [b"prompt"], grok_home=home)
