# Case Study — Streaming the Answer, Token by Token

*Living Portfolio, Module 6. Status: live in production — `POST /chat/stream` sends the answer
as Server-Sent Events, and the chat widget types it out live, then finalizes citations and
cost. Verified incremental on the deployed API.*

## Problem

The assistant made you wait. Retrieval plus generation takes a few seconds, and the old
`/chat` returned nothing until the entire answer was ready — a blank bubble, then a wall of
text. Every serious LLM chat UI streams, because the first token arriving quickly is the
difference between "is this broken?" and "it's thinking." The goal was to stream the answer
token-by-token **without losing** the honest extras that make this assistant what it is: the
renumbered citations, the touchable source chips, and the real per-answer cost — all of which
are computed *after* the full text exists.

## Constraints

- **Keep the finalize step.** Citations are renumbered to match a deduped source list, and
  markdown is stripped, only once the whole reply is known. Streaming raw tokens can't skip that.
- **Same behaviour as `/chat`.** Retrieval, grounding, the $0 refusal, and cost accounting had
  to match its non-streaming twin exactly — not a second, drifting implementation.
- **Survive the middleware and the proxy.** The observability middleware wraps every response,
  and Render sits in front of the app; either could buffer a stream and silently defeat it.
- **Degrade honestly.** If the stream breaks mid-answer, the widget shows an error, not a
  half-answer presented as complete.

## Architecture

```
POST /chat/stream                     (shared _retrieve_for_chat: query → retrieve → ground)
   │
   ├─ not grounded → one  data:{type:"done", reply:REFUSAL, usage:$0, trace}  (no model call)
   │
   └─ grounded → Anthropic streaming:
         for delta in stream.text_stream:  data:{type:"token", text:delta}   ← as written
         on completion:                    data:{type:"done", reply, citations, usage, trace}
   │
   ▼  (Server-Sent Events, Cache-Control: no-cache, X-Accel-Buffering: no)
Chat widget: getReader() → parse `data:` frames on the blank-line boundary
   token → create the bubble on the first one, type raw text in live
   done  → swap in the finalized reply (renumbered [n] markers), source chips, cost footer
```

Two decisions carry it. **The token stream is raw; the `done` event is authoritative.** The
widget types the model's raw text for the live effect, then on `done` replaces it with the
finalized, renumbered, plain-text reply — so the citation numbers still line up with the chips
and no stray markdown survives. And **retrieval is shared with `/chat`** through one
`_retrieve_for_chat` helper, so the two endpoints can't drift on grounding, refusal, or errors.

## Trade-offs (options considered, why the choice won)

- **Server-Sent Events** over WebSockets. The data flows one way (server → client), SSE is a
  plain HTTP response the existing CORS and middleware already handle, and it needs no new
  connection lifecycle. WebSockets would be more machinery for no benefit here.
- **Stream raw, finalize on done** over streaming already-renumbered text. Renumbering needs the
  whole answer (a later `[2]` can renumber an earlier `[1]`), so it can't be done mid-stream. The
  small "snap" when raw markers become clean ones at the end is worth keeping citations correct.
- **`fetch` + `ReadableStream`** over the browser's `EventSource`. `EventSource` is GET-only, and
  the chat needs to POST a conversation; reading the `fetch` body stream and splitting on the SSE
  blank-line boundary is a few lines and supports POST.
- **A shared retrieval helper** over duplicating the logic. One source of truth for the part that
  must stay identical between the streaming and non-streaming endpoints.

## Metrics (honestly labeled — live production)

Measured against the deployed API with a streaming client:

- **Incremental, not buffered** — a real answer arrived as **15 token events spread over ~2.9s**
  (the model's writing time), not in a single blob. Confirmed through both the observability
  middleware and Render's proxy.
- **The `done` event is complete** — finalized reply, **1 citation**, `cost $0.0027`, and the
  full trace (retrieval/model timings), identical in shape to `/chat`.
- **Refusals stay free** — an out-of-corpus question emits a single `done` event with the refusal
  text and `$0`, no token stream and no model call.

## What broke, and what it taught

1. **The middleware could have buffered the stream.** Starlette's `BaseHTTPMiddleware` (which the
   observability middleware uses) historically collected streaming responses. On the installed
   version it forwards chunks, but "it should" isn't good enough here — so it was measured: tokens
   arrive incrementally *through* the middleware, and the request is still logged (its latency
   marks time-to-first-response, which is the honest number for a stream).
2. **The proxy could have buffered it too.** Render/its proxy can hold a response until it's
   complete. `Cache-Control: no-cache` and `X-Accel-Buffering: no` on the streaming response tell
   it not to — and the live 2.9s spread proves they took effect.
3. **My own test lied first.** The first local check reported "zero tokens" — a shell bug where a
   heredoc overrode the pipe feeding the parser, not a streaming failure. The raw stream showed
   tokens all along. A reminder to distrust the harness before the system when a result looks wrong.

## What's next

- **Stream the agent's steps** — the `/agent` loop already produces steps in order; surfacing each
  tool call as it happens (rather than after the run) is the same SSE pattern applied there.
- **Reconnect / resume** — a dropped stream currently shows an error and the user retries; a resume
  token would let a flaky connection pick back up.
- **Backpressure-aware scroll** — the widget follows the bottom only when the reader is already
  there; a "jump to latest" affordance would round it out for long answers.
