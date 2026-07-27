# Case Study — Measuring the RAG Assistant with Evals

*Living Portfolio, Module 2. Status: eval engine built and run; the judge caught a real
honesty bug that was fixed and deployed. Judge-vs-human calibration is the one open step
(24-item blind slice awaiting hand labels). Numbers below are from the run saved in
`evals/results.json` and `evals/judged.json`.*

## Problem

Module 1 shipped a RAG assistant that answers only from Samuel's documents and cites its
sources. But "it seems to work when I try it" is not evidence — it's the exact thing a
senior reviewer discounts. The assistant makes three kinds of decision that can each fail
silently: it retrieves the wrong chunks, it answers when it should refuse (or refuses when
it should answer), and it can drift from the sources into something that merely sounds
right. With no users and no traffic, there was no natural signal telling Samuel whether any
of that was happening.

The goal: replace vibes with numbers. Build a repeatable evaluation that scores the
assistant on a fixed set of questions with known-correct behavior, publish the numbers with
honest labels, and — the part that separates eval literacy from eval theater — **prove the
automated judge agrees with a human** before trusting a single score it produces.

## Constraints

- **Cost control** — the suite loops LLM calls, so every run is costed before it runs. A
  full pass (108 answers + 108 judgments) had to stay well under a dollar.
- **No fabricated data, ever** — labels are verified against the corpus, not invented; the
  judge's numbers are only trustworthy once measured against human labels, so any score is
  reported as *uncalibrated* until that check exists.
- **Probe-proof understanding** — a hand-rolled harness over a framework, so every number
  has a line of code behind it Samuel can explain in an interview.
- **Honest scope** — the corpus is a claims surface; an eval that "passes" a bot which
  overclaims is worse than no eval. The suite had to be able to *fail* on a real overclaim,
  and it did.

## Architecture

```
data/golden_dataset.json        108 Q&A cases (66 answer / 42 refuse), 6 categories,
   │                            each: question, expected_behavior, expected_sources,
   │                            answer_gist, rationale — built by a 12-agent workflow
   │                            (6 category generators + 6 adversarial verifiers)
   ▼
evals/harness.py  ── runs each case through the REAL pipeline ──▶ evals/results.json
   │   conversation_query → retrieve → is_grounded → build_system_prompt
   │   → Haiku 4.5 → finalize_citations → to_plain_text
   │   scores the objective dimensions:
   │     • retrieval recall@5   (did the needed sources get retrieved?)
   │     • citation validity    (did the answer cite only retrieved sources?)
   │     • threshold behavior   (did the 0.35 gate answer/refuse as expected?)
   ▼
evals/judge.py  ── Claude Sonnet 5 grades the ACTUAL replies ──▶ evals/judged.json
   │   corpus sent as a cached system prefix (~350k tokens read from cache per run)
   │   Verdict{ grounded, behavior_correct, captures_expected, overall_pass, reason }
   ▼
evals/calibrate.py  ── blind 24-item slice ──▶ data/calibration_slice.json
       human labels each pass/fail without seeing the judge's verdict
       → raw agreement + Cohen's kappa  (judge trustworthiness)
```

Two decisions carry the design. **The harness runs the real pipeline, not a reimplementation
of it** — it imports the same `retrieve`, `build_system_prompt`, and `finalize_citations`
the production `/chat` uses, so a passing eval is evidence about the deployed system, not a
parallel copy that can drift. And **the judge is a stronger model than the author** — Sonnet
5 grades what Haiku 4.5 wrote, so the grader isn't marking its own homework at its own skill
ceiling.

## Trade-offs (options considered, why the choice won)

- **Judge model — Sonnet 5** over Haiku. Judgment quality matters more here than raw
  answer-generation cost, and a judge at the same tier as the author shares its blind spots.
  Sonnet grades the actual replies at ~$0.20 a run, kept cheap by caching the corpus.
- **Hand-rolled harness** over promptfoo / a framework. The point of this module is that
  Samuel can defend every number. A framework hides recall@k and the confusion matrix behind
  config; here they're twenty lines he wrote. Portability is the trade — this harness is
  specific to this app, which for a portfolio is the right call.
- **Structured judge output** (`messages.parse` → a Pydantic `Verdict`) over free-text
  parsing. The judge must return a strict schema, so scoring is deterministic and a
  malformed verdict is a retry, not a silent miscount.
- **Golden set built by adversarial agents, then human-owned** over hand-writing 108 cases
  or trusting one generator. Six generators drafted cases by category; six independent
  verifiers checked each label against the corpus and cut the ones that didn't hold. The
  human still owns the calibration labels — the generators seed the set; they don't certify
  the judge.
- **Corpus as a cached prefix** over re-sending it every call. The judge needs the whole
  corpus to check groundedness; caching it turns ~350k tokens per run from full-price into
  cache reads, which is what keeps the run under a dollar.

## Metrics (honestly labeled — local run, not production traffic)

**Golden set:** 108 cases — 66 expected-answer, 42 expected-refuse — across six categories
(background, skills, projects, refuse, edge, multi-turn).

**Deterministic (harness, objective ground truth):**
- **Retrieval recall@5 — 0.992** (65/66 expected-answer cases retrieved every source a
  correct answer needs; one case missed one source).
- **Citation validity — 92/92** — every answer that cited a source cited only a source it
  actually retrieved. Zero fabricated citations.
- **Threshold behavior — 0.611** (66/108), with 1 false-refusal and 41 "false-answers."
  *This number is a trap, and unpacking it is the finding below.*
- **Run cost — $0.209** for 106 model answers.

**LLM judge (Sonnet 5, on the actual replies):**
- **Overall pass — 0.917** (answer cases 59/66, refuse cases 40/42).
- **Grounded — 0.944** · **Behavior-correct — 0.981** · **Captures-expected — 0.963**.
- **Judge cost — $0.203** per full run (353,634 tokens served from cache).

**Judge calibration — pending.** A 24-item blind slice (every judge-failure plus a balanced
sample of passes) is built and waiting for human pass/fail labels; `calibrate.py score` then
reports raw agreement and Cohen's kappa. Until then, **every judge number above is
uncalibrated** and labeled as such — the honest state, not a hidden one.

### The finding: 0.611 and 0.981 are measuring different things

The deterministic "threshold behavior" score is 0.611, which looks alarming next to the
judge's 0.981 behavior-correctness. They disagree because they measure different decisions.

`refusal_correctness` in the harness scores only the **0.35 similarity gate** — answer if the
top retrieved chunk clears 0.35, refuse if not. On the 42 should-refuse cases, 41 cleared the
gate (a question about, say, Samuel's *opinion on remote work* still retrieves his real
profile chunks at high similarity — the topic is on-corpus even though the answer isn't in
it). So the gate alone "answers" 41 cases it arguably shouldn't, and the naive metric reads
61%.

But the gate was never the refusal mechanism. It's a cheap pre-filter that only catches
wildly off-topic questions (the "favorite pizza" case, at 0.33). The *real* refusal
intelligence is the grounded model reading numbered sources and saying "these don't contain
that." Scoring the **actual replies**, the judge finds behavior correct 98.1% of the time and
refuse-cases passing 40/42 — the model refuses correctly even when the threshold waved the
question through.

The lesson is the senior one: **a metric that's easy to compute can measure the wrong
decision boundary.** The threshold is one gate in a two-gate system; judging the system's
real output, not its cheapest proxy, is what tells the truth. That distinction — not the
headline pass rate — is the thing worth defending in an interview.

## What broke, and how it was fixed

1. **The judge caught a live overclaim — the module's whole justification.** Asked "can he
   do response streaming and Terraform?", the deployed bot answered *yes, he's shipped them*
   — both are in-progress, not shipped. The grounding rule was strengthened to forbid
   describing in-progress work as done, the fix was re-measured on the failing cases, and it
   was deployed and verified live (the bot now frames that work as in progress). This is the
   eval loop closing end to end: **measure → find a real bug → fix → re-measure → deploy →
   verify.**
2. **Judge scores move run-to-run.** Both answer generation and judging are
   non-deterministic, so the pass rate wobbles ~0.02 and the *set* of failing cases shifts.
   The response was to stop treating a single run as truth: the recurring failures (a handful
   of factual-precision edge cases) are the real signal, and calibration plus repeated runs
   matter more than any one number. Naming this is itself the eval-literacy point.
3. **`cp1252` crashes on em-dashes.** The corpus and labels contain `—` and `→`; printing
   them on Windows' default code page threw `UnicodeEncodeError` mid-run. Fixed with
   `sys.stdout.reconfigure(encoding="utf-8")` and ASCII arrows in log lines.
4. **Ordering bug in the judge fan-out.** An over-clever index expression risked pairing a
   verdict with the wrong example under threading. Replaced with an order-preserving
   `pool.map`, so verdict *i* always belongs to example *i*.

## What's next

- **Calibrate the judge** — the one open step. Human labels the 24-item blind slice; if
  agreement and kappa are high, the judge's numbers become reportable as
  *"LLM-judge agreement 0.9x vs hand labels (kappa 0.8x)"*; if they're low, the judge prompt
  gets fixed before any score is published. Either outcome is the honest one.
- **Publish an Evals page** on the site rendering the calibrated numbers with their source
  labels — no headline judge score goes public before calibration.
- **Tighten the threshold story** — the 0.35 gate and the model's refusal are two gates;
  a future pass could measure them separately and tune the gate with the confusion matrix in
  hand, rather than by a single hand-picked example.
- **Wire evals into CI (Module 6)** — once calibrated, run a subset on every push and fail
  the build if groundedness or behavior-correctness drops below a threshold, so an overclaim
  like the one above can never reach production again.
