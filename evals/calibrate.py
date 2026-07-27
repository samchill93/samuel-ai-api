"""
Calibrate the LLM judge against Samuel's hand labels — the senior signal for the evals.

The judge is only trustworthy if it agrees with a human on the same examples. This builds
a blind labeling slice (you don't see the judge's verdict while labeling), then computes
the agreement rate between your labels and the judge.

    python evals/calibrate.py make     # writes data/calibration_slice.json (label human_pass)
    python evals/calibrate.py score     # after labeling, reports judge-vs-human agreement

The slice is stratified: every judge-failure plus a balanced sample of passes, so the set
contains both good and bad answers — otherwise "agreement" is trivially high.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JUDGED = ROOT / "evals" / "judged.json"
RESULTS = ROOT / "evals" / "results.json"
SLICE = ROOT / "data" / "calibration_slice.json"
TARGET = 24   # slice size

INSTRUCTIONS = (
    "Label each item BLIND — decide for yourself, the judge's verdict is not shown. For each item, "
    "read `question` and `assistant_reply`. Set `human_pass` to true if the reply is good — grounded "
    "in Samuel's documents, correct, and answers when it should / refuses when the docs don't cover it. "
    "Set false if it's bad — hallucinates, is wrong, over-refuses, or presents in-progress work as "
    "shipped. `key_facts` is the rubric of what a correct answer needs. Add an optional `human_note`. "
    "Save the file, then tell Claude 'labels done' and it will run: python evals/calibrate.py score"
)


def make() -> None:
    judged = {j["id"]: j for j in json.loads(JUDGED.read_text(encoding="utf-8"))["judged"]}
    results = {r["id"]: r for r in json.loads(RESULTS.read_text(encoding="utf-8"))["results"]}

    fails = [i for i, j in judged.items() if not j["verdict"]["overall_pass"]]
    passes = [i for i, j in judged.items() if j["verdict"]["overall_pass"]]
    # Deterministic, balanced spread of passes across categories (evenly spaced by id).
    passes.sort()
    step = max(1, len(passes) // max(1, TARGET - len(fails)))
    sampled_passes = passes[::step][: TARGET - len(fails)]
    chosen = sorted(set(fails) | set(sampled_passes), key=lambda i: int(i[1:]))

    items = []
    for i in chosen:
        r = results[i]
        item = {
            "id": i,
            "question": r["question"],
            "expected_behavior": r["expected_behavior"],
            "key_facts": r.get("answer_gist", ""),
            "assistant_reply": r["actual"]["reply"],
            "human_pass": None,     # <-- you fill this in: true / false
            "human_note": "",
        }
        if r.get("history"):
            item["prior_turns"] = r["history"]
        items.append(item)

    SLICE.write_text(json.dumps({"instructions": INSTRUCTIONS, "items": items}, indent=2, ensure_ascii=False),
                     encoding="utf-8")
    n_fail = sum(1 for i in chosen if not judged[i]["verdict"]["overall_pass"])
    print(f"wrote {SLICE.relative_to(ROOT)} — {len(items)} items to label "
          f"({n_fail} the judge failed, {len(items) - n_fail} it passed).")
    print("Open it, set human_pass true/false on each, save, then: python evals/calibrate.py score")


def score() -> None:
    data = json.loads(SLICE.read_text(encoding="utf-8"))
    judged = {j["id"]: j for j in json.loads(JUDGED.read_text(encoding="utf-8"))["judged"]}
    labeled = [it for it in data["items"] if isinstance(it.get("human_pass"), bool)]
    if not labeled:
        print("No labels yet — set human_pass (true/false) on the items in "
              f"{SLICE.relative_to(ROOT)}, then re-run.")
        return

    agree = disagree = 0
    both_pass = both_fail = judge_only = human_only = 0
    disagreements = []
    for it in labeled:
        jp = judged[it["id"]]["verdict"]["overall_pass"]
        hp = it["human_pass"]
        if jp == hp:
            agree += 1
            both_pass += jp
            both_fail += (not jp)
        else:
            disagree += 1
            judge_only += (jp and not hp)   # judge passed, human failed
            human_only += (hp and not jp)   # human passed, judge failed
            disagreements.append((it["id"], jp, hp, it.get("human_note", "")))

    n = len(labeled)
    agreement = agree / n
    # Cohen's kappa (chance-corrected agreement)
    pj = sum(judged[it["id"]]["verdict"]["overall_pass"] for it in labeled) / n
    ph = sum(it["human_pass"] for it in labeled) / n
    pe = pj * ph + (1 - pj) * (1 - ph)
    kappa = (agreement - pe) / (1 - pe) if pe < 1 else 1.0

    print(f"=== JUDGE CALIBRATION (n={n} hand-labeled) ===")
    print(f"  raw agreement:      {agreement:.3f}  ({agree}/{n})")
    print(f"  Cohen's kappa:      {kappa:.3f}  (chance-corrected)")
    print(f"  both pass: {both_pass} | both fail: {both_fail} | judge-lenient: {judge_only} | judge-strict: {human_only}")
    if disagreements:
        print("  disagreements:")
        for i, jp, hp, note in disagreements:
            print(f"    {i}: judge={'pass' if jp else 'fail'} human={'pass' if hp else 'fail'}  {note[:70]}")
    print(f"\n  Reportable: \"LLM-judge agreement {agreement:.2f} vs {n} hand labels (kappa {kappa:.2f}).\"")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "make"
    {"make": make, "score": score}.get(cmd, make)()
