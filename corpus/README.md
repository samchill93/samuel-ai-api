# Corpus — the bot's source of truth

Every markdown file in this folder is a **document** the portfolio assistant can answer from.
The ingestion script splits each file into overlapping **chunks**, turns each chunk into an
embedding (a vector), and stores it in Postgres (pgvector). At question time the bot embeds the
visitor's question, retrieves the most similar chunks, and answers **only** from them — quoting
its sources as citations.

## How to change what the bot knows
1. Edit these files (or add new ones).
2. Re-run the ingestion CLI to re-embed the corpus.
3. The bot immediately answers from the updated content.

## Honesty rules (non-negotiable — this is a claims surface)
- Everything here must be **true and defensible**. The bot will state it to recruiters as fact.
- **Shipped vs. in-progress is always explicit.** Never present work that is still being built as
  finished, or as past client experience.
- **No fabricated numbers.** Every metric carries its source. If a number doesn't exist yet, leave
  it out — don't invent one.
- Keep the title accurate: **Full-Stack AI Engineer** (the "Agentic" upgrade is earned later).

## File layout
- `profile.md` — who Samuel is, background, and what he's looking for.
- `skills.md` — shipped skills, and a clearly separate "currently building" section.
- `projects/*.md` — one file per project, each with an honest scope of what's shipped.
