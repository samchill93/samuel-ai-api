"""
Roll the eval run artifacts into one small, publishable summary.

The full run files (evals/results.json, evals/judged.json) hold every example and are
gitignored — too big and too detailed to publish. This distills them to the headline
numbers the site and case study quote, so the published figures are provably derived from
a real run rather than hand-typed. Re-run after any eval pass:

    python evals/harness.py        # -> results.json
    python evals/judge.py          # -> judged.json
    python evals/summarize.py      # -> summary.json   (committed, the published numbers)

summary.json is the single source of truth for every eval number shown publicly.
"""

import json
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "golden_dataset.json"
RESULTS = ROOT / "evals" / "results.json"
JUDGED = ROOT / "evals" / "judged.json"
OUT = ROOT / "evals" / "summary.json"


def main() -> None:
    examples = json.loads(DATA.read_text(encoding="utf-8"))["examples"]
    det = json.loads(RESULTS.read_text(encoding="utf-8"))["metrics"]
    jud = json.loads(JUDGED.read_text(encoding="utf-8"))["metrics"]

    behaviors = Counter(e["expected_behavior"] for e in examples)
    categories = sorted({e["category"] for e in examples})

    summary = {
        "generated_on": date.today().isoformat(),
        "source": "derived from evals/results.json and evals/judged.json",
        "runtime_model": "claude-haiku-4-5",
        "judge_model": jud["judge_model"],
        "dataset": {
            "total": len(examples),
            "expected_answer": behaviors["answer"],
            "expected_refuse": behaviors["refuse"],
            "categories": categories,
        },
        "deterministic": {
            "retrieval_recall_at_k": det["retrieval_recall_at_k"],
            "recall_k": det["recall_k"],
            "perfect_recall_examples": det["perfect_recall_examples"],
            "citation_validity": det["citation_validity"],
            "false_refusals": det["false_refusals"],
            "threshold_behavior_correctness": det["refusal_correctness"],
            "run_cost_usd": det["total_run_cost_usd"],
        },
        "judge": {
            "calibrated": False,
            "overall_pass_rate": jud["overall_pass_rate"],
            "grounded_rate": jud["grounded_rate"],
            "behavior_correct_rate": jud["behavior_correct_rate"],
            "captures_expected_rate": jud["captures_expected_rate"],
            "answer_pass": jud["answer_pass"],
            "refuse_pass": jud["refuse_pass"],
            "cost_usd": jud["judge_cost_usd"],
        },
        "costs": {
            "answer_generation_usd": det["total_run_cost_usd"],
            "judge_usd": jud["judge_cost_usd"],
            # A full eval run is both phases: generate every answer, then judge every reply.
            "full_eval_run_usd": round(det["total_run_cost_usd"] + jud["judge_cost_usd"], 4),
        },
        "calibration": {"status": "pending", "slice_size": 24},
    }

    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
