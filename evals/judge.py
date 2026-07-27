"""
LLM-as-judge for the RAG evals — scores the subjective dimensions the deterministic
harness cannot: groundedness/faithfulness and answer completeness, reading the actual reply.

Judge model: Claude Sonnet 5 — deliberately stronger than the Haiku that writes the answers,
so the judge isn't marking its own homework. Structured output via messages.parse; no
temperature (Sonnet 5 rejects it). Samuel's full corpus is the source of truth and is sent
as a cached system prefix, so the 108 judgements reuse it instead of re-paying for it.

Run:  python evals/judge.py           (judges evals/results.json, writes evals/judged.json)
It reuses the cached bot outputs, so it never re-runs the RAG pipeline.
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel
from dotenv import load_dotenv
from anthropic import Anthropic

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
CORPUS_DIR = ROOT / "corpus"
RESULTS = ROOT / "evals" / "results.json"
OUT = ROOT / "evals" / "judged.json"
JUDGE_MODEL = "claude-sonnet-5"


def load_corpus() -> str:
    parts = []
    for f in sorted(CORPUS_DIR.rglob("*.md")):
        if f.name == "README.md":
            continue
        parts.append(f"### {f.relative_to(CORPUS_DIR).as_posix()}\n{f.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


CORPUS = load_corpus()

INSTRUCTIONS = (
    "You are a strict evaluator for a retrieval-augmented assistant that answers questions about "
    "Samuel Hill using ONLY his documents. Below are Samuel's COMPLETE documents — the only facts "
    "the assistant is allowed to use. For each test case you receive the question, the expected "
    "behavior, the key facts a correct answer needs, and the assistant's actual answer.\n\n"
    "Score these booleans strictly:\n"
    "- grounded: every factual claim in the answer is supported by the documents. A refusal is "
    "trivially grounded. Any claim not supported by the documents makes this false.\n"
    "- behavior_correct: if expected is 'answer', the assistant actually answered from the docs; "
    "if expected is 'refuse', it declined or said it doesn't have that information (a helpful "
    "redirect to contact Samuel still counts as a correct refusal).\n"
    "- captures_expected: if expected is 'answer', the answer conveys the key facts; if expected "
    "is 'refuse', set true when it correctly declined without fabricating.\n"
    "- overall_pass: true only if grounded AND behavior_correct AND captures_expected.\n"
    "- reason: one sentence."
)

SYSTEM = [{
    "type": "text",
    "text": INSTRUCTIONS + "\n\n=== SAMUEL'S DOCUMENTS (source of truth) ===\n" + CORPUS,
    "cache_control": {"type": "ephemeral"},   # stable prefix — cached across all judgements
}]

_client = Anthropic()


class Verdict(BaseModel):
    grounded: bool
    behavior_correct: bool
    captures_expected: bool
    overall_pass: bool
    reason: str


def judge_one(row: dict) -> dict:
    user = (
        f"=== QUESTION ===\n{row['question']}\n\n"
        f"=== EXPECTED BEHAVIOR ===\n{row['expected_behavior']}\n\n"
        f"=== KEY FACTS A CORRECT ANSWER NEEDS ===\n{row.get('answer_gist', '')}\n\n"
        f"=== ASSISTANT'S ACTUAL ANSWER ===\n{row['actual']['reply']}"
    )
    resp = _client.messages.parse(
        model=JUDGE_MODEL, max_tokens=2048, system=SYSTEM,
        messages=[{"role": "user", "content": user}], output_format=Verdict,
    )
    v = resp.parsed_output
    return {
        "id": row["id"], "category": row["category"], "expected_behavior": row["expected_behavior"],
        "verdict": v.model_dump(),
        "usage": {"in": resp.usage.input_tokens, "out": resp.usage.output_tokens,
                  "cache_read": getattr(resp.usage, "cache_read_input_tokens", 0)},
    }


# Sonnet 5 intro pricing (through 2026-08-31): $2/$10 per 1M in/out; cache reads ~0.1x input.
IN_USD, OUT_USD = 2.00, 10.00


def main() -> None:
    rows = json.loads(RESULTS.read_text(encoding="utf-8"))["results"]
    print(f"Judging {len(rows)} answers with {JUDGE_MODEL}. Corpus is cached, so cost is mostly the "
          f"per-answer tokens. Est. < $1.\n")

    judged = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for i, res in enumerate(pool.map(judge_one, rows), 1):   # map preserves input order
            judged.append(res)
            if i % 15 == 0 or i == len(rows):
                print(f"  {i}/{len(rows)}")

    passed = sum(1 for j in judged if j["verdict"]["overall_pass"])
    grounded = sum(1 for j in judged if j["verdict"]["grounded"])
    behavior = sum(1 for j in judged if j["verdict"]["behavior_correct"])
    captures = sum(1 for j in judged if j["verdict"]["captures_expected"])
    ans = [j for j in judged if j["expected_behavior"] == "answer"]
    ref = [j for j in judged if j["expected_behavior"] == "refuse"]
    ans_pass = sum(1 for j in ans if j["verdict"]["overall_pass"])
    ref_pass = sum(1 for j in ref if j["verdict"]["overall_pass"])

    cost = sum(j["usage"]["in"] / 1e6 * IN_USD + j["usage"]["out"] / 1e6 * OUT_USD for j in judged)
    cache_reads = sum(j["usage"]["cache_read"] for j in judged)

    metrics = {
        "judge_model": JUDGE_MODEL,
        "n": len(judged),
        "overall_pass_rate": round(passed / len(judged), 3),
        "grounded_rate": round(grounded / len(judged), 3),
        "behavior_correct_rate": round(behavior / len(judged), 3),
        "captures_expected_rate": round(captures / len(judged), 3),
        "answer_pass": f"{ans_pass}/{len(ans)}",
        "refuse_pass": f"{ref_pass}/{len(ref)}",
        "judge_cost_usd": round(cost, 4),
        "cache_read_tokens": cache_reads,
    }
    OUT.write_text(json.dumps({"metrics": metrics, "judged": judged}, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== LLM-JUDGE METRICS (Sonnet 5, on actual replies) ===")
    for k, v in metrics.items():
        print(f"  {k:24} {v}")
    print(f"\nwrote {OUT.relative_to(ROOT)}")

    fails = [j for j in judged if not j["verdict"]["overall_pass"]]
    if fails:
        print(f"\n=== {len(fails)} failures (for review / calibration) ===")
        for j in fails[:12]:
            print(f"  [{j['id']} {j['category']}/{j['expected_behavior']}] {j['verdict']['reason'][:90]}")


if __name__ == "__main__":
    main()
