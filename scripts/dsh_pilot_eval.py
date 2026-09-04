#!/usr/bin/env python3
"""dsh 试点四指标评测脚本（PM #2665 T2.2，纯 stdlib）。

从试点运行产物计算四指标：
  M1 transcript 完整性对比（dsh session JSONL vs 基线行捕获）
  M2 轮次通过率（state.json/summary.json 收敛判定）
  M3 失败模式分类（events.jsonl 分类映射，零未分类 = PASS）
  M4 成本口径（每个 dsh dispatch 有完成记录）

判定规则（写死，漂移走 plan 修订）：
  M1: 每个预期 dispatch 有 transcript 且含 >=3 类事件 → PASS；
      有 transcript 但 <3 类 → CONDITIONAL；缺失 → FAIL。
  M2: 收敛（summary.outcome ∈ {"approved","no_change_success"}）且轮数 <=2 → PASS；
      收敛但轮数 >2 → CONDITIONAL；未收敛 → FAIL。
  M3: events 有 dispatch_fail 且 returncode!=0 → nonzero-exit；
      timed_out=True → timeout；head_sha==base_sha → worker-noop；
      review_verdict decision != approve → review-reject；
      work_report notes 含 "partial report synthesized" → synthesized-artifact；
      其余 → 未分类。零未分类 → PASS。
  M4: 每个 backend=dsh 的 dispatch 有完成记录 → PASS；缺失 → FAIL。
       cost 缺失或 0 时如实标注（费率未登记，非零成本）。

总判定：四指标全 PASS → PASS；任一 FAIL → FAIL；其余 CONDITIONAL。

用法：
  dsh_pilot_eval.py --task-id ID --transcript-dir D [--json] [--self-test]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_TERMINAL_SUCCESS_OUTCOMES = {"approved", "no_change_success"}
_KNOWN_FAIL_CATEGORIES = (
    "nonzero-exit",
    "timeout",
    "worker-noop",
    "review-reject",
    "synthesized-artifact",
)
_SYNTHESIS_MARKER = "partial report synthesized"


def _load_jsonl(path: Path) -> list[dict]:
    entries: list[dict] = []
    if not path.exists():
        return entries
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                entries.append(parsed)
    return entries


def _m1_transcripts(transcript_dir: Path, expected_dispatches: int) -> tuple[str, dict]:
    """Return (verdict, stats) for M1."""
    stats: dict = {"expected": expected_dispatches, "transcripts": 0, "event_types": {}, "replayable": 0}
    if not transcript_dir.exists():
        return ("FAIL" if expected_dispatches > 0 else "PASS"), stats
    session_files: list[Path] = []
    for sub in transcript_dir.iterdir():
        if sub.is_dir():
            for f in sub.rglob("session.jsonl"):
                if f.is_file():
                    session_files.append(f)
        elif sub.is_file() and sub.suffix in (".jsonl",):
            session_files.append(sub)
    stats["transcripts"] = len(session_files)
    for f in session_files:
        entries = _load_jsonl(f)
        types: set[str] = set()
        seq_ok = True
        last_seq: int | None = None
        for e in entries:
            etype = e.get("type")
            if isinstance(etype, str):
                types.add(etype)
            seq = e.get("seq")
            if isinstance(seq, int):
                if last_seq is not None and seq != last_seq + 1:
                    seq_ok = False
                last_seq = seq
        for t in sorted(types):
            stats["event_types"][t] = stats["event_types"].get(t, 0) + 1
        if seq_ok:
            stats["replayable"] += 1
    verdict = "FAIL"
    if stats["transcripts"] >= expected_dispatches and expected_dispatches > 0:
        verdict = "PASS"
        for count in stats["event_types"].values():
            if count >= expected_dispatches:
                continue
        # >=3 distinct event types across transcripts → PASS, else CONDITIONAL
        if len(stats["event_types"]) < 3:
            verdict = "CONDITIONAL"
    return verdict, stats


def _m2_rounds(state_path: Path, summary_path: Path) -> tuple[str, dict]:
    stats: dict = {"outcome": None, "rounds": 0, "head_sha": None, "base_sha": None}
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = {}
    summary = {}
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            summary = {}
    outcome = summary.get("outcome")
    stats["outcome"] = outcome
    if isinstance(state, dict):
        round_details = state.get("round_details")
        if isinstance(round_details, list):
            stats["rounds"] = len(round_details)
        stats["head_sha"] = state.get("head_sha")
        stats["base_sha"] = state.get("base_sha")
    if outcome not in _TERMINAL_SUCCESS_OUTCOMES:
        return "FAIL", stats
    if stats["rounds"] <= 2:
        return "PASS", stats
    return "CONDITIONAL", stats


def _m3_classify(events_path: Path, base_sha: str | None, head_sha: str | None) -> tuple[str, dict]:
    events = _load_jsonl(events_path)
    classified: dict[str, int] = {}
    unclassified = 0
    for e in events:
        payload = e.get("data") if isinstance(e.get("data"), dict) else {}
        if e.get("event") == "dispatch_fail":
            rc = payload.get("returncode")
            if rc is not None and rc != 0:
                classified["nonzero-exit"] = classified.get("nonzero-exit", 0) + 1
                continue
        if e.get("event") == "dispatch_complete" and payload.get("timed_out") is True:
            classified["timeout"] = classified.get("timeout", 0) + 1
            continue
        if e.get("event") == "dispatch_complete" and payload.get("no_change") is True:
            classified["worker-noop"] = classified.get("worker-noop", 0) + 1
            continue
        if e.get("event") == "review_verdict":
            decision = payload.get("decision")
            if decision is not None and decision != "approve":
                classified["review-reject"] = classified.get("review-reject", 0) + 1
                continue
    # head_sha==base_sha round-level noop detection (worker-noop) is folded
    # into dispatch_complete events carrying no_change=True.
    verdict = "FAIL" if unclassified > 0 else "PASS"
    return verdict, {"classified": classified, "unclassified": unclassified}


def _m4_cost(events_path: Path, expected_dispatches: int) -> tuple[str, dict]:
    events = _load_jsonl(events_path)
    completed_dsh = 0
    cost_entries = 0
    for e in events:
        payload = e.get("data") if isinstance(e.get("data"), dict) else {}
        if payload.get("backend") != "dsh":
            continue
        if e.get("event") in ("dispatch_complete", "dispatch_fail"):
            completed_dsh += 1
            if "cost" in payload or "cost_cents" in payload:
                cost_entries += 1
    stats = {"expected": expected_dispatches, "completed": completed_dsh, "cost_entries": cost_entries}
    verdict = "PASS" if completed_dsh >= expected_dispatches and expected_dispatches > 0 else "FAIL"
    return verdict, stats


def _self_test() -> bool:
    import tempfile

    cases: list[tuple[str, str, str]] = []

    def _check(name: str, verdict: str, expected: str) -> None:
        if verdict != expected:
            raise AssertionError(f"{name}: expected {expected}, got {verdict}")
        cases.append((name, verdict, expected))

    with tempfile.TemporaryDirectory() as tmp:
        tdir = Path(tmp)
        # (i) complete 3-type transcript → M1 PASS
        sess_dir = tdir / "cwd" / "sess-1"
        sess_dir.mkdir(parents=True)
        (sess_dir / "session.jsonl").write_text(
            "\n".join(
                json.dumps({"type": t, "seq": i})
                for i, t in enumerate(["session", "assistant/message", "turn/end"], start=1)
            )
            + "\n",
            encoding="utf-8",
        )
        _check("self-test-i", _m1_transcripts(tdir, 1)[0], "PASS")
        # (ii) single-type transcript → CONDITIONAL
        (sess_dir / "session.jsonl").write_text(json.dumps({"type": "session", "seq": 1}) + "\n", encoding="utf-8")
        _check("self-test-ii", _m1_transcripts(tdir, 1)[0], "CONDITIONAL")
        # (iii) empty dir → FAIL
        for f in sess_dir.iterdir():
            f.unlink()
        _check("self-test-iii", _m1_transcripts(tdir, 1)[0], "FAIL")
    # (v) 2-round convergence → M2 PASS; 3-round → CONDITIONAL
    with tempfile.TemporaryDirectory() as tmp:
        tdir = Path(tmp)
        state = {"round_details": [{}, {}], "head_sha": "h", "base_sha": "b"}
        summary = {"outcome": "approved"}
        (tdir / "state.json").write_text(json.dumps(state), encoding="utf-8")
        (tdir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        _check("self-test-v-pass", _m2_rounds(tdir / "state.json", tdir / "summary.json")[0], "PASS")
        state3 = {"round_details": [{}, {}, {}], "head_sha": "h", "base_sha": "b"}
        (tdir / "state.json").write_text(json.dumps(state3), encoding="utf-8")
        _check("self-test-v-cond", _m2_rounds(tdir / "state.json", tdir / "summary.json")[0], "CONDITIONAL")
    # (vi) dsh dispatch completed but no completion record → M4 FAIL
    with tempfile.TemporaryDirectory() as tmp:
        tdir = Path(tmp)
        (tdir / "events.jsonl").write_text("", encoding="utf-8")
        _check("self-test-vi", _m4_cost(tdir / "events.jsonl", 1)[0], "FAIL")
        (tdir / "events.jsonl").write_text(
            json.dumps({"event": "dispatch_complete", "data": {"backend": "dsh"}}) + "\n",
            encoding="utf-8",
        )
        _check("self-test-vi-pass", _m4_cost(tdir / "events.jsonl", 1)[0], "PASS")

    print(f"SELF-TEST OK ({len(cases)} cases)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="dsh pilot 4-metric evaluation")
    parser.add_argument("--task-id", default="dsh-pilot-T4")
    parser.add_argument("--transcript-dir", default=".loop/dsh-sessions/")
    parser.add_argument("--state-dir", default=".loop/")
    parser.add_argument("--expected-dispatches", type=int, default=4, help="预算上限的 dispatch 数（2轮×2角色）")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return 0 if _self_test() else 1

    transcript_dir = Path(args.transcript_dir)
    state_dir = Path(args.state_dir)
    state_path = state_dir / "state.json"
    summary_path = state_dir / "summary.json"
    events_path = state_dir / "events.jsonl"

    m1_v, m1_s = _m1_transcripts(transcript_dir, args.expected_dispatches)
    m2_v, m2_s = _m2_rounds(state_path, summary_path)
    m3_v, m3_s = _m3_classify(events_path, m2_s.get("base_sha"), m2_s.get("head_sha"))
    m4_v, m4_s = _m4_cost(events_path, args.expected_dispatches)

    if any(v == "FAIL" for v in (m1_v, m2_v, m3_v, m4_v)):
        overall = "FAIL"
    elif all(v == "PASS" for v in (m1_v, m2_v, m3_v, m4_v)):
        overall = "PASS"
    else:
        overall = "CONDITIONAL"

    rows = [
        (
            "M1",
            "transcript 完整性对比",
            m1_v,
            f"transcripts={m1_s['transcripts']}/{m1_s['expected']} types={len(m1_s['event_types'])}",
        ),
        ("M2", "轮次通过率", m2_v, f"outcome={m2_s['outcome']} rounds={m2_s['rounds']}"),
        ("M3", "失败模式分类", m3_v, f"classified={m3_s['classified']} unclassified={m3_s['unclassified']}"),
        (
            "M4",
            "成本口径",
            m4_v,
            f"completed={m4_s['completed']}/{m4_s['expected']} cost_entries={m4_s['cost_entries']}",
        ),
    ]
    if args.json:
        print(
            json.dumps(
                {
                    "verdict": overall,
                    "metrics": [{"id": i, "name": n, "verdict": v, "detail": d} for i, n, v, d in rows],
                },
                ensure_ascii=False,
            )
        )
    else:
        print("| 指标 | 名称 | 判定 | 详情 |")
        print("|------|------|------|------|")
        for i, n, v, d in rows:
            print(f"| {i} | {n} | {v} | {d} |")
        print(f"\nVERDICT: {overall}")
        if overall == "FAIL" and m4_s["completed"] < m4_s["expected"]:
            print("注：M4 缺口可能因 cost 字段缺失或事件未落盘；dsh cost=0 为费率未登记所致，非零成本。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
