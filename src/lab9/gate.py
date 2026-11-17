"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def _bad_number(v) -> bool:
    return isinstance(v, float) and not math.isfinite(v)


def _report_problems(rep: dict, spec: dict, who: str) -> list[str]:
    """Checks one report against itself: values, row count, duplicates, crashed graders, and whether
    its headline metrics really are the aggregate of its rows."""
    problems: list[str] = []
    metrics, rows, man = rep.get("metrics") or {}, rep.get("rows") or [], rep.get("manifest") or {}
    problems += [f"{who} metric {k} is {v!r} (NaN/inf)" for k, v in metrics.items() if _bad_number(v)]
    if rep.get("evaluator_failures"):
        problems.append(f"{who} has {len(rep['evaluator_failures'])} evaluator failure(s), "
                        f"first: {str(rep['evaluator_failures'][0])[:80]}")
    try:
        want = int(man["items"]) * len(man["seeds"])
    except (KeyError, TypeError, ValueError):
        problems.append(f"{who} manifest lacks items/seeds")
        want = None
    if want is not None and len(rows) != want:
        problems.append(f"{who} has {len(rows)} rows, manifest says {man['items']} items x {len(man['seeds'])} seeds = {want}")
    keys = Counter((r.get("item_id"), r.get("seed")) for r in rows)
    dup = sorted(k for k, n in keys.items() if n > 1)
    if dup:
        problems.append(f"{who} has duplicated (item, seed) rows, e.g. {dup[0]}")
    if man.get("seeds") is not None and {s for _, s in keys} - set(man["seeds"]):
        problems.append(f"{who} rows carry seeds outside the manifest {man['seeds']}")
    if want is not None and man.get("items") is not None and len({i for i, _ in keys}) != int(man["items"]):
        problems.append(f"{who} rows cover {len({i for i, _ in keys})} items, manifest says {man['items']}")
    graded = [m["id"] for m in spec.get("metrics") or [] if m["id"] in GRADERS]
    for m in graded:
        broken = [r for r in rows if not isinstance(r.get(m), bool)]
        if broken:
            r = broken[0]
            problems.append(f"{who} metric {m} is {r.get(m)!r} on {len(broken)} row(s), e.g. "
                            f"{r.get('item_id')}@{r.get('seed')} (a crashed grader must not drop out of the mean)")
    # The headline numbers must be what the rows say; an edited metric with untouched rows is a lie.
    if rows and not problems:
        ids = [m for m in metrics if m in GRADERS and all(m in r for r in rows)]
        has_cost = all(isinstance(r.get("cost"), (int, float)) for r in rows)
        again = aggregate([r if has_cost else {**r, "cost": 0.0} for r in rows], ids,
                          k_values=[k for k in spec.get("pass_k") or [] if f"pass_hat_{k}" in metrics])
        for k, v in again.items():
            if k not in metrics or (k == "cost_per_success" and not has_cost):
                continue
            got = metrics[k]
            same = (got is None and v is None) or (isinstance(got, (int, float)) and isinstance(v, (int, float))
                                                    and abs(got - v) <= 1e-6)
            if not same:
                problems.append(f"{who} metric {k} = {got!r} but its rows aggregate to {v!r}")
    return problems


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    """Same eval set => thresholds may only get stricter. Renaming eval_set_version does not escape
    the ratchet while the eval set file stays the same."""
    same_set = (spec.get("eval_set_version") == base_spec.get("eval_set_version")
                or (spec.get("eval_set") is not None and spec.get("eval_set") == base_spec.get("eval_set")))
    if not same_set:
        return []
    problems: list[str] = []

    def compare(where: str, old: dict, new: dict | None) -> None:
        if new is None:
            problems.append(f"RATCHET {where} removed")
            return
        if old.get("blocking") and not new.get("blocking"):
            problems.append(f"RATCHET {where} no longer blocking")
        ot, nt = old.get("threshold", old), new.get("threshold", new)
        for key in ("max", "max_increase"):
            if key in ot and (key not in nt or nt[key] > ot[key]):
                problems.append(f"RATCHET {where} {key} loosened {ot[key]} -> {nt.get(key)}")
        if "min" in ot and ("min" not in nt or nt["min"] < ot["min"]):
            problems.append(f"RATCHET {where} min loosened {ot['min']} -> {nt.get('min')}")
        if ot.get("no_significant_drop") and not nt.get("no_significant_drop"):
            problems.append(f"RATCHET {where} dropped no_significant_drop")
        if "metric" in old and new.get("metric") != old["metric"]:
            problems.append(f"RATCHET {where} metric changed {old['metric']} -> {new.get('metric')}")

    new_metrics = {m["id"]: m for m in spec.get("metrics") or []}
    for m in base_spec.get("metrics") or []:
        compare(f"metric {m['id']}", m, new_metrics.get(m["id"]))
    new_slices = {(s["name"], s.get("metric")): s for s in spec.get("slices") or []}
    for s in base_spec.get("slices") or []:
        compare(f"slice {s['name']}/{s.get('metric')}", s, new_slices.get((s["name"], s.get("metric"))))
    if set(base_spec.get("seeds") or []) - set(spec.get("seeds") or []):
        problems.append(f"RATCHET seeds shrank {base_spec.get('seeds')} -> {spec.get('seeds')}")
    ob, nb = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    if nb.get("confidence", 0.95) > ob.get("confidence", 0.95):
        problems.append(f"RATCHET bootstrap confidence widened {ob.get('confidence')} -> {nb.get('confidence')}")
    if nb.get("n_resamples", 1000) < ob.get("n_resamples", 1000):
        problems.append(f"RATCHET bootstrap n_resamples cut {ob.get('n_resamples')} -> {nb.get('n_resamples')}")
    if set(base_spec.get("pass_k") or []) - set(spec.get("pass_k") or []):
        problems.append(f"RATCHET pass_k shrank {base_spec.get('pass_k')} -> {spec.get('pass_k')}")
    return problems


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems = _report_problems(pr, spec, "PR") + _report_problems(base, spec, "baseline")
    pr_keys = {(r.get("item_id"), r.get("seed")) for r in pr.get("rows") or []}
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base.get("rows") or []}
    if pr_keys != base_keys:
        miss, extra = sorted(base_keys - pr_keys), sorted(pr_keys - base_keys)
        problems.append(f"(item, seed) set differs from the baseline: {len(miss)} missing"
                        f"{f' e.g. {miss[0]}' if miss else ''}, {len(extra)} extra{f' e.g. {extra[0]}' if extra else ''}")
    pm, bm = pr.get("manifest") or {}, base.get("manifest") or {}
    if sorted(pm.get("seeds") or []) != sorted(bm.get("seeds") or []) or pm.get("items") != bm.get("items"):
        problems.append(f"manifest differs from the baseline: seeds {pm.get('seeds')} vs {bm.get('seeds')}, "
                        f"items {pm.get('items')} vs {bm.get('items')}")
    if spec.get("seeds") and sorted(pm.get("seeds") or []) != sorted(spec["seeds"]):
        problems.append(f"PR seeds {pm.get('seeds')} are not the spec's {spec['seeds']}")
    base_tags = {r.get("item_id"): sorted(r.get("slices") or []) for r in base.get("rows") or []}
    for r in pr.get("rows") or []:
        tags = sorted(r.get("slices") or [])
        if r.get("item_id") in base_tags and tags != base_tags[r["item_id"]]:
            problems.append(f"{r['item_id']} slice tags {tags} differ from the baseline's {base_tags[r['item_id']]}")
            break
    if base_spec is not None:
        problems += _ratchet(spec, base_spec)
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, metric = s["name"], s["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict = "missing"               # an empty slice cannot vouch for anything
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in s and val < s["min"]:
                verdict = "fail"
            if "max" in s and val > s["max"]:
                verdict = "fail"
            keys = sorted(set(a) & set(b))
            if s.get("no_significant_drop") and keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if s.get("blocking") else "warn")
        th = {k: s[k] for k in ("min", "max", "no_significant_drop") if k in s}
        lines.append(f"  {sid:<22} {val!s:<8} {json.dumps(th) + f' n={len(a)}':<40} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
