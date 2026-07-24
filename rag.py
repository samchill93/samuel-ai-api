"""
Grounded-answer assembly for the RAG assistant.

Three pure steps, all unit-tested without a network or database, so wiring them into
/chat later is a few lines rather than a rewrite:
  - build_context(hits)            — number the retrieved chunks and tag each with its source
  - build_system_prompt(base, …)   — a prompt that forbids answering beyond those sources
  - finalize_citations(reply, …)   — renumber the reply's [n] markers to a clean 1..N that
                                     matches the deduped source list, and return that list

finalize_citations is what makes citations honest AND touchable: the visible markers line
up one-to-one with the source chips, and the list holds only the sources the answer used.
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


def finalize_citations(reply: str, hits: list[dict]) -> tuple[str, list[dict]]:
    """Renumber the reply's [n] markers and return (rewritten_reply, citations).

    A marker [n] refers to the n-th retrieved chunk, and several markers can point to the
    same source. This collapses them to a clean 1..N so the visible numbers line up with
    the deduped source chips — like a reference list — which is what lets each marker be a
    touchable link to its chip. A marker with no matching chunk is a model slip and is
    dropped rather than shown as a citation.
    """
    order: list[str] = []            # source_path in first-citation order
    meta: dict[str, dict] = {}       # source_path -> {source_path, title, snippet}
    for match in _MARKER.finditer(reply):
        idx = int(match.group(1)) - 1
        if 0 <= idx < len(hits):
            source_path = hits[idx]["source_path"]
            if source_path not in meta:
                # Snippet = the first cited chunk's text, whitespace-collapsed and trimmed.
                # It lets the widget preview a source next to the marker without scrolling.
                snippet = " ".join(hits[idx]["content"].split())[:200]
                meta[source_path] = {
                    "source_path": source_path,
                    "title": hits[idx]["title"],
                    "snippet": snippet,
                }
                order.append(source_path)
    renumber = {source_path: i + 1 for i, source_path in enumerate(order)}

    def _sub(match) -> str:
        idx = int(match.group(1)) - 1
        if 0 <= idx < len(hits):
            return f"[{renumber[hits[idx]['source_path']]}]"
        return ""   # drop a marker that points at no retrieved chunk

    new_reply = _MARKER.sub(_sub, reply)
    citations = [meta[source_path] for source_path in order]
    return new_reply, citations
