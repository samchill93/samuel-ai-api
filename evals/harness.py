"""
Deterministic eval pass over the golden dataset — no LLM judge required.

Runs each dataset example through the real RAG pipeline and scores the parts that have
an objective ground truth:
  - refusal correctness: did the bot answer vs refuse when it should have?
  - retrieval recall@k:  did retrieval surface the source(s) a correct answer needs?
  - citation validity:   did the answer cite only sources it actually retrieved?

The subjective dimensions (groundedness, answer quality) are scored separately by the
LLM judge (judge.py). Results are cached to evals/results.json so the judge phase can
reuse the bot outputs without re-running the pipeline.
"""

import json
import sys
from pathlib import Path
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8")   # the corpus/labels contain em-dashes etc.
except Exception:
    pass

from dotenv import load_dotenv
from anthropic import Anthropic

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from retrieve import retrieve, is_grounded, conversation_query, RETRIEVAL_K  # noqa: E402
from rag import build_system_prompt, finalize_citations, to_plain_text, REFUSAL  # noqa: E402
from about_me import ABOUT_SAMUEL  # noqa: E402
from main import _answer_cost_usd  # noqa: E402

DATA = ROOT / "data" / "golden_dataset.json"
OUT = ROOT / "evals" / "results.json"
MODEL = "claude-haiku-4-5-20251001"


def run_bot(example: dict) -> dict:
    """Answer one example through the real RAG pipeline; capture what we need to score."""
    msgs = list(example.get("history") or [])
    msgs.append({"role": "user", "content": example["question"]})

    hits = retrieve(conversation_query(msgs))
    retrieved, seen = [], set()
    for h in hits:
        if h["source_path"] not in seen:
            seen.add(h["source_path"])
            retrieved.append(h["source_path"])

    if not is_grounded(hits):
        return {"behavior": "refuse", "reply": REFUSAL, "citations": [],
                "retrieved": retrieved, "top_similarity": hits[0]["similarity"] if hits else 0.0, "cost": 0.0}

    system = build_system_prompt(ABOUT_SAMUEL, hits)
    resp = Anthropic().messages.create(model=MODEL, max_tokens=1024, system=system, messages=msgs)
    reply, citations = finalize_citations(resp.content[0].text, hits)
    reply = to_plain_text(reply)
    return {
        "behavior": "answer",
        "reply": reply,
        "citations": [c["source_path"] for c in citations],
        "retrieved": retrieved,
        "top_similarity": hits[0]["similarity"],
        "cost": _answer_cost_usd(resp.usage.input_tokens, resp.usage.output_tokens),
    }


def recall_at_k(expected: list, retrieved: list) -> float:
    """Fraction of expected sources that appear in the retrieved set."""
    if not expected:
        return None
    hit = sum(1 for s in expected if s in retrieved)
    return hit / len(expected)


def main() -> None:
    ds = json.loads(DATA.read_text(encoding="utf-8"))
    examples = ds["examples"]
    n_answer = sum(1 for e in examples if e["expected_behavior"] == "answer")
    print(f"Running {len(examples)} examples ({n_answer} expected-answer -> Claude calls). Est. cost < $0.30.\n")

    results = []
    for i, ex in enumerate(examples, 1):
        out = run_bot(ex)
        results.append({**ex, "actual": out})
        if i % 15 == 0 or i == len(examples):
            print(f"  {i}/{len(examples)}")

    # --- Deterministic metrics -------------------------------------------------
    behavior_correct = sum(1 for r in results if r["actual"]["behavior"] == r["expected_behavior"])
    conf = Counter((r["expected_behavior"], r["actual"]["behavior"]) for r in results)
    false_refusals = conf[("answer", "refuse")]   # should have answered, refused
    false_answers = conf[("refuse", "answer")]    # should have refused, answered (hallucination risk)

    recalls = [recall_at_k(r["expected_sources"], r["actual"]["retrieved"])
               for r in results if r["expected_behavior"] == "answer" and r["expected_sources"]]
    recalls = [x for x in recalls if x is not None]
    mean_recall = sum(recalls) / len(recalls) if recalls else 0.0
    perfect_recall = sum(1 for x in recalls if x == 1.0)

    answered = [r for r in results if r["actual"]["behavior"] == "answer"]
    cited = [r for r in answered if r["actual"]["citations"]]
    citation_valid = sum(1 for r in cited
                         if all(c in r["actual"]["retrieved"] for c in r["actual"]["citations"]))
    total_cost = sum(r["actual"]["cost"] for r in results)

    metrics = {
        "n": len(results),
        "refusal_correctness": round(behavior_correct / len(results), 3),
        "correct_behaviors": behavior_correct,
        "false_refusals": false_refusals,
        "false_answers": false_answers,
        "retrieval_recall_at_k": round(mean_recall, 3),
        "recall_k": RETRIEVAL_K,
        "perfect_recall_examples": f"{perfect_recall}/{len(recalls)}",
        "answered": len(answered),
        "answers_with_citations": len(cited),
        "citation_validity": f"{citation_valid}/{len(cited)}" if cited else "n/a",
        "total_run_cost_usd": round(total_cost, 4),
    }

    OUT.write_text(json.dumps({"metrics": metrics, "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== DETERMINISTIC METRICS (no judge) ===")
    for k, v in metrics.items():
        print(f"  {k:26} {v}")
    print(f"\nwrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
