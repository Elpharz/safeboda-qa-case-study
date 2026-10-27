#!/usr/bin/env python3
"""API coverage report: answers five questions about the suite and writes COVERAGE.md + reports/coverage.html.

  1. Operation coverage   which documented operations (method + path) the tests actually called
  2. Contract coverage    which documented (operation, status) responses were seen and schema-validated,
                          which request/response schemas were exercised, and any schema mismatches
  3. Behaviour coverage   positive / negative / boundary / state (+ concurrency) test cases per operation
  4. Execution status     passed / failed / skipped / blocked (env) / xfailed / xpassed per case
  5. Defect status        confirmed / under_investigation / spec_gap from known_bugs.json, plus untriaged failures

Inputs (all produced by a normal `pytest` run, see conftest.py):
  openapi.json               vendored spec
  reports/api_calls.json     every HTTP call: operation, status, schema validated?, schema ok?, test id
  reports/collected.json     every collected test id and its markers
  reports/junit.xml          outcomes
  known_bugs.json            defect registry

    python coverage_report.py                    # defaults above
    python coverage_report.py --junit other.xml --out-md COVERAGE.md --out-html reports/coverage.html
"""
import argparse
import html
import json
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
BEHAVIOUR = ["positive", "negative", "boundary", "state", "concurrency"]
EXEC = ["passed", "failed", "error", "skipped", "blocked", "xfailed", "xpassed"]
DEFECT = ["confirmed", "under_investigation", "spec_gap"]
COLORS = {"passed": "green", "failed": "red", "error": "red", "xpassed": "red", "skipped": "orange", "xfailed": "orange",
          "blocked": "#999", "positive": "#4caf50", "negative": "red", "boundary": "orange", "state": "#5b7db1",
          "concurrency": "#8e5bb1", "confirmed": "red", "under_investigation": "orange", "spec_gap": "#5b7db1",
          "covered": "#4caf50", "uncovered": "#e6e6e6"}


# ------------------------------------------------------------------------------------------- inputs
def load_spec(path):
    spec = json.loads(Path(path).read_text())
    ops = {}
    for p, item in spec["paths"].items():
        for m, op in item.items():
            if m.upper() not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                continue
            name = f"{m.upper()} {p}"
            req = (op.get("requestBody") or {}).get("content", {}).get("application/json", {}).get("schema")
            resp = {c: (r.get("content") or {}).get("application/json", {}).get("schema") for c, r in op.get("responses", {}).items()}
            ops[name] = {"req": req, "resp": resp, "summary": op.get("summary", "")}
    return spec, ops


def refs(schema, comps, seen=None):
    """Component schema names reachable from a schema."""
    seen = set() if seen is None else seen
    if isinstance(schema, dict):
        r = schema.get("$ref")
        if r:
            n = r.split("/")[-1]
            if n not in seen:
                seen.add(n)
                refs(comps.get(n, {}), comps, seen)
        for v in schema.values():
            refs(v, comps, seen)
    elif isinstance(schema, list):
        for v in schema:
            refs(v, comps, seen)
    return seen


def load_junit(path):
    res = {}
    if not path or not Path(path).exists():
        return res
    for tc in ET.parse(path).iter("testcase"):
        cls = tc.get("classname", "")
        nodeid = cls.replace(".", "/") + ".py::" + tc.get("name")
        st = "passed"
        for ch in tc:
            msg = (ch.get("message") or "") + " " + (ch.text or "")
            if ch.tag in ("failure", "error") and "SandboxUnavailable" in msg:
                st = "blocked"  # network failure talking to the sandbox: environment, not a product result
            elif ch.tag == "failure":
                st = "xpassed" if "XPASS(strict)" in msg else "failed"
            elif ch.tag == "error":
                st = "error"
            elif ch.tag == "skipped":
                if ch.get("type") == "pytest.xfail":
                    st = "xfailed"
                elif "blocked: env" in msg:
                    st = "blocked"
                else:
                    st = "skipped"
        res[nodeid] = st
    return res


def fn_id(nodeid):
    return nodeid.split("[")[0]


# ------------------------------------------------------------------------------------------- model
def build(a):
    spec, ops = load_spec(a.spec)
    comps = spec.get("components", {}).get("schemas", {})
    calls = json.loads(Path(a.calls).read_text()) if Path(a.calls).exists() else []
    collected = json.loads(Path(a.collected).read_text()) if Path(a.collected).exists() else {}
    junit = load_junit(a.junit)
    known = json.loads(Path(a.known_bugs).read_text()) if Path(a.known_bugs).exists() else {}
    known = {k: v for k, v in known.items() if not k.startswith("_")}

    per_op = {o: {"tests": set(), "calls": 0, "statuses": Counter(), "validated": 0, "mismatch": 0, "mismatch_tests": set()}
              for o in ops}
    undocumented = Counter()
    for c in calls:
        o = c["op"]
        if o not in per_op:
            undocumented[(o, c["status"])] += 1
            continue
        d = per_op[o]
        d["calls"] += 1
        d["statuses"][str(c["status"])] += 1
        if c.get("test"):
            d["tests"].add(c["test"])
        if c["validated"]:
            d["validated"] += 1
        if not c["schema_ok"]:
            d["mismatch"] += 1
            d["mismatch_tests"].add(c["test"])
        if not c["documented"]:
            undocumented[(o, c["status"])] += 1

    # 1 + 2
    status_pairs = [(o, s) for o, info in ops.items() for s in info["resp"]]
    seen_pairs = [(o, s) for o, s in status_pairs if per_op[o]["statuses"][s]]
    resp_schemas_seen, req_schemas_seen = set(), set()
    for o, info in ops.items():
        for s, sch in info["resp"].items():
            if per_op[o]["statuses"][s] and sch:
                resp_schemas_seen |= refs(sch, comps)
        if per_op[o]["calls"] and info["req"]:
            req_schemas_seen |= refs(info["req"], comps)
    all_comp = set(comps)

    # 3 behaviour per op (test cases that called the op), from collected markers
    beh = {o: Counter() for o in ops}
    for o in ops:
        for t in per_op[o]["tests"]:
            for m in collected.get(t, []):
                if m in BEHAVIOUR:
                    beh[o][m] += 1
    suite_beh = Counter(m for t, ms in collected.items() for m in ms if m in BEHAVIOUR)
    untagged = [t for t, ms in collected.items() if not set(ms) & set(BEHAVIOUR[:4])]

    # 4 execution
    exec_counts = Counter(junit.values())
    # 5 defects
    bugs = defaultdict(lambda: {"tests": [], "statuses": set()})
    for nodeid, e in known.items():
        b = bugs[e["id"]]
        b.update({k: e.get(k) for k in ("severity", "summary", "review_by", "ticket")})
        b["tests"].append(nodeid)
        b["statuses"].add(e.get("status"))
    problems = [f"{bid} has conflicting statuses {sorted(b['statuses'])}" for bid, b in bugs.items() if len(b["statuses"]) > 1]
    for b in bugs.values():
        b["status"] = sorted(b["statuses"])[0]
        b["latest"] = Counter(st for nid, st in junit.items() if nid in b["tests"] or fn_id(nid) in b["tests"])
    registered = set(known)
    untriaged = sorted({fn_id(n) for n, st in junit.items() if st in ("failed", "error")
                        and n not in registered and fn_id(n) not in registered})
    return dict(spec=spec, ops=ops, per_op=per_op, status_pairs=status_pairs, seen_pairs=seen_pairs, undocumented=undocumented,
                resp_schemas_seen=resp_schemas_seen, req_schemas_seen=req_schemas_seen, all_comp=all_comp, beh=beh,
                suite_beh=suite_beh, collected=collected, untagged=untagged, junit=junit, exec_counts=exec_counts,
                bugs=dict(bugs), problems=problems, untriaged=untriaged, calls=calls)


# ------------------------------------------------------------------------------------------- markdown
def pct(n, d):
    return f"{(100 * n / d if d else 0):.0f}%"


def to_md(M):
    ops, P = M["ops"], M["per_op"]
    cov = [o for o in ops if P[o]["calls"]]
    n429 = sum(1 for o, s in M["status_pairs"] if s == "429")
    seen_no429 = sum(1 for o, s in M["seen_pairs"] if s != "429")
    validated = sum(P[o]["validated"] for o in ops)
    mism = sum(P[o]["mismatch"] for o in ops)
    total_calls = sum(P[o]["calls"] for o in ops)
    L = []
    w = L.append
    w(f"# API coverage report\n\nSpec: {M['spec']['info']['title']} v{M['spec']['info']['version']}. "
      f"Generated {datetime.now().strftime('%d %b %Y %H:%M')} (box time, EAT) by `coverage_report.py` from the last pytest run.\n")
    w("## Summary\n")
    w("| Question | Answer |\n|---|---|")
    w(f"| 1. Operation coverage | **{len(cov)} of {len(ops)}** documented operations called by tests |")
    w(f"| 2. Contract coverage | **{len(M['seen_pairs'])} of {len(M['status_pairs'])}** documented (operation, status) responses seen "
      f"({seen_no429} of {len(M['status_pairs']) - n429} excluding 429, which is deliberately not tested); "
      f"**{validated} of {total_calls}** responses schema-validated, **{mism}** mismatches; "
      f"response schemas {len(M['resp_schemas_seen'])} of {len(M['all_comp'])}, request schemas {len(M['req_schemas_seen'])} exercised |")
    sb = M["suite_beh"]
    w(f"| 3. Behaviour coverage | test cases: " + ", ".join(f"{b} {sb[b]}" for b in BEHAVIOUR) +
      f"; untagged {len(M['untagged'])} |")
    ec = M["exec_counts"]
    w(f"| 4. Execution status | {sum(ec.values())} cases: " + ", ".join(f"{k} {ec[k]}" for k in EXEC if ec[k]) + " |")
    bs = Counter(b["status"] for b in M["bugs"].values())
    w(f"| 5. Defect status | {len(M['bugs'])} registered defects: " + ", ".join(f"{k.replace('_', ' ')} {bs[k]}" for k in DEFECT) +
      f"; untriaged failing tests {len(M['untriaged'])} |\n")

    w(f"## 1. Operation coverage ({len(cov)} of {len(ops)})\n")
    w("| Operation | Test cases | Calls | Documented statuses | Seen | Not seen |\n|---|---|---|---|---|---|")
    for o, info in ops.items():
        doc = list(info["resp"])
        seen = [s for s in doc if P[o]["statuses"][s]]
        w(f"| `{o}` | {len(P[o]['tests'])} | {P[o]['calls']} | {', '.join(doc)} | {', '.join(seen) or '-'} | "
          f"{', '.join(s for s in doc if s not in seen) or '-'} |")
    w("")
    w(f"## 2. Contract coverage\n\nEvery response is validated in `qa_api.Contract` against the schema the spec documents for that "
      f"operation and status (undocumented 4xx/5xx are checked against `Error`). A mismatch fails the test.\n")
    w("| Operation | Request schema | Validated responses | Schema mismatches | Tests with mismatches |\n|---|---|---|---|---|")
    for o, info in ops.items():
        req = info["req"].get("$ref", "inline").split("/")[-1] if info["req"] else "-"
        mt = ", ".join(f"`{t.split('::')[-1]}`" for t in sorted(P[o]["mismatch_tests"])[:4])
        w(f"| `{o}` | {req} | {P[o]['validated']} / {P[o]['calls']} | {P[o]['mismatch']} | {mt or '-'} |")
    w(f"\nComponent schemas exercised in responses: {', '.join(sorted(M['resp_schemas_seen']))}.")
    w(f"Exercised in requests: {', '.join(sorted(M['req_schemas_seen']))}.")
    never = sorted(M["all_comp"] - M["resp_schemas_seen"] - M["req_schemas_seen"])
    w(f"Never exercised: {', '.join(never) or 'none'}.\n")
    if M["undocumented"]:
        w("Undocumented statuses returned by the API (each is a contract finding):\n")
        w("| Operation | Status | Times |\n|---|---|---|")
        for (o, s), n in sorted(M["undocumented"].items()):
            w(f"| `{o}` | {s} | {n} |")
        w("")
    w("## 3. Behaviour coverage (test cases per operation)\n")
    w("| Operation | " + " | ".join(BEHAVIOUR) + " |\n|---|" + "---|" * len(BEHAVIOUR))
    for o in ops:
        w(f"| `{o}` | " + " | ".join(str(M["beh"][o][b]) for b in BEHAVIOUR) + " |")
    w("\nA test case counts for every operation it calls (a booking journey counts for estimates, trips and the driver steps). "
      "Markers are set by hand per test or per `pytest.param`; conftest refuses to collect a test without one.\n")
    w("## 4. Execution status\n")
    w("| Status | Cases |\n|---|---|")
    for k in EXEC:
        w(f"| {k} | {ec[k]} |")
    bad = sorted(n for n, s in M["junit"].items() if s in ("failed", "error", "xpassed"))
    w(f"\nFailing cases ({len(bad)}):\n")
    for n in bad:
        w(f"- `{n}`")
    w("\n## 5. Defect status\n")
    if M["problems"]:
        w("**Registry problems:** " + "; ".join(M["problems"]) + "\n")
    w("| Defect | Severity | Status | Summary | Tests | Latest result |\n|---|---|---|---|---|---|")
    for bid, b in sorted(M["bugs"].items(), key=lambda kv: (kv[0].startswith("TEST"), int(re.sub(r"\D", "", kv[0]) or 0))):
        lat = ", ".join(f"{k} {v}" for k, v in b["latest"].items()) or "not run"
        w(f"| {bid} | {b['severity']} | {b['status'].replace('_', ' ')} | {b['summary']} | "
          f"{'<br>'.join('`' + t.split('::')[-1] + '`' for t in b['tests'])} | {lat} |")
    w(f"\nUntriaged failing tests (failing, not in known_bugs.json): {len(M['untriaged'])}")
    for t in M["untriaged"]:
        w(f"- `{t}`")
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------------------------------- html
CSS = """
body{font-family:Helvetica,Arial,sans-serif;font-size:12px;min-width:800px;color:#999;margin:8px 16px}
h1{font-size:24px;color:black}h2{font-size:16px;color:black;margin-top:28px}h3{font-size:13px;color:black;margin:0 0 8px}
p{color:black}a{color:#999}table{border-collapse:collapse}
.cards{display:flex;flex-wrap:wrap;gap:10px;margin:10px 0}
.card{border:1px solid #e6e6e6;padding:10px 14px;min-width:150px;flex:1 1 150px;background:#fff}
.card .q{color:#999}.card .big{font-size:24px;color:black;font-weight:bold;margin:4px 0}.card .sub{color:#999}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:12px}
.panel{border:1px solid #e6e6e6;padding:10px 12px}
.results{border:1px solid #e6e6e6;color:#999;font-size:12px;width:100%;margin-top:6px}
.results th,.results td{padding:5px;border:1px solid #e6e6e6;text-align:left;vertical-align:top}
.results th{font-weight:bold}.results tr:nth-child(even) td{background:#f6f6f6}
.passed{color:green}.failed,.error,.xpassed,.confirmed{color:red}.skipped,.xfailed,.under_investigation{color:orange}
.blocked{color:#999}.spec_gap{color:#5b7db1}
code{color:black}.legend span{margin-right:12px}.sw{display:inline-block;width:10px;height:10px;margin-right:4px;vertical-align:middle}
"""


def bar(segments, width=300, height=12):
    """Stacked horizontal bar as inline SVG. segments: [(value, color, title)]"""
    total = sum(v for v, _, _ in segments) or 1
    x, parts = 0.0, []
    for v, c, t in segments:
        wv = width * v / total
        if wv > 0:
            parts.append(f'<rect x="{x:.1f}" y="0" width="{wv:.1f}" height="{height}" fill="{c}"><title>{html.escape(t)}: {v}</title></rect>')
        x += wv
    return f'<svg width="{width}" height="{height}" role="img">{"".join(parts)}</svg>'


def donut(segments, size=120):
    total = sum(v for v, _, _ in segments) or 1
    r, cx = size / 2 - 10, size / 2
    circ = 2 * math.pi * r
    off, parts = 0.0, []
    for v, c, t in segments:
        if v <= 0:
            continue
        ln = circ * v / total
        parts.append(f'<circle r="{r:.1f}" cx="{cx}" cy="{cx}" fill="none" stroke="{c}" stroke-width="16" '
                     f'stroke-dasharray="{ln:.2f} {circ - ln:.2f}" stroke-dashoffset="{-off:.2f}" '
                     f'transform="rotate(-90 {cx} {cx})"><title>{html.escape(t)}: {v}</title></circle>')
        off += ln
    label = f'<text x="{cx}" y="{cx + 5}" text-anchor="middle" font-size="16" fill="black">{total}</text>'
    return f'<svg width="{size}" height="{size}">{"".join(parts)}{label}</svg>'


def legend(items):
    return '<div class="legend">' + "".join(f'<span><i class="sw" style="background:{c}"></i>{html.escape(t)}</span>' for t, c in items) + "</div>"


def to_html(M):
    ops, P = M["ops"], M["per_op"]
    e = html.escape
    cov = [o for o in ops if P[o]["calls"]]
    validated = sum(P[o]["validated"] for o in ops)
    total_calls = sum(P[o]["calls"] for o in ops)
    mism = sum(P[o]["mismatch"] for o in ops)
    n429 = sum(1 for o, s in M["status_pairs"] if s == "429")
    seen_no429 = sum(1 for o, s in M["seen_pairs"] if s != "429")
    ec, sb = M["exec_counts"], M["suite_beh"]
    bs = Counter(b["status"] for b in M["bugs"].values())
    H = []
    w = H.append
    w(f'<!DOCTYPE html><html><head><meta charset="utf-8"/><title>coverage.html</title><style>{CSS}</style></head><body>')
    w('<h1>coverage.html</h1>')
    w(f'<p>Report generated on {datetime.now().strftime("%d-%b-%Y at %H:%M:%S")} (EAT) by coverage_report.py from the last pytest run. '
      f'Spec: {e(M["spec"]["info"]["title"])} v{e(M["spec"]["info"]["version"])}.</p>')
    w("<h2>Summary</h2><div class='cards'>")
    cards = [
        ("1. Operations covered", f"{len(cov)} / {len(ops)}", "documented operations called"),
        ("2. Responses seen", f"{len(M['seen_pairs'])} / {len(M['status_pairs'])}", f"{seen_no429} / {len(M['status_pairs']) - n429} excl. 429"),
        ("2. Schema-validated", f"{validated} / {total_calls}", f"{mism} mismatches"),
        ("3. Behaviour tags", f"{len(M['collected']) - len(M['untagged'])} / {len(M['collected'])}", "test cases tagged"),
        ("4. Executed", f"{sum(ec.values())}", " ".join(f'<span class="{k}">{ec[k]} {k}</span>' for k in EXEC if ec[k])),
        ("5. Defects", f"{len(M['bugs'])}", " ".join(f'<span class="{k}">{bs[k]} {k.replace("_", " ")}</span>' for k in DEFECT)),
    ]
    for q, big, sub in cards:
        w(f"<div class='card'><div class='q'>{q}</div><div class='big'>{big}</div><div class='sub'>{sub}</div></div>")
    w("</div><div class='grid'>")
    # execution + defect donuts
    w("<div class='panel'><h3>4. Execution status</h3><div style='display:flex;gap:16px;align-items:center'>")
    w(donut([(ec[k], COLORS[k], k) for k in EXEC]))
    w(legend([(f"{k} {ec[k]}", COLORS[k]) for k in EXEC if ec[k]]) + "</div></div>")
    w("<div class='panel'><h3>5. Defect status</h3><div style='display:flex;gap:16px;align-items:center'>")
    w(donut([(bs[k], COLORS[k], k) for k in DEFECT]))
    sev = Counter(b["severity"] for b in M["bugs"].values())
    w(legend([(f"{k.replace('_', ' ')} {bs[k]}", COLORS[k]) for k in DEFECT]) +
      f"<div style='margin-left:8px'>Severity: {', '.join(f'{k} {v}' for k, v in sorted(sev.items()))}<br>"
      f"Untriaged failing tests: {len(M['untriaged'])}</div></div></div>")
    w("</div>")
    # operation table with bars
    w("<h2>1-3. Per operation</h2>")
    w(legend([("status seen", COLORS["covered"]), ("documented, not seen", COLORS["uncovered"])] +
             [(b, COLORS[b]) for b in BEHAVIOUR]))
    w("<table class='results'><tr><th>Operation</th><th>Cases</th><th>Calls</th><th>Status-code coverage</th><th>Not seen</th>"
      "<th>Schema-validated</th><th>Mismatches</th><th>Behaviour mix (cases)</th></tr>")
    for o, info in ops.items():
        d = P[o]
        doc = list(info["resp"])
        seen = [s for s in doc if d["statuses"][s]]
        sc = bar([(len(seen), COLORS["covered"], "seen"), (len(doc) - len(seen), COLORS["uncovered"], "not seen")], 120)
        bm = bar([(M["beh"][o][b], COLORS[b], b) for b in BEHAVIOUR], 200)
        mm = f"<span class='failed'>{d['mismatch']}</span>" if d["mismatch"] else "0"
        cls = "" if d["calls"] else " class='failed'"
        w(f"<tr><td{cls}><code>{e(o)}</code></td><td>{len(d['tests'])}</td><td>{d['calls']}</td><td>{sc} {len(seen)}/{len(doc)}</td>"
          f"<td>{', '.join(s for s in doc if s not in seen) or '-'}</td><td>{d['validated']}</td><td>{mm}</td><td>{bm}</td></tr>")
    w("</table>")
    w(f"<p>Component schemas exercised: responses {len(M['resp_schemas_seen'])} of {len(M['all_comp'])}, requests "
      f"{len(M['req_schemas_seen'])}. Never exercised: {e(', '.join(sorted(M['all_comp'] - M['resp_schemas_seen'] - M['req_schemas_seen'])) or 'none')}. "
      f"429 is deliberately not tested (shared rate limit).</p>")
    if M["undocumented"]:
        w("<h3>Undocumented statuses returned (contract findings)</h3><table class='results'><tr><th>Operation</th><th>Status</th><th>Times</th></tr>")
        for (o, s), n in sorted(M["undocumented"].items()):
            w(f"<tr><td><code>{e(o)}</code></td><td class='failed'>{s}</td><td>{n}</td></tr>")
        w("</table>")
    # behaviour suite totals
    w("<h2>3. Behaviour mix (whole suite)</h2>")
    mx = max(sb.values() or [1])
    w("<table class='results' style='width:auto'>")
    for b in BEHAVIOUR:
        w(f"<tr><td>{b}</td><td>{bar([(sb[b], COLORS[b], b), (mx - sb[b], '#f6f6f6', '')], 300)}</td><td>{sb[b]}</td></tr>")
    w("</table>")
    # defects
    w("<h2>5. Defects</h2><table class='results'><tr><th>Defect</th><th>Severity</th><th>Status</th><th>Summary</th><th>Tests</th><th>Latest result</th></tr>")
    for bid, b in sorted(M["bugs"].items(), key=lambda kv: (kv[0].startswith("TEST"), int(re.sub(r"\D", "", kv[0]) or 0))):
        lat = ", ".join(f"<span class='{k}'>{k} {v}</span>" for k, v in b["latest"].items()) or "not run"
        w(f"<tr><td>{e(bid)}</td><td>{e(str(b['severity']))}</td><td class='{b['status']}'>{e(b['status'].replace('_', ' '))}</td>"
          f"<td>{e(b['summary'] or '')}</td><td>{'<br>'.join('<code>' + e(t.split('::')[-1]) + '</code>' for t in b['tests'])}</td><td>{lat}</td></tr>")
    w("</table>")
    if M["untriaged"]:
        w("<p class='failed'>Untriaged failing tests: " + ", ".join(f"<code>{e(t)}</code>" for t in M["untriaged"]) + "</p>")
    # failing cases
    bad = sorted((n, s) for n, s in M["junit"].items() if s in ("failed", "error", "xpassed", "blocked"))
    w(f"<h2>4. Non-passing cases ({len(bad)})</h2><table class='results'><tr><th>Result</th><th>Test</th></tr>")
    for n, s in bad:
        w(f"<tr><td class='{s}'>{s}</td><td><code>{e(n)}</code></td></tr>")
    w("</table></body></html>")
    return "".join(H)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", default=ROOT / "openapi.json")
    ap.add_argument("--calls", default=ROOT / "reports/api_calls.json")
    ap.add_argument("--collected", default=ROOT / "reports/collected.json")
    ap.add_argument("--junit", default=ROOT / "reports/junit.xml")
    ap.add_argument("--known-bugs", default=ROOT / "known_bugs.json")
    ap.add_argument("--out-md", default=ROOT / "reports/COVERAGE.md")
    ap.add_argument("--out-html", default=ROOT / "reports/coverage.html")
    a = ap.parse_args()
    M = build(a)
    Path(a.out_md).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out_md).write_text(to_md(M))
    Path(a.out_html).write_text(to_html(M))
    print(f"wrote {a.out_md} and {a.out_html}")
    if M["problems"]:
        raise SystemExit("known_bugs.json problems: " + "; ".join(M["problems"]))


if __name__ == "__main__":
    main()
