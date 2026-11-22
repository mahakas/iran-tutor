# Multi-provider AI routing and failover

This branch adds ordered provider failover to the existing encrypted provider vault and feature-routing layer.

## Current protocol support

The runtime currently supports providers whose inference API is OpenAI-compatible:

- OpenAI
- OpenAI-compatible hosted endpoints
- Local endpoints exposing the OpenAI-compatible API (for example, a local inference server)

The database and initial provider form still know about Anthropic and Gemini provider types, but their native request protocols are **not** implemented by this hotfix. They are rejected from feature routes rather than being sent to the OpenAI client incorrectly. Native Anthropic and Gemini adapters are a separate follow-up.

## Configure providers

1. Start the real-mode application with `DEMO_MODE=false`.
2. Sign in to the admin area at `/admin`.
3. Add each provider with a unique display name, provider type, API base URL and API key.
4. Select the capabilities actually supported by that endpoint.
5. Use the provider test action and confirm a successful result.
6. Under the feature-route matrix, select a primary provider and add ordered fallbacks. The first fallback is tried before the second, and so on.
7. Enter a model name for each fallback only when it differs from the primary model. Blank fallback model names inherit the primary route model.

Provider API keys are encrypted by the backend using `SECRET_KEY` before storage. API keys are never returned in plaintext by the admin API. Keep `SECRET_KEY` stable and back it up securely: changing it makes already-encrypted provider keys undecryptable until the keys are entered again.

The route API accepts up to eight fallback providers per feature, in addition to the primary provider. Duplicate provider IDs and the primary provider repeated as a fallback are rejected.

## Failover rules

The gateway proceeds to the next configured provider for connection failures, timeouts, malformed/empty JSON responses, HTTP 401/402/403/404, 408, 409, 425, 429 and 5xx responses.

It does not fail over on ordinary request-validation/client errors such as HTTP 400. These usually indicate a bad request or incompatible model configuration and should not be hidden by retrying other providers.

Streaming is special: failover is allowed only before the first response chunk is sent to the student. Once visible output has started, the gateway will not switch providers, because doing so could duplicate or splice the response.

Only the successful provider is recorded as the provider used for the successful AI audit row. The gateway performs quota accounting once for the overall successful call, rather than once per attempted provider. Provider-attempt diagnostics log provider IDs and error types, not API keys.

## Capability-specific routing

Each feature has its own route. At minimum, configure the features you intend to use:

- `chat`, `solve`, `quiz` — text/JSON chat
- `vision_ocr`, `ingest_ocr` — vision-capable chat endpoint
- `stt` — audio transcription endpoint using the OpenAI-compatible transcription API
- `audio_tts` — speech synthesis endpoint using the OpenAI-compatible speech API
- `embedding` — embedding endpoint

All embedding providers in one fallback chain must return vectors with the same configured `EMBEDDING_DIMENSION`, and that dimension must match the vector store collection. A dimension mismatch is a configuration error, not an outage eligible for automatic failover.

A provider may not support every capability. Mark capabilities accurately, then configure separate routes for capabilities such as vision, speech and embedding.

## GitHub Codespaces real-mode setup

The Codespaces account/repository secrets used by the startup script are:

- `SECRET_KEY` — at least 32 random characters
- `AUTH_SECRET` — an independent random value
- `ADMIN_PASSWORD` — at least 12 characters
- `POSTGRES_PASSWORD` — PostgreSQL password

Run from the repository root:

```bash
bash scripts/run-codespaces-real.sh
```

The script starts PostgreSQL, Qdrant and Redis via Docker Compose, installs backend/frontend dependencies if needed, applies Alembic migrations, then starts FastAPI on port 8000 and Next.js on port 3000. It explicitly sets `DEMO_MODE=false`; do not use `scripts/run-live-demo.sh` for real AI inference.

In Codespaces, keep port 3000 Private while testing and keep port 8000 and the database/vector/cache ports Private. Next.js proxies browser `/api/*` requests to the local FastAPI process.

AI API keys are not Codespaces secrets in this design; add them through the admin provider vault so each provider's key can be encrypted and administered independently. Never paste provider keys or other secrets into chat or commit them to Git.

## Remaining production gates

This is an integration/development path, not a production certification. Before public Production deployment, complete the broader security and release-readiness review, change SMS and payment from their demo providers, configure HTTPS/rate limits/backups, verify user/admin authorization, and test every provider/model combination with real credentials and textbook sources. Codespaces is a development environment and should not be used as permanent production hosting.
