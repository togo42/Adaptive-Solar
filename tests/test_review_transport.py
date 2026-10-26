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

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review.py"
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
    '{"verdict":"mergeable","findings":[],"summary":"ok","partial":true}',
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
    shutil.copyfile(SCRIPT, root / "scripts/review.py")
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
if os.environ.get("FAKE_CLI_LOG"):
    with Path(os.environ["FAKE_CLI_LOG"]).open("a") as log:
        log.write(json.dumps(sys.argv[1:]) + "\n")
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
assert os.environ["GROK_DEBUG_CONTEXT_WINDOW"] == "500000"
assert os.environ["GROK_DISABLE_AUTOUPDATER"] == "1"
session = args[args.index("--session-id" if "--session-id" in args else "--resume") + 1]
updates = Path(os.environ["GROK_HOME"]) / "sessions/test-project" / session / "updates.jsonl"
if mode != "missing_updates":
    updates.parent.mkdir(parents=True, exist_ok=True)
    (updates.parent / "summary.json").write_text(json.dumps({
        "current_model_id": "wrong-model" if mode == "wrong_model" else "grok-4.7",
        "reasoning_effort": "low" if mode == "low_effort" else "high"}))
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
    reply = (re.search(r"OK CHUNK \d+", prompt).group() if prompt.startswith("Store context chunk") else
             json.dumps({"verdict":"mergeable","findings":[],"summary":"Synthetic transport test only"}))
    rows.append({"timestamp": 1792886400001, "method": "session/update",
                 "params": {"sessionId": session, "update": {"sessionUpdate": "agent_thought_chunk",
                            "content": {"type": "text", "text": "PRIVATE_HISTORY_SENTINEL"}}}})
    rows.append({"timestamp": 1792886400001, "method": "session/update",
                 "params": {"sessionId": session, "update": {"sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": reply if mode != "response_mismatch" else
                                '{"verdict":"mergeable","findings":[],"summary":"different native response"}'}}}})
    rows.append({"timestamp": 1792886400002, "method": "_x.ai/session/update",
                 "params": {"sessionId": session, "update": {"sessionUpdate": "turn_completed",
                            "prompt_id": f"prompt-{index}", "stop_reason": "end_turn", "elapsed_ms": 10,
                            "usage": {"modelCalls": 2 if mode == "extra_model_call" else 1,
                                      "numTurns": 2 if mode == "extra_turn" else 1,
                                      "modelUsage": {"wrong-model" if mode == "wrong_usage_model" else "grok-4.7-build": {"modelCalls": 1}}}}}})
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
if os.environ.get("FAKE_DRIFT_PATH"):
    with Path(os.environ["FAKE_DRIFT_PATH"]).open("a") as changed:
        changed.write(os.environ.get("FAKE_DRIFT_SUFFIX", "\nDRIFT\n"))
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


def run_fake(workspace, mode, timeout=10, transport="chunks", extra=(), output_name="test-run", extra_env=None):
    root, bin_dir = workspace
    output = root / "reviews/private" / output_name
    env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""), "FAKE_GROK_MODE": mode,
           "GROK_HOME": str(root.parent / "fake-grok-home"),
           "FAKE_CLI_LOG": str(root / "reviews/private/cli-calls.jsonl"), **(extra_env or {})}
    argv = [sys.executable, str(root / "scripts/review.py"), "--output-dir", str(output),
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


def test_snapshot_includes_extensionless_licenses_without_private_files(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "ROOT", tmp_path)
    files = {
        "LICENSE": b"Public project license\n",
        "custom_components/example/LICENSE": b"Shipped component license\n",
        "data/LICENSE": b"Private data must remain excluded\n",
        "icon.png": b"\x89PNG\r\n",
    }
    for name, data in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    monkeypatch.setattr(review, "git", lambda *args: "\0".join(files))
    snapshot = review.snapshot()
    assert set(snapshot) == {"LICENSE", "custom_components/example/LICENSE"}
    payload, _ = review.build_payload(snapshot)
    assert all(data in payload for name, data in files.items() if name in snapshot)
    assert files["data/LICENSE"] not in payload


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
    assert receipt["context_audit"]["event_count"] == 6
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
    ("low_effort", "high reasoning effort"),
    ("wrong_model", "high reasoning effort"),
    ("extra_model_call", "one matching native model call"),
    ("extra_turn", "one matching native model call"),
    ("wrong_usage_model", "one matching native model call"),
    ("response_mismatch", "Native final response differs"),
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


@pytest.fixture
def reference_workspace(transport_workspace):
    root, binary_dir = transport_workspace
    binary = binary_dir / 'grok'
    binary.rename(binary_dir / 'native-grok')
    binary.symlink_to(binary_dir / 'native-grok')
    for index, name in enumerate(sorted(review.RESEARCH_FILES)):
        (root / name).write_text(f"Originalforschung {index}: Grüße ☀️\n")
    for name in ('tests/current.py', 'docs/current.md', 'scripts/current.py', 'new-public.md'):
        (root / name).parent.mkdir(exist_ok=True)
        (root / name).write_text(f"Aktuelle Originalbytes für {name}: ü\n")
    run, receipt, directory = run_fake(transport_workspace, 'success', transport='single', output_name='baseline')
    assert run.returncode == 0, run.stderr
    return transport_workspace, receipt, directory


def implementation_run(reference_workspace, *, extra_env=None):
    workspace, _, directory = reference_workspace
    return run_fake(workspace, 'success', transport='single', output_name='implementation',
                    extra=('--scope', 'implementation', '--reference-receipt', str(directory / 'receipt.json')),
                    extra_env=extra_env)


def native_path(reference_workspace, filename):
    (root, _), receipt, _ = reference_workspace
    return root.parent / 'fake-grok-home/sessions/test-project' / receipt['session_id'] / filename


def test_implementation_includes_every_other_original_byte_and_discloses_inheritance(reference_workspace):
    (root, _), baseline, directory = reference_workspace
    run, receipt, output = implementation_run(reference_workspace)
    assert run.returncode == 0, run.stderr
    assert receipt['status'] == 'accepted' and receipt['scope'] == 'implementation'
    assert set(receipt['reference_only_files']) == review.RESEARCH_FILES
    assert set(receipt['files']) == set(receipt['workspace_files']) - review.RESEARCH_FILES
    assert set(baseline['files']) == set(receipt['workspace_files'])
    payload = (output / 'payload.md').read_bytes()
    assert b'IMPLEMENTIERUNGSreview' in payload and b'NICHT Bestandteil' in payload
    assert str(directory).encode() not in payload and b'PRIVATE_HISTORY_SENTINEL' not in payload
    for item in receipt['file_manifest']:
        raw = (root / item['path']).read_bytes()
        assert payload[item['byte_start']:item['byte_end']] == raw
        assert len(raw) == item['byte_length'] and review.digest(raw) == item['sha256']
    for name in review.RESEARCH_FILES:
        assert (root / name).read_bytes() not in payload
        assert receipt['reference_only_files'][name] == baseline['files'][name]
    assert receipt['reference']['receipt_sha256'] == review.digest((directory / 'receipt.json').read_bytes())
    assert receipt['reference']['payload_sha256'] == baseline['payload_sha256']
    assert receipt['reference']['native_final_response_sha256']
    assert receipt['context_audit']['reasoning_effort'] == 'high'
    argv = receipt['calls'][0]['argv']
    assert argv[argv.index('--reasoning-effort') + 1] == 'high'
    assert len(receipt['calls']) == 1 and receipt['calls'][0]['returncode'] == 0
    assert not baseline['reference_only_files'] and baseline['scope'] == 'all'


@pytest.mark.parametrize('fault', ['blocked', 'chunks', 'inherited', 'invalid_inheritance', 'returncode', 'bool_returncode', 'cli_hash',
    'missing_cli_version', 'weak_flags', 'manifest_offset', 'manifest_omission', 'payload', 'prompt', 'stdout',
    'review', 'research', 'compaction', 'no_end_turn', 'native_reply', 'native_effort', 'native_model', 'native_usage'])
def test_reference_is_independently_rejected_before_any_cli_call(reference_workspace, fault):
    (root, _), receipt, directory = reference_workspace
    if fault == 'blocked':
        receipt['status'] = 'findings'
    elif fault == 'chunks':
        receipt['transport'] = 'chunks'
    elif fault == 'inherited':
        receipt['reference_only_files'] = {name: receipt['files'][name] for name in review.RESEARCH_FILES}
    elif fault == 'invalid_inheritance':
        receipt['reference_only_files'] = []
    elif fault in ('returncode', 'bool_returncode'):
        receipt['calls'][0]['returncode'] = 1 if fault == 'returncode' else False
    elif fault == 'cli_hash':
        receipt['cli_sha256'] = '0' * 64
    elif fault == 'missing_cli_version':
        receipt.pop('cli_version')
    elif fault == 'weak_flags':
        receipt['calls'][0]['argv'].remove('--no-memory')
    elif fault == 'manifest_offset':
        receipt['file_manifest'][0]['byte_start'] += 1
    elif fault == 'manifest_omission':
        receipt['file_manifest'].pop()
    elif fault in ('payload', 'prompt', 'stdout', 'review'):
        name = {'payload': 'payload.md', 'prompt': 'single-prompt.md', 'stdout': 'single-stdout.txt', 'review': 'review.json'}[fault]
        with (directory / name).open('ab') as stream:
            stream.write(b'changed')
    elif fault == 'research':
        with (root / sorted(review.RESEARCH_FILES)[0]).open('a') as stream:
            stream.write('NEUE Forschung')
    elif fault.startswith('native_') and fault != 'native_reply':
        if fault in ('native_effort', 'native_model'):
            path = native_path(reference_workspace, 'summary.json')
            summary = json.loads(path.read_text())
            summary['reasoning_effort' if fault == 'native_effort' else 'current_model_id'] = 'wrong'
            path.write_text(json.dumps(summary))
        else:
            path = native_path(reference_workspace, 'updates.jsonl')
            events = [json.loads(line) for line in path.read_text().splitlines()]
            next(row for row in events if row['params']['update']['sessionUpdate'] == 'turn_completed')['params']['update']['usage']['modelCalls'] = 2
            path.write_text(''.join(json.dumps(row) + '\n' for row in events))
    else:
        path = native_path(reference_workspace, 'updates.jsonl')
        events = [json.loads(line) for line in path.read_text().splitlines()]
        if fault == 'compaction':
            events.append({'timestamp': 1, 'method': '_x.ai/session/update', 'params': {
                'sessionId': receipt['session_id'], 'update': {'sessionUpdate': 'auto_compact_started'}}})
        elif fault == 'no_end_turn':
            events = [row for row in events if row['params']['update']['sessionUpdate'] != 'turn_completed']
        else:
            next(row for row in events if row['params']['update']['sessionUpdate'] == 'agent_message_chunk')['params']['update']['content']['text'] = '{"verdict":"mergeable","findings":[],"summary":"tampered"}'
        path.write_text(''.join(json.dumps(row) + '\n' for row in events))
    (directory / 'receipt.json').write_text(json.dumps(receipt))
    log = root / 'reviews/private/cli-calls.jsonl'
    before = log.read_bytes()
    run, failed, output = implementation_run(reference_workspace)
    assert run.returncode != 0 and failed['status'] == 'failed'
    assert not failed['calls'] and not (output / 'review.json').exists()
    assert log.read_bytes() == before  # Neither --version nor model invocation.


def test_legacy_all_reference_without_effort_flag_still_needs_native_high(reference_workspace):
    _, receipt, directory = reference_workspace
    receipt.pop('scope')
    receipt.pop('workspace_files')
    receipt.pop('reference_only_files')
    argv = receipt['calls'][0]['argv']
    index = argv.index('--reasoning-effort')
    del argv[index:index + 2]
    for key in ('summary_sha256', 'native_model_id', 'reasoning_effort', 'native_final_response_sha256'):
        receipt['context_audit'].pop(key)
    (directory / 'receipt.json').write_text(json.dumps(receipt))
    run, result, _ = implementation_run(reference_workspace)
    assert run.returncode == 0, run.stderr
    assert result['reference']['reasoning_effort'] == 'high'


def test_historical_cli_identity_survives_alias_upgrade_but_new_call_is_pinned(reference_workspace):
    (_, binary_dir), baseline, _ = reference_workspace
    alias = binary_dir / 'grok'
    replacement = binary_dir / 'new-grok'
    replacement.write_bytes(Path(baseline['cli_path']).read_bytes() + b'\n# new executable\n')
    replacement.chmod(0o755)
    alias.unlink()
    alias.symlink_to(replacement)
    run, receipt, _ = implementation_run(reference_workspace)
    assert run.returncode == 0, run.stderr
    assert receipt['reference']['cli_sha256'] == baseline['cli_sha256']
    assert receipt['cli_sha256'] != baseline['cli_sha256']
    assert receipt['cli_path'] == str(replacement)


@pytest.mark.parametrize('target', ['reference_receipt', 'reference_payload', 'reference_summary',
                                   'reference_updates', 'research', 'source', 'new_source', 'payload', 'prompt'])
def test_reference_and_complete_workspace_remain_frozen_through_closeout(reference_workspace, target):
    (root, _), _, directory = reference_workspace
    paths = {'reference_receipt': directory / 'receipt.json', 'reference_payload': directory / 'payload.md',
             'reference_summary': native_path(reference_workspace, 'summary.json'),
             'reference_updates': native_path(reference_workspace, 'updates.jsonl'),
             'research': root / sorted(review.RESEARCH_FILES)[0], 'source': root / 'README.md',
             'new_source': root / 'new-source.py', 'payload': root / 'reviews/private/implementation/payload.md',
             'prompt': root / 'reviews/private/implementation/single-prompt.md'}
    run, result, output = implementation_run(reference_workspace, extra_env={
        'FAKE_DRIFT_PATH': str(paths[target]), 'FAKE_DRIFT_SUFFIX': '\n '})
    assert run.returncode != 0 and result['status'] == 'failed'
    assert len(result['calls']) == 1 and result['calls'][0]['returncode'] == 0
    assert not (output / 'review.json').exists()


def test_an_accepted_implementation_receipt_cannot_become_a_reference_chain(reference_workspace):
    workspace, _, _ = reference_workspace
    run, _, directory = implementation_run(reference_workspace)
    assert run.returncode == 0
    root, _ = workspace
    log = root / 'reviews/private/cli-calls.jsonl'
    before = log.read_bytes()
    run, result, _ = run_fake(workspace, 'success', transport='single', output_name='chain',
        extra=('--scope', 'implementation', '--reference-receipt', str(directory / 'receipt.json')))
    assert run.returncode != 0 and result['status'] == 'failed'
    assert not result['calls'] and log.read_bytes() == before


@pytest.mark.parametrize('args', [('--scope', 'implementation'), ('--reference-receipt', 'receipt.json'),
    ('--scope', 'implementation', '--reference-receipt', 'receipt.json', '--transport', 'chunks'),
    ('--exclude', 'core/physics.py')])
def test_no_free_exclusions_or_ambiguous_reference_modes(transport_workspace, args):
    root, binary_dir = transport_workspace
    run = subprocess.run([sys.executable, str(root / 'scripts/review.py'), *args], cwd=root,
        env={**os.environ, 'PATH': str(binary_dir) + os.pathsep + os.environ.get('PATH', '')},
        capture_output=True, timeout=10)
    assert run.returncode != 0
    assert not (root / 'reviews/private').exists()


@pytest.fixture
def ordered_context(context_updates):
    home, session, write = context_updates
    verdict = {'verdict': 'mergeable', 'findings': [], 'summary': 'Synthetic ordering check'}
    def check(updates):
        completion = completed_update()
        completion['usage'] = {'modelCalls': 1, 'numTurns': 1, 'modelUsage': {'grok-4.7-build': {'modelCalls': 1}}}
        path = write([*updates, completion], complete=False)
        path.with_name('summary.json').write_text(json.dumps({'current_model_id': 'grok-4.7', 'reasoning_effort': 'high'}))
        return review.audit_context(session, [b'AB'], grok_home=home, require_identity=True, expected_review=verdict)
    return check, json.dumps(verdict)


@pytest.mark.parametrize('kind', ['agent_message_chunk', 'agent_thought_chunk'])
@pytest.mark.parametrize('initial,late', [('A', 'B'), ('AB', ''), ('AB', 'B')])
def test_native_output_cannot_precede_complete_prompt_or_accept_any_late_user_chunk(ordered_context, kind, initial, late):
    check, final = ordered_context
    updates = [user_update(initial), {'sessionUpdate': kind, 'content': {'type': 'text', 'text': final if kind == 'agent_message_chunk' else 'thinking'}}, user_update(late)]
    if kind == 'agent_thought_chunk':
        updates.append({'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': final}})
    with pytest.raises(ValueError, match='before output|after output'):
        check(updates)


@pytest.mark.parametrize('kind', ['agent_message_chunk', 'agent_thought_chunk'])
def test_complete_split_user_bytes_before_first_output_are_valid(ordered_context, kind):
    check, final = ordered_context
    updates = [user_update('A'), user_update('B'), {'sessionUpdate': kind,
               'content': {'type': 'text', 'text': final if kind == 'agent_message_chunk' else 'thinking'}}]
    if kind == 'agent_thought_chunk':
        updates.append({'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': final}})
    assert check(updates)['turn_completed_count'] == 1


@pytest.mark.parametrize('canonical_drift', [False, True])
def test_version_and_review_execute_canonical_file_even_during_alias_swap(tmp_path, monkeypatch, canonical_drift):
    root = tmp_path / 'workspace'
    root.mkdir()
    (root / 'README.md').write_text('Synthetic source only')
    canonical, other, alias = tmp_path / 'A', tmp_path / 'B', tmp_path / 'grok'
    canonical.write_bytes(b'canonical A')
    other.write_bytes(b'wrong B')
    alias.symlink_to(canonical)
    monkeypatch.setattr(review, 'ROOT', root)
    monkeypatch.setattr(review.shutil, 'which', lambda name: str(alias))
    monkeypatch.setattr(review, 'git', lambda *args: 'README.md\0' if args[0] == 'ls-files' else 'synthetic-head')
    home = tmp_path / 'native-home'
    monkeypatch.setenv('GROK_HOME', str(home))
    monkeypatch.setattr(sys, 'argv', ['review.py'])
    selected = []
    def selected_at_exec(argv):
        alias.unlink()
        alias.symlink_to(other)
        selected.append((argv[0], Path(argv[0]).resolve()))
        alias.unlink()
        alias.symlink_to(canonical)
    def version(argv, **kwargs):
        selected_at_exec(argv)
        if canonical_drift:
            canonical.write_bytes(b'changed canonical A')
        return 'synthetic-cli\n'
    def run(argv, **kwargs):
        selected_at_exec(argv)
        session = argv[argv.index('--session-id') + 1]
        path = home / 'sessions/project' / session / 'updates.jsonl'
        path.parent.mkdir(parents=True)
        prompt = Path(argv[argv.index('--prompt-file') + 1]).read_text()
        final = json.dumps({'verdict': 'mergeable', 'findings': [], 'summary': 'Synthetic exec check'})
        completion = completed_update()
        completion['usage'] = {'modelCalls': 1, 'numTurns': 1, 'modelUsage': {'grok-4.7-build': {'modelCalls': 1}}}
        updates = [user_update(prompt), {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': final}}, completion]
        path.write_text(''.join(json.dumps({'timestamp': 1,
            'method': '_x.ai/session/update' if update['sessionUpdate'] == 'turn_completed' else 'session/update',
            'params': {'sessionId': session, 'update': update}}) + '\n' for update in updates))
        path.with_name('summary.json').write_text(json.dumps({'current_model_id': 'grok-4.7', 'reasoning_effort': 'high'}))
        return subprocess.CompletedProcess(argv, 0, stdout=final.encode(), stderr=b'')
    monkeypatch.setattr(review.subprocess, 'check_output', version)
    monkeypatch.setattr(review.subprocess, 'run', run)
    if canonical_drift:
        with pytest.raises(RuntimeError, match='version check failed'):
            review.main()
        receipt_path, = (root / 'reviews/private').glob('*/receipt.json')
        receipt = json.loads(receipt_path.read_text())
        assert receipt['status'] == 'failed' and not receipt['calls']
        assert selected == [(str(canonical), canonical)]
    else:
        assert review.main() == 0
        assert selected == [(str(canonical), canonical), (str(canonical), canonical)]


@pytest.fixture
def codex_workspace(transport_workspace):
    root, bin_dir = transport_workspace
    fake_codex = bin_dir / "codex"
    fake_codex.write_text(f"#!{sys.executable}\n" + r'''
import json
import os
from pathlib import Path
import re
import sys
import time

mode = os.environ.get("FAKE_CODEX_MODE", "success")
if os.environ.get("FAKE_CLI_LOG"):
    with Path(os.environ["FAKE_CLI_LOG"]).open("a") as log:
        log.write(json.dumps(sys.argv[1:]) + "\n")
if "--version" in sys.argv:
    if mode == "version_timeout":
        time.sleep(3)
    if mode == "version_fail":
        raise SystemExit(8)
    print("codex-cli 0.164.0")
    raise SystemExit(0)
args = sys.argv[1:]
assert args[0] == "exec"
is_resume = len(args) > 1 and args[1] == "resume"
if mode == "fail":
    print("Deliberate fake Codex failure", file=sys.stderr)
    raise SystemExit(9)
if mode == "timeout":
    time.sleep(3)
prompt = sys.stdin.buffer.read().decode("utf-8")
codex_home = Path(os.environ["CODEX_HOME"])
existing_sessions = len(list(codex_home.glob("sessions/*/*/*/rollout-*.jsonl"))) if codex_home.exists() else 0
default_session = "01a1781a-e760-73b3-9db1-bbdc214acc4f" if existing_sessions == 0 else f"01a1781a-e760-73b3-9db1-bbdc214acc{existing_sessions:02x}"
session = args[-2] if is_resume else default_session
rollout = codex_home / "sessions/2026/10/26" / f"rollout-2026-10-26T16-00-00-{session}.jsonl"
if mode != "missing_updates":
    rollout.parent.mkdir(parents=True, exist_ok=True)
    existing = [json.loads(line) for line in rollout.read_text().splitlines()] if rollout.exists() else []
    turn_index = sum(1 for row in existing if row.get("type") == "event_msg" and row.get("payload", {}).get("type") == "task_started")
    turn_id = f"turn-{turn_index}"
    rows = []
    if not existing:
        rows.append({
            "timestamp": "2026-10-26T16:00:00.000Z",
            "type": "session_meta",
            "ordinal": 0,
            "payload": {
                "id": "00000000-0000-4000-8000-000000000099" if mode == "foreign_session" else session,
                "session_id": session,
                "cli_version": "0.164.0",
                "model_provider": "openai",
                "source": {"subagent": "guardian"} if mode == "subagent_session" else "exec",
                "parent_thread_id": "00000000-0000-4000-8000-000000000088" if mode == "parent_thread" else None,
            },
        })
    rows.append({
        "timestamp": "2026-10-26T16:00:01.000Z",
        "type": "event_msg",
        "payload": {"type": "task_started", "turn_id": turn_id, "model_context_window": 500000},
    })
    if not existing:
        rows.append({
            "timestamp": "2026-10-26T16:00:01.100Z",
            "type": "response_item",
            "payload": {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "dev"}]},
        })
        rows.append({
            "timestamp": "2026-10-26T16:00:01.200Z",
            "type": "response_item",
            "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "<environment_context>"}]},
        })
        rows.append({
            "timestamp": "2026-10-26T16:00:01.300Z",
            "type": "world_state",
            "payload": {"full": True},
        })
    model_id = "wrong-model" if mode == "wrong_model" else "gpt-6.1-sol"
    effort = "medium" if mode == "low_effort" else "high"
    approval = "on-request" if mode == "wrong_approval" else "never"
    sandbox_kind = "workspace-write" if mode == "wrong_sandbox" else "read-only"
    rows.append({
        "timestamp": "2026-10-26T16:00:01.400Z",
        "type": "turn_context",
        "payload": {
            "turn_id": turn_id,
            "model": model_id,
            "effort": effort,
            "approval_policy": approval,
            "sandbox_policy": {"type": sandbox_kind},
            "collaboration_mode": {"mode": "default", "settings": {"model": model_id, "reasoning_effort": effort}},
        },
    })
    rows.append({
        "timestamp": "2026-10-26T16:00:01.500Z",
        "type": "event_msg",
        "payload": {
            "type": "thread_settings_applied",
            "thread_id": session,
            "thread_settings": {"model": model_id, "reasoning_effort": effort, "approval_policy": approval},
        },
    })
    captured = prompt + " " if mode == "altered_prompt" else prompt
    if mode == "changed_unicode":
        captured = captured.replace("ü", "u", 1)
    rows.append({
        "timestamp": "2026-10-26T16:00:02.000Z",
        "type": "response_item",
        "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": captured}]},
    })
    rows.append({
        "timestamp": "2026-10-26T16:00:02.100Z",
        "type": "event_msg",
        "payload": {
            "type": "item_completed",
            "thread_id": session,
            "turn_id": turn_id,
            "item": {"type": "UserMessage", "content": [{"type": "text", "text": captured}]},
        },
    })
    if mode == "compaction":
        rows.append({
            "timestamp": "2026-10-26T16:00:02.200Z",
            "type": "response_item",
            "payload": {"type": "compaction", "encrypted_content": "..."},
        })
    if mode == "tool_call":
        rows.append({
            "timestamp": "2026-10-26T16:00:02.300Z",
            "type": "response_item",
            "payload": {"type": "custom_tool_call", "name": "exec_command"},
        })
    reply = (re.search(r"OK CHUNK \d+", prompt).group() if prompt.startswith("Store context chunk") else
             json.dumps({"verdict": "mergeable", "findings": [], "summary": "Synthetic Codex review test"}))
    native_reply = '{"verdict":"mergeable","findings":[],"summary":"different native response"}' if mode == "response_mismatch" else reply
    rows.append({
        "timestamp": "2026-10-26T16:00:03.000Z",
        "type": "event_msg",
        "payload": {
            "type": "item_completed",
            "thread_id": session,
            "turn_id": turn_id,
            "item": {"type": "Reasoning", "content": [{"type": "Text", "text": "PRIVATE_CODEX_SENTINEL"}]},
        },
    })
    rows.append({
        "timestamp": "2026-10-26T16:00:03.100Z",
        "type": "response_item",
        "payload": {"type": "reasoning", "summary": []},
    })
    if mode == "commentary":
        rows.append({
            "timestamp": "2026-10-26T16:00:03.150Z",
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "thread_id": session,
                "turn_id": turn_id,
                "item": {"type": "AgentMessage", "content": [{"type": "Text", "text": "Checking files..."}]},
            },
        })
        rows.append({
            "timestamp": "2026-10-26T16:00:03.160Z",
            "type": "response_item",
            "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Checking files..."}], "phase": "commentary"},
        })
    rows.append({
        "timestamp": "2026-10-26T16:00:03.200Z",
        "type": "event_msg",
        "payload": {
            "type": "item_completed",
            "thread_id": session,
            "turn_id": turn_id,
            "item": {"type": "AgentMessage", "content": [{"type": "Text", "text": native_reply}]},
        },
    })
    rows.append({
        "timestamp": "2026-10-26T16:00:03.300Z",
        "type": "response_item",
        "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": native_reply}]},
    })
    for _ in range(2 if mode == "extra_model_call" else 1):
        rows.append({
            "timestamp": "2026-10-26T16:00:03.400Z",
            "type": "token_usage_record",
            "payload": {
                "thread_id": session,
                "session_id": session,
                "turn_id": turn_id,
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
        })
    if mode != "no_task_complete":
        rows.append({
            "timestamp": "2026-10-26T16:00:03.500Z",
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": turn_id,
                "duration_ms": 25,
                "last_agent_message": native_reply,
            },
        })
    with rollout.open("a") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")
    if mode == "truncated_updates":
        rollout.write_bytes(rollout.read_bytes()[:-1])
    if mode == "duplicate_session":
        dup = codex_home / "sessions/2026/10/25" / f"rollout-2026-10-25T16-00-00-{session}.jsonl"
        dup.parent.mkdir(parents=True, exist_ok=True)
        dup.write_bytes(rollout.read_bytes())
reply = (re.search(r"OK CHUNK \d+", prompt).group() if prompt.startswith("Store context chunk") else
         json.dumps({"verdict": "mergeable", "findings": [], "summary": "Synthetic Codex review test"}))
stdout_events = [
    {"type": "thread.started", "thread_id": session},
    {"type": "turn.started"},
    {"type": "item.completed", "item": {"id": "item_0", "type": "reasoning", "text": "thinking"}},
    {"type": "item.completed", "item": {"id": "item_1", "type": "agent_message",
     "text": "invalid json" if mode == "invalid_review" else reply}},
    {"type": "turn.completed", "usage": {"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 20}},
]
if mode == "commentary":
    stdout_events.insert(3, {"type": "item.completed", "item": {"id": "item_c", "type": "agent_message", "text": "Checking files..."}})
if mode == "stdout_tool":
    stdout_events.insert(2, {"type": "item.completed", "item": {"id": "cmd_1", "type": "command_execution"}})
for ev in stdout_events:
    print(json.dumps(ev))
''')
    fake_codex.chmod(0o755)
    return root, bin_dir


def run_fake_codex(workspace, mode="success", timeout=10, transport="single", extra=(), output_name="codex-run",
                   extra_env=None):
    root, bin_dir = workspace
    output = root / "reviews/private" / output_name
    env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
           "FAKE_CODEX_MODE": mode, "CODEX_HOME": str(root.parent / "fake-codex-home"),
           "FAKE_CLI_LOG": str(root / "reviews/private/cli-calls.jsonl"), **(extra_env or {})}
    script = root / "scripts/review.py"
    argv = [sys.executable, str(script), "--reviewer", "codex", "--output-dir", str(output),
            "--timeout", str(timeout), *extra]
    if transport is not None:
        argv.extend(["--transport", transport])
    run = subprocess.run(argv, cwd=root, env=env, capture_output=True, text=True, timeout=20)
    receipt = json.loads((output / "receipt.json").read_text())
    return run, receipt, output


def test_codex_single_transport_binds_gpt_6_1_sol_high_and_audits_native_rollout(codex_workspace):
    run, receipt, output = run_fake_codex(
        codex_workspace, "success", transport="single", output_name="codex-single")
    assert run.returncode == 0, run.stderr
    assert receipt["status"] == "accepted"
    assert receipt["reviewer"] == "codex"
    assert receipt["requested_model"] == "gpt-6.1-sol"
    assert receipt["requested_reasoning_effort"] == "high"
    assert receipt["session_id"] == "01a1781a-e760-73b3-9db1-bbdc214acc4f"
    assert len(receipt["calls"]) == 1
    call = receipt["calls"][0]
    assert call["argv"] == review.codex_argv(receipt["cli_path"], new=True)
    assert "--ignore-user-config" in call["argv"]
    assert 'model_reasoning_effort="high"' in call["argv"]
    assert 'sandbox_mode="read-only"' in call["argv"]
    assert 'web_search="disabled"' in call["argv"]
    for feature in review.CODEX_DISABLED_FEATURES:
        idx = call["argv"].index(feature)
        assert call["argv"][idx - 1] == "--disable"
    payload = (output / "payload.md").read_bytes()
    assert payload == (output / "single-prompt.md").read_bytes()
    assert receipt["context_audit"]["native_model_id"] == "gpt-6.1-sol"
    assert receipt["context_audit"]["reasoning_effort"] == "high"
    assert receipt["context_audit"]["prompt_sha256"] == [review.digest(payload)]
    assert receipt["context_audit"]["compaction_count"] == 0
    assert receipt["context_audit"]["tool_call_count"] == 0
    assert "PRIVATE_CODEX_SENTINEL" not in (output / "receipt.json").read_text()
    assert (output / "review.json").exists()


def test_codex_chunks_transport_audits_all_turns_in_sequence(codex_workspace):
    root, _ = codex_workspace
    (root / "README.md").write_text("# Grüße ☀️\n" * 12000)
    run, receipt, _ = run_fake_codex(codex_workspace, "commentary", transport="chunks", output_name="codex-chunks")
    assert run.returncode == 0, run.stderr
    assert receipt["chunk_count"] > 1
    assert receipt["context_audit"]["prompt_count"] == receipt["chunk_count"] + 1
    assert receipt["context_audit"]["turn_completed_count"] == receipt["chunk_count"] + 1
    assert receipt["calls"][0]["argv"][:2] == [receipt["cli_path"], "exec"]
    assert receipt["calls"][1]["argv"][:3] == [receipt["cli_path"], "exec", "resume"]


@pytest.mark.parametrize("mode,reason", [
    ("missing_updates", "exactly one"),
    ("compaction", "detected compaction"),
    ("tool_call", "forbidden tool call"),
    ("stdout_tool", "forbidden tool call"),
    ("altered_prompt", "prompt bytes differ"),
    ("changed_unicode", "prompt bytes differ"),
    ("foreign_session", "foreign session"),
    ("subagent_session", "foreign session"),
    ("parent_thread", "foreign session"),
    ("truncated_updates", "truncated"),
    ("duplicate_session", "exactly one"),
    ("low_effort", "gpt-6.1-sol with high reasoning effort"),
    ("wrong_model", "gpt-6.1-sol with high reasoning effort"),
    ("wrong_approval", "gpt-6.1-sol with high reasoning effort"),
    ("wrong_sandbox", "gpt-6.1-sol with high reasoning effort"),
    ("extra_model_call", "one matching native model call"),
    ("no_task_complete", "turn completion metadata"),
    ("response_mismatch", "Native final response differs"),
    ("invalid_review", "Expecting value"),
    ("fail", "Codex failed (9)"),
])
def test_codex_failures_and_context_audit_violations_fail_closed(codex_workspace, mode, reason):
    run, receipt, output = run_fake_codex(codex_workspace, mode, transport="single", output_name=f"codex-fail-{mode}")
    assert run.returncode != 0
    assert receipt["status"] == "failed"
    assert reason in receipt["error"]
    assert not (output / "review.json").exists()


def test_codex_all_single_receipt_serves_as_verified_reference_for_implementation_scope(codex_workspace):
    root, _ = codex_workspace
    for index, name in enumerate(sorted(review.RESEARCH_FILES)):
        (root / name).write_text(f"Originalforschung {index}: Grüße ☀️\n")
    run, baseline, base_dir = run_fake_codex(codex_workspace, "success", transport="single", output_name="codex-base")
    assert run.returncode == 0, run.stderr
    (root / "README.md").write_text("# Geänderte Implementierungsdoku\n")
    run2, impl, impl_dir = run_fake_codex(
        codex_workspace, "success", transport="single", output_name="codex-impl",
        extra=("--scope", "implementation", "--reference-receipt", str(base_dir / "receipt.json")))
    assert run2.returncode == 0, run2.stderr
    assert impl["status"] == "accepted"
    assert impl["scope"] == "implementation"
    assert impl["reviewer"] == "codex"
    assert impl["reference"]["native_model_id"] == "gpt-6.1-sol"
    assert impl["reference"]["reasoning_effort"] == "high"
    assert impl["reference"]["receipt_sha256"] == review.digest((base_dir / "receipt.json").read_bytes())
    assert (impl_dir / "review.json").exists()

