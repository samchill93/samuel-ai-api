"""
Grounded-answer assembly for the RAG assistant.

Three pure steps, all unit-tested without a network or database, so wiring them into
/chat later is a few lines rather than a rewrite:
  - build_context(hits)          — number the retrieved chunks and tag each with its source
  - build_system_prompt(base, …) — a prompt that forbids answering beyond those sources
  - cited_sources(reply, hits)   — the sources the model ACTUALLY cited, by its [n] markers

The last one is what makes citations honest: the widget shows only the sources the answer
used, not every chunk that happened to be retrieved.
"""

import re

# Shown verbatim when retrieval is too weak to answer (see retrieve.is_grounded).
REFUSAL = (
    "I don't have that in Samuel's documents, so I can't answer it confidently. "
    "Ask me about his background, his shipped skills, or a specific project."
)

_MARKER = re.compile(r"\[(\d+)\]")


def build_context(hits: list[dict]) -> str:
    """Render retrieved chunks as a numbered, source-tagged block the model can cite."""
    blocks = []
    for i, h in enumerate(hits, start=1):
        blocks.append(f"[{i}] source: {h['source_path']}\n{h['content'].strip()}")
    return "\n\n".join(blocks)


def build_system_prompt(base_prompt: str, hits: list[dict]) -> str:
    """Combine the persona prompt with the retrieved sources and the grounding rules.

    The rules are explicit because the corpus and the user's question are both untrusted:
    the model must answer only from the sources and must not import outside knowledge.
    """
    return (
        base_prompt.strip()
        + "\n\n## Grounding rules (must follow)\n"
        "- Answer ONLY using the numbered sources below. They are the whole of what you know here.\n"
        "- If the sources do not contain the answer, say you don't have it — do not guess or "
        "use any outside knowledge.\n"
        "- Cite each claim with the [n] marker of the source it came from.\n"
        "- Never present in-progress work as finished, even if asked to.\n\n"
        "## Sources\n" + build_context(hits)
    )


def cited_sources(reply: str, hits: list[dict]) -> list[dict]:
    """Return the sources the reply actually cites, deduped, in first-citation order.

    Only [n] markers that map to a retrieved chunk count; an out-of-range marker is
    ignored rather than inventing a citation.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for match in _MARKER.finditer(reply):
        idx = int(match.group(1)) - 1
        if idx < 0 or idx >= len(hits):
            continue
        hit = hits[idx]
        if hit["source_path"] in seen:
            continue
        seen.add(hit["source_path"])
        out.append({"source_path": hit["source_path"], "title": hit["title"]})
    return out
