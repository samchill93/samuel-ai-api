# Cadence — AI customer-support chatbot

A custom AI customer-support chatbot built on the Claude API. It answers from a product's real
knowledge instead of making things up, and hands off cleanly to a human when a question needs one.
Live and deployed.

## What's shipped
- A React frontend talking to a serverless function that holds the API key and calls Claude with
  an engineered system prompt.
- Grounded answers designed against hallucination; a clean refusal and human handoff for questions
  that need a person (for example, billing).
- Sample-question chips and a mobile-friendly UI.

## Design decisions
- API key lives server-side in a serverless function — the browser never sees it.
- Grounding via an engineered system prompt rather than RAG: the knowledge base is small and
  bounded, so retrieval would add latency and moving parts without accuracy gains. RAG is the
  documented next step as the corpus grows.
- Refusal and human handoff over best-guess answers — a support bot that invents policy is worse
  than one that escalates.

**Stack:** React, Vite, Vercel serverless functions, Claude API.
**Live:** cadence-support-bot.vercel.app
**Repo:** github.com/samchill93/cadence-support-bot
