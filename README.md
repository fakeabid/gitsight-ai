# GitSight PR Review Service

A FastAPI + LangGraph service for automated, actionable pull request code reviews using Google Gemini.

Designed to replace sequential, monolithic LLM calls in pull-request review platforms with parallel chunk analysis, structured schema validation, fallback models, and deterministic aggregation.

---

## Features

- **Parallel Processing:** Splits PR diffs into manageable chunks (up to 15,000 characters each) and processes them concurrently using LangGraph's `Send` API.
- **Structured Output:** Strictly enforced Pydantic schemas eliminate markdown stripping errors and ensure consistent responses.
- **Model Fallbacks:** Automatically falls back across multiple Gemini models (`gemini-3.8-flash`, `gemini-3.5-flash`, `gemini-flash-latest`) to withstand free-tier quota spikes.
- **Accurate Line Anchoring:** Oversized files are split across hunk boundaries with dynamically rewritten `@@` headers to preserve line number accuracy for inline comments.
- **Deterministic Metrics:** Issue counts (`security`, `breach`, `bugs`, `performance`, `codeSmells`), overall confidence, and code complexity are computed in pure Python rather than hallucinated by the model.
- **Resilient & Partial Reviews:** If individual chunks fail after retries, the review succeeds partially with `meta.partial = true`, only returning 502 when every chunk fails.
- **Clean Architecture:** Strict separation between API (`app/api`), service orchestration (`app/services`), graph execution (`app/graph`), and pure domain logic (`app/domain`).

---

## Architecture Overview

```
START
  │
  ▼
prepare_chunks          (pure Python)  Filter noise files, split oversized files, pack into chunks
  │
  ├── no chunks ────────────────────────────────────────┐
  │                                                      │
  ▼  Send() per chunk (parallel, bounded by max_concurrency)
analyze_chunk × N        (subgraph)
  ┌────────────────────────────────────────────────┐
  │ build_prompt → call_llm → validate ──► END     │   Success  → chunk_results
  │                  ▲           │                 │
  │                  └─ retry ───┤ (max N retries) │
  │                              └─► record_failure│   Failure  → failed_chunks
  └────────────────────────────────────────────────┘
  │                                                      │
  ▼◄─────────────────────────────────────────────────────┘
aggregate                (pure Python)  Merge, dedupe, sort, recount, mean confidence, max complexity
  │
  ▼
synthesize_summary       (LLM, skipped if ≤ 1 chunk succeeded)  Unified executive summary
  │
  ▼
END  →  ReviewResult
```

---

## Configuration (Environment Variables)

| Variable | Default | Description |
|---|---|---|
| `SERVICE_API_KEY` | *(Required)* | Secret key required in the `X-API-Key` request header. |
| `GEMINI_API_KEY` | *(Required)* | Google AI Studio API key. |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Primary Gemini model. |
| `GEMINI_FALLBACK_MODELS` | `gemini-3.5-flash,gemini-flash-latest` | Comma-separated or JSON list of fallback models. |
| `GEMINI_TEMPERATURE` | `0.2` | Sampling temperature for review generation. |
| `GEMINI_TIMEOUT_SECONDS` | `60` | Timeout per individual request to Gemini API. |
| `GEMINI_SDK_MAX_RETRIES` | `2` | Internal Google client SDK retry attempts (e.g. on 429). |
| `MAX_CHUNK_CHARS` | `15000` | Maximum character length of each diff chunk. |
| `MAX_TOTAL_CHUNKS` | `5` | Maximum number of chunks to review per PR diff. |
| `NOISE_PATTERNS` | *(21 defaults)* | Comma-separated list of noise file paths/extensions/directories. |
| `MAX_DIFF_CHARS` | `2000000` | Maximum allowed request diff size in characters (exceeding returns HTTP 413). |
| `MAX_CONCURRENCY` | `3` | Maximum number of parallel LLM calls. |
| `CHUNK_MAX_RETRIES` | `2` | Additional retry attempts per chunk inside the subgraph. |
| `RETRY_BACKOFF_SECONDS` | `2.0` | Linear backoff factor between chunk retries (`attempt * backoff`). |
| `REVIEW_TIMEOUT_SECONDS` | `90` | Whole-review timeout (must be lower than caller's client timeout). |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |

---

## API Specification

### Authentication
All routes except `/health` require the `X-API-Key` header matching `SERVICE_API_KEY`. Missing or invalid keys return HTTP 401.

### 1. `POST /v1/reviews`
Analyzes a pull request diff and returns structured findings.

#### Request Body
```json
{
  "prTitle": "Add authentication middleware",
  "prDescription": "Introduces JWT validation and route guards.",
  "diff": "diff --git a/server/auth.js b/server/auth.js\n..."
}
```
*Note: `prDescription` is optional.*

#### Response (200 OK)
```json
{
  "issues": [
    {
      "filePath": "server/auth.js",
      "startLine": 12,
      "endLine": 12,
      "issueType": "Breach",
      "severity": "High",
      "comment": "Hardcoded secrets should not be committed to version control. Use environment variables.",
      "suggestedRemovedCode": "const JWT_SECRET = \"hardcoded-secret\";",
      "suggestedAddedCode": "const JWT_SECRET = process.env.JWT_SECRET;"
    }
  ],
  "executiveSummary": "The PR introduces authentication guards but includes a hardcoded secret in server/auth.js.",
  "overallConfidenceScore": 0.95,
  "finalSuggestionsCount": 1,
  "securityIssuesCount": 0,
  "syntaxErrorsCount": 0,
  "breachesCount": 1,
  "bugsCount": 0,
  "performanceIssuesCount": 0,
  "codeSmellsCount": 0,
  "testCoverageImpact": 0.0,
  "codeComplexity": "Low",
  "meta": {
    "partial": false,
    "chunkCount": 1,
    "failedChunks": [],
    "skippedFiles": [
      {
        "path": "package-lock.json",
        "reason": "generated or non-code file"
      }
    ]
  }
}
```

### 2. `GET /health`
Health check endpoint used by container orchestrators. No authentication required.
```json
{
  "status": "ok"
}
```

### Error Responses
Error responses follow the standard format:
```json
{
  "error": {
    "code": "diff_too_large",
    "message": "Diff has 2500000 characters; the limit is 2000000."
  }
}
```

- **401 `unauthorized`**: Missing or invalid `X-API-Key`.
- **413 `diff_too_large`**: Diff length exceeds `MAX_DIFF_CHARS`.
- **422 Validation Error**: Missing required fields (`prTitle` or `diff`).
- **502 `llm_unavailable`**: All chunks failed LLM analysis after retries and model fallbacks.
- **504 `review_timeout`**: Total review execution exceeded `REVIEW_TIMEOUT_SECONDS`.

---

## Local Development & Setup

### Requirements
- Python 3.11 or higher (Python 3.12 recommended)
- `pip` or virtual environment manager

### Setup
```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies in editable mode with development tools
pip install -e ".[dev]"

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your SERVICE_API_KEY and GEMINI_API_KEY
```

### Running Locally
```bash
uvicorn app.main:create_app --factory --reload --port 8000
```

---

## Testing

```bash
# Run full offline unit and integration test suite
pytest -q

# Run tests with coverage report
pytest --cov=app --cov-report=term-missing

# Run live Gemini test (requires valid GEMINI_API_KEY and RUN_LIVE=1)
RUN_LIVE=1 GEMINI_API_KEY=your_key pytest -m live
```

### Smoke Testing
To run a manual smoke test against a real diff file using live Gemini models:
```bash
python -m scripts.smoke_test path/to/sample.diff
```

---

## Docker & Deployment

### Build and Run with Docker
```bash
# Build the Docker image
docker build -t pr-review-service .

# Run the container
docker run -p 8000:8000 --env-file .env pr-review-service
```

### Deploying to Cloud Providers (Render, Railway, Fly.io, Cloud Run)
- The service is completely stateless and container-ready.
- Expose port `8000` (or allow the platform to bind `$PORT` via the entrypoint).
- Healthcheck path: `/health`.
- Set `SERVICE_API_KEY`, `GEMINI_API_KEY`, and optional overrides in the host's environment settings.

---

## Deliberate Differences from the Legacy C# System

1. **Parallel vs. Sequential:** Chunks are reviewed in parallel rather than sequentially, reducing latency from $O(N)$ to $O(1)$ chunk duration.
2. **File Splitting vs. Truncation:** Large files are split across hunk boundaries with rewritten `@@ -old,count +new,count @@` headers rather than being truncated at 8,000 characters.
3. **Exact Noise Matching:** Noise patterns match path segments, suffixes, or file names, avoiding false-positive matches (e.g. `rebuild/` or `cabin/`).
4. **Calculated Counts:** All metric counts (including `bugsCount`, `syntaxErrorsCount = 0`, `codeComplexity`, and `testCoverageImpact`) are computed deterministically in code from the final issue list.
5. **Unified Executive Summary:** Multi-chunk PRs receive a single synthesized executive summary rather than concatenated per-chunk summaries with trailing line breaks.
6. **Graceful Partial Results:** Individual failed chunks return partial reviews (`meta.partial = true`); 502 is returned only if all chunks fail.
7. **Hallucination Filtering:** Issues reporting file paths not present in the diff are automatically stripped.
8. **Noise-Only Diffs:** Diffs containing only noise files return immediately with an empty issue list without consuming LLM quota.

---

## Known Limitations

- **Malformed Hunk Headers:** If a git hunk header deviates from standard unified diff format (`@@ -o,c +n,c @@`), line rewriting cannot be guaranteed safely, and the hunk is kept intact rather than split.
- **Free-Tier Gemini Limits:** On Google AI Studio free tier, concurrent requests may experience 429 rate limits. `MAX_CONCURRENCY` is set to 3 and fallback models are configured to mitigate this.
