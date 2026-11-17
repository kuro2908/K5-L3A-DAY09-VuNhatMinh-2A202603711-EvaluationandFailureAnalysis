"""Regression test from docs/trace_case.md: C-014@11, FM-05 pre_deducted.

The first wrong step is the agent deducting the prior 30.000đ refund itself (trace event
`refund_history` -> `proposal` 120000) before calling the host, which deducts it again: the ledger
ends at 90.000đ instead of 120.000đ while the reply says 120.000đ. The test re-runs the trial on
a fresh store and checks the graders that catch it fail on seeded_regression and pass on fixed."""
import pytest

pytestmark = pytest.mark.student


def _trial(shape: str, claim_id: str = "C-014", seed: int = 11):
    import tempfile
    from pathlib import Path

    from lab8.db import load_json, load_jsonl
    from lab9 import variants
    from lab9.eval import WORLD, make_task

    variants.register()
    claims = load_jsonl(Path("data/public_claims.jsonl"))
    labels = {c["claim_id"]: c["expected"] for c in claims}
    with tempfile.TemporaryDirectory(prefix="lab9-tc-", ignore_cleanup_errors=True) as tmp:
        trial = make_task(shape, load_json(WORLD), claims, labels, Path(tmp))({"claim_id": claim_id, "seed": seed})
    return trial, labels[claim_id]


def _grade(trial, label):
    from pydantic_evals.evaluators import EvaluatorContext

    from lab9 import graders

    ctx = EvaluatorContext(name="tc", inputs={}, metadata=None, expected_output=label, output=trial,
                           duration=0.0, _span_tree=None, attributes={}, metrics={})
    return {name: graders.GRADERS[name]().evaluate(ctx).value
            for name in ("refund_amount_correct", "reply_matches_ledger", "proposal_correct")}


def test_c014_pre_deduct_is_caught_on_seeded_regression():
    trial, label = _trial("seeded_regression")
    kinds = [e["kind"] for e in trial["events"]]
    assert "refund_history" in kinds and "proposal" in kinds      # the first wrong step is in the trace
    assert trial["snapshot"]["refund_vnd"] == 90000 != label["refund_vnd"]
    assert _grade(trial, label) == {"refund_amount_correct": False, "reply_matches_ledger": False,
                                    "proposal_correct": False}


def test_c014_passes_on_fixed():
    trial, label = _trial("fixed")
    assert "proposal" not in [e["kind"] for e in trial["events"]]
    assert _grade(trial, label) == {"refund_amount_correct": True, "reply_matches_ledger": True,
                                    "proposal_correct": True}
