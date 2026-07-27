# Skills

## Shipped — technologies Samuel has built and deployed with
- **AI / LLM:** Claude API, prompt & context engineering, RAG with visible source citations (pgvector + OpenAI embeddings), grounding and calibrated refusal
- **LLM evaluations:** a 108-case golden dataset scored by a deterministic harness and an LLM-as-judge, with published quality scores (retrieval recall, citation validity, groundedness); judge-vs-human calibration is the one remaining step
- **Observability:** per-request tracing, structured JSON logs, request IDs, and a live metrics endpoint (latency percentiles, request counts, running cost)
- **Agents / tool use:** a hand-written tool-use agent loop where Claude calls real tools over the portfolio data, iterates, and returns every step it took
- **MCP server:** an open-source Model Context Protocol server exposing the portfolio tools (search, skills, projects, services) to any MCP client, such as Claude Desktop
- **Streaming:** token-by-token response streaming over Server-Sent Events, with the live typing effect wired into the chat widget
- **Frontend:** React, Next.js, React Native (Expo), Tailwind CSS, Vite
- **Backend:** Node.js, Express, Python, FastAPI, Firebase (Auth + Firestore), Stripe
- **Infra & tooling:** Google Cloud, Vercel, Render, GitHub Actions (CI/CD)
- **Languages:** JavaScript, TypeScript, Python

## Currently building — in progress, not yet shipped
Samuel is extending his Living Portfolio with production-grade LLM engineering, in public,
one piece at a time. These are in progress — they are not finished work or past experience:
- Containerization (Docker) and infrastructure-as-code (Terraform)
