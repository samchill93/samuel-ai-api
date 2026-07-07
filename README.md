# Ask Me About Samuel — API

A small Python (FastAPI) backend that answers questions about Samuel using the Claude API.
It's the Python counterpart to the Cadence support bot, and the first building block of the
Living Portfolio.

## What's in here

- `main.py` — the FastAPI app (a `/health` check + a `/chat` endpoint)
- `about_me.py` — the knowledge the bot answers from (Claude's system prompt)
- `test_main.py` — a starter pytest test
- `requirements.txt` — the Python packages this project needs
- `.env.example` — a template for your API key

## Setup (Windows)

Open this folder in VS Code, then open a terminal (**Terminal → New Terminal**) and run these
one at a time.

**1. Create a virtual environment** — a private package folder just for this project:

```
py -m venv venv
```

**2. Activate it** (you'll see `(venv)` appear at the start of your prompt):

```
.\venv\Scripts\activate
```

> If PowerShell blocks it with an "execution policy" error, run this once, then activate again:
> ```
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

**3. Install the packages:**

```
pip install -r requirements.txt
```

**4. Add your API key:** make a copy of `.env.example`, name the copy exactly `.env`, and paste
your key from https://console.anthropic.com.

**5. Run the server:**

```
uvicorn main:app --reload
```

Then open **http://localhost:8000/health** — you should see `{"status":"ok"}`.
Interactive API docs are at **http://localhost:8000/docs**, where you can try the `/chat`
endpoint right in the browser.

**6. Run the test:**

```
pytest
```

## Next steps

- Flesh out `about_me.py` so the bot really knows you.
- Connect this API to the Monograph portfolio site's chat widget.
- Later phases: RAG, evals, and observability — the Living Portfolio roadmap.
