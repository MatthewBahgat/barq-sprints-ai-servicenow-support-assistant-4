# S3.6 — Running the Integrated Stack

Setup from a clean checkout of this repo.

## Prerequisites
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (with WSL2 backend on Windows)
- A real embedding credential: either a `GEMINI_API_KEY`, or `LITELLM_BASE_URL`/`LITELLM_API_KEY`
  for the Sprints LiteLLM proxy
- A Qdrant Cloud cluster URL + API key (or use the local `qdrant` service in
  `docker-compose.yml` instead — see `.env`'s `QDRANT_URL`)
- A free [Langfuse](https://cloud.langfuse.com) project (public/secret keys)
- A ServiceNow PDI with the 5 scoped AI fields already added to Incident (`ai_status`,
  `ai_suggested_response`, `ai_confidence`, `human_review_required`, `ai_processed`) — see
  `AI_FIELD_PREFIX` below
- A LiteLLM-proxy-compatible key for the agent's LLM calls (`OPENAI_API_KEY`, same value as
  `LITELLM_API_KEY` — the agent's client and the retrieval/benchmark scripts read different
  env var names for the same underlying key)

## 1. Clone and configure
```bash
git clone <this repo>
cd barq-sprints-ai-servicenow-support-assistant-4
cp .env.example .env
```
Fill in `.env`: `QDRANT_URL`/`QDRANT_API_KEY`, embedding credentials, and Langfuse keys should
be real. `AI_FIELD_PREFIX` must match the scoped field prefix on your specific ServiceNow
instance (System Definition > Dictionary, filter Table=incident — every intern's PDI has a
different scope number). `OPENAI_API_KEY` must be set to the same LiteLLM proxy key as
`LITELLM_API_KEY` (the agent's LLM client reads a different env var name than the retrieval
scripts do for the same underlying credential).

## 2. Install dependencies
```bash
uv lock
uv sync
```

## 3. Seed the knowledge base (first time only)
If your Qdrant collection is empty, populate it with the fixture KB articles matching the
benchmark dataset:
```bash
uv run python benchmark/seed_fixtures.py
```

## 4. Bring up the stack
```bash
docker compose up --build
```
This builds and starts four containers: `api` (FastAPI, port 8000), `worker` (Celery), `redis`,
and `qdrant`. First build takes a few minutes; subsequent builds are cached.

Verify:
```bash
docker compose ps            # all 4 should show Up (redis: healthy)
curl localhost:8000/health   # {"status": "ok"}
```

## 5. Run an end-to-end incident
The webhook now verifies a real HMAC-SHA256 signature over the raw request body (matching
the ServiceNow eligibility Business Rule's signing contract) — not a plain shared-secret
header. With the stack running, in a second terminal (PowerShell example):
```powershell
$secret = "<your SERVICENOW_WEBHOOK_SECRET value>"
$body = '{"sys_id":"<a real Incident sys_id from your PDI>","number":"INC0099001","short_description":"No internet connection","description":"User cannot reach any websites"}'
$hmac = New-Object System.Security.Cryptography.HMACSHA256
$hmac.Key = [System.Text.Encoding]::UTF8.GetBytes($secret)
$sig = [System.BitConverter]::ToString($hmac.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($body))).Replace("-","").ToLower()
curl -X POST localhost:8000/webhook -H "Content-Type: application/json" -H "X-Signature: $sig" -d $body
```
`sys_id` must be a real Incident record's sys_id on your ServiceNow PDI — the worker fetches
the incident for real via the Table API, so a fake sys_id will fail at that step (the failure
is handled cleanly: logged, a work note attempted, incident left `in_progress` for retry).

The API returns `202 Accepted` immediately. Watch `docker compose logs worker -f` to see the
real agent run: fetch (real Table API GET) -> ReAct loop over searchKB/addWorkNote (real
Qdrant retrieval) -> terminal suggestAnswer or requestHR -> real writeback (one atomic PATCH
to the scoped AI fields on the incident, matching `AI_FIELD_PREFIX`).

Sending the same `sys_id` twice returns `{"status": "duplicate"}` on the second call (Redis
SETNX dedup, 24h expiry) rather than enqueueing a second run.

## 6. Run the benchmark harness
```bash
uv run python benchmark/pipeline_benchmark.py --real
```
Outputs `benchmark/PIPELINE_RESULTS.md` (per-incident table) and
`benchmark/pipeline_benchmark_results.json`.

## 7. Send tracing demo data
```bash
uv run python benchmark/traced_demo_run.py
```
Sends a couple of traced incident runs to Langfuse. Check your project's **Traces** tab —
each run should show one trace with 4 nested spans (`incident-fetch`, `kb-retrieval`,
`agent-decision`, `servicenow-writeback`).

## Known stubs / open items (see individual file headers for details)
- **KB content**: fixture articles (`seed_fixtures.py`), not the real ServiceNow knowledge
  base. Real KB content would need re-seeding/re-validation of benchmark numbers.
- **`AI_FIELD_PREFIX`**: must be set per-instance in `.env`; not a code stub, just
  configuration that varies per ServiceNow PDI.
- **Benchmark harness** (`pipeline_benchmark.py`) still uses its own threshold-gate stub
  decision layer, separate from the real agent above — it evaluates retrieval quality
  directly rather than invoking the full LLM agent per benchmark case (would be slow/costly
  to run the real agent 30x per benchmark run). This is intentional, not a gap to fix.

## Resolved since the last revision (real, not stubbed anymore)
- **Agent decision**: the real S3.4 ReAct agent (searchKB/addWorkNote/suggestAnswer/
  requestHR via `agent/s3_worker.py`) is merged and wired into the Celery task — no more
  threshold-gate stand-in in the live pipeline.
- **Celery consumer**: real Redis SETNX dedup (24h expiry) and real incident claim (PATCH
  `ai_status=in_progress`) before the agent runs.
- **Writeback**: real, atomic Table API PATCH to the scoped AI fields — not a log-only stub.
