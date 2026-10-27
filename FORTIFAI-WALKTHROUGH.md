# Omniflow: Technical Evidence Walkthrough for Fortifai

Reviewed on 20 October 2026. This report describes the working-tree implementation, including existing uncommitted changes, rather than assuming that HEAD or older project narratives describe the current application. It is a technical evidence report, not an assessment of individual authorship or a claim of production adoption.

**Evidence convention:** “Implemented” means supported by source; “tested” identifies an available test, not necessarily a test executed during this review. “Recorded verification” refers to repository documentation of earlier runs. Inferences and proposed improvements are labeled explicitly. Repository-relative paths and symbols identify evidence throughout; Section 10 consolidates it. No dependencies were installed, models downloaded, services started, or pipelines executed for this report. Existing files were not changed.

## 1. Project Overview

Omniflow is a local personal dashboard for tasks, medication schedules/logs, exercise catalogs and workouts, recipes and ingredients, inventory, meals, and media tracking. It combines conventional CRUD interfaces with a local language-model assistant that retrieves records, answers questions, and proposes bounded changes for explicit operator approval. This is personal-data workflow software, not an implemented financial-risk, fraud, or anomaly-detection product. Evidence: `api/app/routers/{tasks,medications,gym,kitchen,media}.py`, `frontend/src/pages/`, and `ai/app/main.py::chat` / `_chat_stream_events`.

Implemented capabilities include:

- Structured PostgreSQL storage and domain APIs, with Pydantic validation and database constraints (`api/app/schemas.py`; `database/init.sql`; Alembic migrations).
- Local embedding and language-model inference through Ollama, hybrid lexical/vector retrieval, and grounded answer prompts (`ai/app/{ollama,retrieval,indexer,main}.py`).
- Ordered, allowlisted action proposals; stored review information; operator approve/reject decisions; transactional mutations with before/after audits (`api/app/routers/ai.py`).
- Streamed assistant responses, proposal review controls, and refresh of client queries following approved changes (`frontend/src/components/ChatBubble.tsx`).
- First-run operator setup, persistent credentials, backups and restore preview, recent activity, service readiness, and containerized installation/testing (`api/app/{auth,credentials,main}.py`; `api/app/routers/backups.py`; `compose.yaml`).

**Development status:** a containerized application with substantial unit/contract tests and opt-in PostgreSQL integration tests, plus a repository record of isolated clean-install and upgrade verification. `tests/VERIFICATION.md` reports successful checks on 17 October 2026. This is stronger evidence than an architecture-only prototype, but does not establish a public deployment, active users, production traffic, service-level objectives, or independently reproducible model quality measurements. The prior verification record is prose, not attached raw CI logs.

**Implemented versus planned/absent:** `todolist.md` marks its listed installation, activity, and test-workflow tasks complete; relevant implementations exist. Those checkboxes alone are not proof of operation. Multi-tenant authorization, statistical anomaly detection, supervised training, fine-tuning, quantitative LLM evaluation, and distributed orchestration were not found in the inspected source. Enterprise recommendations below are proposed future work, not an existing roadmap commitment. Older claims in `README.md`, `RESUME.md`, `WALKTHROUGH.md`, `SIMPLIFIED.md`, or `LLD.md` should be checked against current code before reuse.

## 2. Architecture and Data Flow

### Components

| Component | Responsibility and evidence |
| --- | --- |
| React/TypeScript SPA | Domain pages, React Query caching, chat stream parsing, approval controls; `frontend/package.json`, `frontend/src/App.tsx`, `frontend/src/components/ChatBubble.tsx` |
| Nginx | Serves built assets; proxies API calls; disables buffering for chat; blocks `/api/internal`; `frontend/nginx.conf` |
| API service | Operator boundary, domain mutations, proposals, approval, audits, backups and activity; `api/app/main.py`, `api/app/routers/`, `api/app/mutations.py` |
| AI service | Retrieval/index synchronization, intent classification, action planning, answer generation; `ai/app/main.py`, `ai/app/ollama.py` |
| PostgreSQL + pgvector | Relational source records, JSONB metadata, full-text/vector indexes, proposal state and audit; `database/init.sql`, `alembic/versions/` |
| Ollama | External inference runtime implementing embedding/chat HTTP endpoints; project code is the client and orchestration layer, not the model implementation; `ai/app/ollama.py::ModelRuntime` |
| Startup/tool containers | Secret initialization, migrations/role setup, model availability, tests, diagnostics and showcase fixture; `compose.yaml`, `scripts/startup/`, `docker/` |

Python services use FastAPI, Pydantic, asyncpg, and httpx. Their requirements pin versions; the migration environment uses Alembic, SQLAlchemy and psycopg with bounded version ranges. Runtime images use Python 3.12 and separate non-root users (`docker/python-services.Dockerfile`). The shared dependency stage installs `api/requirements.txt`; `ai/requirements.txt` currently matches it, so future divergence requires build maintenance.

### Input to output

1. The browser establishes an operator bearer session and CSRF token. `frontend/src/api/client.ts` stores tokens in session storage. Nginx forwards requests to the API; `api/app/main.py::operator_boundary` applies authentication except for explicitly listed public/service paths.
2. Ordinary domain requests use SQL-backed routers. AI chat passes through `api/app/routers/ai.py::ai_chat` or `ai_chat_stream`, using a service secret on internal AI calls.
3. With context enabled, `ai/app/main.py::chat` / `_chat_stream_events` first applies `_retrieval_scope`, embeds the message, and retrieves records. Retrieval happens **before** classification in execution order, but retrieved content is excluded from the classifier's intent prompt.
4. `ModelRuntime.classify` first classifies the current message as read/write/chat. Only a write decision invokes a second planning call. `_build_reference_context` supplies only positive direct entity IDs when exactly one candidate exists for an entity type.
5. A read receives structured JSON records and a grounding instruction, then a generated answer. No retrieved records produces a deterministic “couldn't find” response. Chat without grounded reads uses a general assistant prompt. Up to five prior user/assistant messages may accompany answer generation; classification/planning uses the current message instead.
6. A write calls `_execute_write`, which creates a UUID and posts a **proposal**, despite the function's historical name. The API stores actions and an API-generated review without executing domain changes.
7. The operator reviews and approves through the SPA. `approve_ai_proposal` locks proposal state, checks review digests, resolves selectors and references, executes actions in order, writes audits, and marks the request committed in one database transaction. Rejection only changes proposal state.
8. Later index synchronization reflects source changes. There is no synchronous read-after-write embedding update in the approval path.

### Storage and execution boundaries

`SOURCE_QUERIES` in `ai/app/indexer.py` defines 12 logical retrieval sources: tasks, medications, medication plans/logs, exercises, training sets, workouts, recipes, ingredients, inventory, meals, and media. Some names map to different physical tables, e.g. `exercises` → `exercise_catalog`, `media` → `media_items`. Joins enrich records with related names; the index is a denormalized search representation, not a complete relational database export.

`ai_entity_embeddings` stores entity identity, content, JSONB metadata, a 1,024-dimensional vector, model name, index version, hash, and update timestamp. It has a generated `simple`-configuration `tsvector`, GIN indexes for metadata/text, and an HNSW cosine index (`database/init.sql`, `ai_entity_embeddings` DDL). Index existence does not demonstrate use by the actual query plan.

Migration `009_separate_runtime_roles.py::upgrade` grants AI read access to existing source tables and write access to embeddings, while revoking access to proposal/audit tables. The API role has broader CRUD privileges; administrative migration credentials are separate. This is service-level privilege separation, not per-user row-level isolation.

## 3. Hands-on AI/ML Implementation

### 3.1 Embedding and index pipeline

**Problem:** make structured personal records searchable by natural-language similarity as well as exact terms.

**Technique/model:** pretrained `bge-m3` via Ollama `/api/embed`, used for inference only. `ai/app/settings.py::get_settings` restricts the configured embedding model family to `bge-m3` with an optional tag because the database contract is `VECTOR(1024)`. `ModelRuntime.embeddings` checks response count, vector length, and numeric element types, rejecting booleans. It does not explicitly test each element with `isfinite`.

**Preparation:** `SOURCE_QUERIES` builds one textual document per entity using SQL concatenation and selected joined names, alongside explicit JSON metadata. There is no document chunker, tokenizer implementation, training dataset, label generation, or learned preprocessing. Numeric metadata is handled carefully with Decimal/string conversions in hashing/retrieval rather than indiscriminately converting it through binary floats.

**Indexing rules:** `indexer._hash` computes SHA-256 over canonicalized text plus metadata. `reindex` skips records only when version, hash, and embedding-presence match. Changes are embedded in batches of 32 and upserted transactionally per batch. Removed entities, obsolete models/versions, and unknown sources are cleaned up. Metadata-only changes also cause re-embedding, even though the embedding input is text alone. This simplifies synchronization but may spend inference work unnecessarily.

**Configuration/use:** default index version 2; automatic synchronization defaults to a 60-second interval. `synchronize_index` serializes runs with an asyncio lock and records attempt/success/error timestamps. This lock and state are process-local. Indexing is incremental in embedding computation, but source rows are fully fetched each pass; it is not incremental change-data capture.

### 3.2 Hybrid retrieval and deterministic query scoping

**Problem:** find relevant records while retaining literal term matches and structured constraints.

`ai/app/retrieval.py::hybrid_search` embeds the query and filters eligible rows by configured model/version, JSONB containment, and allowlisted source keys. It combines:

- PostgreSQL full-text matching using `websearch_to_tsquery('simple', query)` and `ts_rank_cd`.
- Cosine distance via pgvector `<=>`, with default maximum distance **0.60**.
- Reciprocal rank fusion: `score = lexical contribution + semantic contribution`, each present contribution `1 / (60 + rank)`.

Each branch has a 50-row limit; final output defaults to 8 and is capped at 20. The branch SQL uses window ordering for rank but does not express a separate top-level branch `ORDER BY` before `LIMIT`; tie/candidate determinism should be verified before claiming exact stable top-50 behavior. No query-plan evidence or measured ANN recall is present.

`ai/app/main.py::_retrieval_scope` uses regular expressions to select domains and, for task-only scopes, priority and completion metadata filters. This is deterministic rule-based routing, not a trained classifier. It can misinterpret natural-language negation or modifiers; for example, the existence of a priority word does not prove the user intended that filter. No learned reranker, calibrated relevance probability, or fallback lexical-only path exists: query embedding happens before the SQL search, so an embedding failure prevents both retrieval branches.

The RRF score is a ranking score, not accuracy, confidence, anomaly severity, or a risk score. The 0.60 cutoff and fusion constant are configured choices, not evidence of optimized hyperparameters.

### 3.3 LLM intent gate and bounded action planning

**Problem:** translate an explicit request into an approved domain operation without granting a model arbitrary SQL or tool execution.

`ai/app/ollama.py::ModelRuntime.classify` makes one schema-constrained call for `IntentResponse`, and a second for `ClassifierActionPlan` only for write intent. Current message text is the sole user input at the first trust stage. The second stage receives an allowlist and a tool message containing numeric reference IDs, not raw retrieved descriptions. The API and classifier maintain matching registries covering 41 actions across dashboard domains (`CLASSIFIER_WRITE_ACTION_NAMES`; `api/app/schemas.py::AI_WRITE_ACTIONS`).

`ClassifierResponse` rejects write-without-actions and non-write-with-actions combinations. An empty planner result is deliberately returned as chat. JSON extraction supports plain, fenced and prose-wrapped JSON, strips `<think>` blocks, and uses Decimal parsing (`extract_json_value`). Extraction is tolerant, not a guarantee that the model obeyed every semantic requirement. Action arguments remain generic dictionaries at the outer planner schema; action-specific validation happens in API mutation preparation.

Inference settings: temperature 0.1 for JSON/schema calls, 0.25 for ordinary generation, and top-p 0.9. Compose defaults to **`qwen3:4b`**, whereas the standalone Python settings default is **`qwen3:8b`**. Model choice must therefore be stated with the deployment context. A request's model override is applied to answer generation, not to the default classifier/planner calls (`main.chat`; `ModelRuntime.classify`). No model-selection benchmark explains these defaults.

`api/app/mutations.py::_resolve_references` supports context references and earlier action results. `_prepare_action_arguments` normalizes aliases, rejects unsupported fields and validates domain-specific schemas. `_resolve_entity_id` uses exact trimmed, case-insensitive name matching, rejects ambiguous matches, and validates ID/name consistency. `_execute_action` dispatches deterministic SQL handlers. Prompt instructions not to invent IDs are not an independently enforced provenance proof: a syntactically valid existing ID can still be a semantically wrong target. Review remains important.

This is a finite, application-specific agentic workflow. It has no autonomous iterative planning loop, external browsing agent, learned policy, unrestricted tool executor, or general task scheduler.

### 3.4 Retrieval-augmented generation and streaming

`ai/app/main.py::_answer_read` and `_grounded_messages` serialize source identity, metadata fields, and search text into a JSON context. Prompts tell the model to treat records as untrusted data, answer only from them, preserve field meanings, admit insufficiency, and not claim mutations. Outputs include answer text and retrieved records; there is no automatic factual verifier or sentence-level citation checker.

`ModelRuntime.stream_chat` reads Ollama NDJSON fragments; `_chat_stream_events` emits application status/delta/result/done/error events; the API and Nginx forward them to the browser. Streaming improves the opportunity to display partial text, but no measured time-to-first-token improvement is supplied. Grounding and injection resistance of real generations remain unquantified.

### Training, tuning, optimization, and inference: precise distinction

| Category | Repository evidence |
| --- | --- |
| Model training from scratch | Not demonstrated: no optimization loop, labeled training corpus, loss, checkpoints, or training framework usage in the AI implementation. |
| Fine-tuning/adaptation of weights | Not demonstrated: no adapters, gradient updates, or fine-tuning jobs. |
| Hyperparameter tuning | Not demonstrated: fixed/configurable temperature, top-p, distance cutoff, retrieval limits and fusion constant exist, but no sweep, held-out selection or comparative experiment. |
| Pipeline engineering/optimization | Demonstrated: hash-based embedding reuse, batching, shared HTTP client, pools, streaming, deterministic filters and bounded contexts. Performance gains are not measured. |
| Pretrained inference | Directly demonstrated: Ollama chat and embedding clients, structured prompts and output parsing. Model weights/runtime are third-party components. |
| Traditional ML/statistical anomaly detection/time-series modeling | Not demonstrated. Date-bearing domain records and inventory/domain constraints are not anomaly models. `risk_level` READ/WRITE is an operation category, not learned risk intelligence. |

## 4. Evaluation and Validation

### Available automated checks

Tests use Python unittest, AsyncMock/fake connections and httpx mock transports, plus PostgreSQL-gated integration classes. `tests/README.md` and `compose.yaml` describe separate test, database-test, migration-test, smoke and frontend build workflows. These were inspected, not rerun here.

| Area | Specific evidence | What it establishes / does not establish |
| --- | --- | --- |
| Classifier trust boundary | `tests/test_ai_classifier.py::ClassifierPromptTests.test_retrieved_prompt_injection_cannot_change_read_intent` | Checks constructed prompts and mocked responses; does not estimate adversarial success rates against Qwen. |
| Structured outputs | `test_classifier_emits_ordered_actions_and_structured_schema`, `test_json_extraction_handles_thinking_fences_and_prose` | Expected schemas, ordering and parsing behavior on controlled examples, not real-model action accuracy. |
| Retrieval wiring | `test_hybrid_search_uses_generated_lexical_index_and_source_keys`, `test_retrieval_scope_applies_explicit_domain_and_task_filters` | SQL parameters and deterministic scope behavior, not relevance judgments. |
| Index lifecycle | `RetrievalIntegrationTests.test_removed_source_cleanup_and_index_health_lifecycle` | Real PostgreSQL lifecycle and health transitions, but embeddings are patched to zero-filled 1,024-element vectors and model tags are mocked. It is not a semantic retrieval benchmark. |
| Mutations | `tests/test_ai_actions.py::ExecuteActionHandlerTests`, `AIActionIntegrationTests` | Exact/ambiguous resolution, references, handler invariants, audits and rollback. Real DB tests include late failure rollback and audit failure rollback. |
| Approval | `ApprovalWorkflowTests`; `AIActionIntegrationTests.test_pending_proposal_requires_explicit_approval` | Proposal persistence versus execution and decision transitions. Direct helper calls do not by themselves prove all HTTP authentication/digest behavior; separate boundary tests must be considered. |
| Other reliability | `tests/test_backups.py`, `test_auth.py`, `test_credentials.py`, `test_migrations.py`, `test_public_routes.py`, `test_activity.py` | Snapshot validation, credentials, constraints, domain rules, transactional activity and source isolation. |
| Frontend/contracts | `tests/test_contracts.py`; `frontend/package.json`; `frontend/Dockerfile` | API/frontend contract assertions plus lint/typecheck/build workflow. No automated browser end-to-end suite was identified. |

### Reference fixtures, manual validation and artifacts

`docker/demo/seed_showcase.py::EXPECTED`, `seed_showcase`, and `inspect_showcase` define a small deterministic showcase fixture, including duplicate task titles for ambiguity and a safety-note record containing hostile instruction-like text. The seeder checks expected fixture identity/counts and refuses unsafe partial fixture states; `tests/test_showcase_seed.py` tests this behavior. This is useful for manual demonstrations and regression of data setup. It is not a labeled question-answer golden dataset or an automatically scored safety benchmark.

`docker/tests/smoke.py::run_read_checks` checks frontend health, blocked internal routes, domain list shapes and AI health. Its AI health check does not ask a model a question or score an answer. `run_write_check` creates/updates a temporary task and attempts cleanup. Backup preview and proposal review provide additional operator inspection workflows (`preview_restore`; `ChatBubble.tsx::decideProposal`).

`tests/VERIFICATION.md` records 198 host-safe/mocked tests with DB classes skipped, 14 PostgreSQL integration tests, two owner-permission migration tests, and frontend checks passing on 17 October. Treat these as historical reported counts, not newly measured results or a coverage percentage. It also records clean installation, schema upgrade to revision 011, credential recovery, and isolated demo startup. No raw execution transcript or independent deployment telemetry is supplied by that record.

### Metrics actually computed and evaluation gaps

Computed values include RRF ranking scores (`hybrid_search`); index totals/stale counts and indexed/unchanged/deleted counts (`index_status`, `reindex`); sync attempts/timestamps (`synchronize_index`); per-request duration in milliseconds and HTTP status (`api/app/main.py::request_log`); backup row counts (`export_backup`); and invalid constraint/violating-row counts (`docker/tests/check_constraints.py::find_invalid_check_constraints`, `count_violations`). These are operational measurements and diagnostics, not model-quality metrics.

Errors are distinguished through HTTP status codes, action-index validation details, missing-model/index readiness fields, exceptions/logs, and migration connection-error categorization (`_translate_action_error`; AI `health`; `scripts/startup/run_migrations.py::_connection_error_category`). There is no centralized model-failure taxonomy, experiment tracker, confusion matrix, precision/recall, recall@k, MRR/nDCG, faithfulness score, real-model attack evaluation, latency benchmark, or cost-per-request report in the inspected implementation. No quantitative claim about model or retrieval quality is defensible from these tests alone.

## 5. Reliability and Failure Handling

### Implemented safeguards

- **Input bounds:** extra fields forbidden by outer Pydantic models; trimmed bounded strings; positive IDs; bounded action batches (1–20), chat message lengths and history (at most five); enum/domain checks and Decimal-backed quantity constraints (`api/app/schemas.py`; `ai/app/main.py` request models). “StrictModel” names should not be read as global strict typing: the base configuration forbids extras; individual fields add their own strictness.
- **Deterministic mutation validation:** unsupported action/argument rejection; exact entity resolution; reference validation; guarded inventory adjustments; media progress consistency; explicit SQL handlers (`api/app/mutations.py::_validate_supported_arguments`, `_resolve_entity_id`, `_resolve_references`, `_prepare_action_arguments`, `_execute_action`). Foreign-key/check/unique failures map to 409 or 422 in API exception handlers.
- **Human approval:** service-authenticated ingestion only stores proposals. Browser approval requires operator authentication and CSRF/origin checks. Proposal rows are locked with `FOR UPDATE`; non-pending decisions are rejected. No direct mutation HTTP route wraps `execute_ai_action`; it remains a test/internal helper (`api/app/routers/ai.py`; `test_direct_internal_mutation_http_route_is_removed`).
- **Atomicity/audit:** action execution, per-action audit inserts, and committed status share the approval transaction. An audit insert failure aborts domain changes. Unique `(request_id, action_index)` audit identity and proposal status checks constrain replay (`database/init.sql`; `_run_action_batch`; integration rollback tests).
- **State integrity:** database constraints reinforce application validation, including finite numeric constraints (`alembic/versions/007_harden_domain_constraints.py`, `010_finite_numeric_constraints.py`). Audit rows contain resolved arguments, entity identity and before/after state. Migration 011 adds transactional manual/restore activity triggers; AI activity uses existing audits to avoid duplicate events.
- **Credential/session handling:** generated file-backed service credentials; separate secret volumes; PBKDF2-SHA256 with 600,000 iterations and random salt for newly set operator passwords; locked, fsynced atomic replacement; credential fingerprints invalidate sessions on reset (`scripts/startup/init_secrets.sh`; `credentials.set_password`; `auth._session`). Legacy plaintext credentials remain accepted by `credentials.verify` for compatibility.
- **Request boundary:** eight-hour in-memory sessions, 1,024-session cap, login-failure limiting, host and same-origin checks, CSRF tokens; Nginx internal-route blocking and local-only published bind by default (`auth.py`; `frontend/nginx.conf`; `compose.yaml`). Showcase mode intentionally bypasses normal password authentication.
- **Backup integrity:** bounded streaming input at 250 MiB, format/version/table/column/value/relationship validation; repeatable-read read-only export; transactional restore in dependency order; sequence adjustment; pending proposal rejection on non-AI restores (`backups.py::_read_restore_body`, `_parse_snapshot`, `_validate_snapshot_relationships`, `export_backup`, `restore_backup`). Database sequence advancement is not generally transactional even when row changes roll back; do not promise gapless IDs.
- **Failure/recovery:** request timeouts, model-response validation, classification fallback to read/chat rather than writes, structured streaming errors, proposal timeout reporting with a reconciliation UUID, periodic synchronization retry on a later loop, startup model-pull retries and migration connection retries (`ai/app/main.py`; `ollama.py`; `indexer.sync_loop`; `scripts/startup/`). No automatic retry of ambiguous write requests is performed.
- **Readiness/observability:** API checks exact schema revision and core tables; AI checks DB, model tags, index state and successful synchronization; request IDs/durations and sync failures are logged. AI shutdown uses bounded task cancellation and pool close (`api/app/db.py::ready`; `ai/app/main.py::health`, `_stop_sync_task`; `ai/app/db.py::close_pool`).

### Important limits

1. **Review digest is not full optimistic concurrency control.** `_build_review` hashes proposed arguments, selected target IDs/names and dependencies. Recomputing it catches changes represented there, but not every domain field. It is a read-only review, not a dry-run of full argument validation/execution. It does not lock every reviewed target through the entire review/approval interval. Do not claim that all stale state or semantic mis-targeting is prevented.
2. **Approval is replay-resistant, not a universal exactly-once API.** A repeated approval encounters a non-pending state; duplicate UUID insertion conflicts rather than returning a cached successful result. A new chat retry generates a new UUID and can create a duplicate logical proposal. `_execute_write` appropriately warns to check pending state after timeout.
3. **Grounding is a prompt-level safeguard.** Retrieved text is excluded from write-intent classification, but answer generation sees untrusted records. No formal prompt-injection immunity or hallucination bound is demonstrated.
4. **Index health has a narrow definition.** `index_status` checks stored rows for wrong model/version, missing vectors and unknown sources. It does not compare current source hashes, discover missing source entities, or measure source-to-index lag. A zero stale count is not proof of up-to-date data. Batches commit independently, so an interrupted sync can leave a partially refreshed index.
5. **Audit is not immutable compliance storage.** The API role has broad table privileges; AI backup/restore includes persisted AI state. Activity displays a generic Operator actor; hashed decision attribution is not organization-wide identity management. Logs/audits are not a tamper-proof distributed trace or externally anchored ledger.
6. **Operational limitations remain.** Sessions, throttling and sync locks are in memory; no cross-replica coordination, circuit breaker, durable work queue or general chat-rate limiter is implemented. HTTP clients have timeouts, but there is no end-to-end latency budget. Health failures do not themselves establish an automated failover strategy.

## 6. Engineering Decisions and Tradeoffs

| Observed choice | Benefit and cost; rationale status |
| --- | --- |
| Separate intent decision from context-assisted planning | Explicitly documented in classifier prompts: stored content cannot alter the intent decision through inclusion in that prompt. Costs a second sequential LLM call for writes; current-message-only planning limits conversational references. |
| LLM proposes; Python/SQL validates and executes | Evident from proposal/approval paths. Inference: constrains probabilistic reasoning to a bounded interface and keeps mutations transactional. Does not guarantee the proposal captures user intent. |
| One PostgreSQL system for relational and search data | Implemented in schema and retrieval SQL. Inference: simplifies local operations and joins; couples search load, indexing and transactional workload. No comparative vector-database benchmark was found. |
| Lexical/vector RRF | Combines rank lists without comparing raw lexical scores to cosine distances. That mathematical property is evident in the SQL; a historical model/algorithm selection rationale is not documented there. Adds embedding dependency even to literal searches. |
| Hash-based incremental embeddings | Explicit hash contract includes metadata. Avoids inference on unchanged records but still scans sources, holds a DB connection during model calls, and can re-embed unchanged text after metadata edits. |
| Exact rather than fuzzy mutation selectors | Explicit ambiguity checks favor refusing unclear names. Inference: reduces accidental writes but requires IDs/clarification for duplicates and spelling variants. Retrieval similarity is not used as mutation identity proof. |
| Local Ollama with small default reasoner | Configured in Compose; inference: avoids a hosted inference dependency for ordinary operation but shifts memory/compute/model availability to the user's machine. No documented speed/quality comparison proves 4b superior to 8b. |
| Shared HTTP client, bounded pools, streaming | Explicit lifecycle and connection limits reduce resource churn and support incremental display. No measured throughput or latency gain supports numerical improvement claims. |
| Explicit approval and atomic batches | Adds a human step and transaction duration but avoids committing a partial composite action. API-level review can still be incomplete or stale in fields outside its digest. |
| Single-operator authentication | Simple local deployment; process memory and generic actor identity do not support enterprise identity, tenancy, or high availability without redesign. |

## 7. Scale, Performance, and Deployment

**Deployment actually represented:** Docker Compose with PostgreSQL 16/pgvector, Ollama 0.32.4, separate API/AI containers, frontend Nginx, one-shot secret/migration/model initialization, and persistent database/model/secret volumes. Only frontend port 3001 is published by default and binds to 127.0.0.1. Runtime commands start one Uvicorn process per service; no multi-worker setting, Kubernetes resources, managed-cloud deployment or horizontal autoscaling configuration appears in this path (`compose.yaml`; `docker/python-services.Dockerfile`). `compose.showcase.yaml` supplies a separate demo configuration. No live deployment was verified in this review.

**Demonstrated workload:** the showcase is deliberately small: five tasks (including two identical ambiguity titles), one medication and plan, two exercises, one training set, one recipe, three inventory items, one media item, plus a medication log, workout and meal (`docker/demo/seed_showcase.py::EXPECTED`, `inspect_showcase`). Tests operate on small fixtures. These are not evidence of thousands of users or million-record retrieval.

**Resource controls rather than throughput measurements:** API pool defaults to 2–10 connections in Compose; AI pool to 1–5; model HTTP client to 50 connections/20 keepalives; model calls have 180-second timeouts and client initialization has a 10-second connect timeout. Compose defaults to one loaded model and one parallel Ollama request. With embedding and reasoning models both used, model switching may matter; that is an inference, not a measured bottleneck.

**Likely scaling constraints, inferred from code:** full-source fetches and Python ID/hash maps on each sync; sequential per-source embedding batches; held DB connections during inference; possible expensive materialization/sorting in the retrieval CTEs; no evidence that HNSW is used by this query; bounded top-k context cannot answer exhaustive aggregate questions over all records; process-local locking/readiness/sessions; in-memory JSON backup construction and restore parsing. Increasing timeouts or pool sizes alone would not solve these issues.

**Performance evidence:** request durations are logged but no percentile series, benchmark artifacts, load tests, model-token throughput, memory measurements or concurrency limits validated under load were found. Historical test counts and health checks must not be presented as performance measurements.

**Enterprise changes proposed, not implemented:** introduce tenant-aware authorization and identity/role mapping; protect secrets and transport for non-local operation; use durable shared sessions and distributed rate limits; coordinate background index jobs and use change tracking with explicit freshness/version checks; inspect SQL plans and benchmark real retrieval quality before scaling; add bounded queues/backpressure and inference capacity planning; add real-model regression datasets, adversarial evaluations and model-version pinning; strengthen target version checks at approval; collect tracing/metrics with operational objectives; establish tested backup recovery, high availability and audit-retention/tamper-resistance policies. Each addresses a limit described above rather than an already demonstrated capability.

## 8. Fortifai Relevance

| Requirement | Classification | Evidence and boundary |
| --- | --- | --- |
| Applied ML/deep learning | **Partially demonstrated** | Practical integration of pretrained embedding/LLM inference and data preparation (`ModelRuntime`, `SOURCE_QUERIES`). No training, fine-tuning, model architecture implementation or measured predictive experiment. |
| Statistical or anomaly-detection techniques | **Not demonstrated** | Retrieval ranks and deterministic domain constraints are not statistical anomaly detection; no anomaly scores, baselines, forecasting or time-series model. |
| LLM and agentic systems | **Directly demonstrated** | Two-stage structured planning, bounded action registry, reference resolution, RAG, streaming and approval (`classify`, `_run_action_batch`). Scope is a finite workflow, not autonomous general-purpose agency. |
| Structured-data retrieval and reasoning | **Directly demonstrated** | SQL-derived text/JSON metadata, source/metadata filtering, lexical/vector fusion and record-grounded answers (`SOURCE_QUERIES`, `hybrid_search`, `_answer_read`). No arbitrary text-to-SQL analytics or exhaustive aggregation reasoning. |
| Model evaluation and regression testing | **Partially demonstrated** | Extensive deterministic/mock regression and real-DB integrity checks. Model quality, semantic retrieval relevance and real-model safety are not quantitatively evaluated. |
| Production Python engineering | **Directly demonstrated** | Async services, schemas, pools, transactions, bounded requests, migrations and Docker workflows. This describes engineering mechanisms, not proven production operation. |
| Reliability, observability and auditability | **Directly demonstrated** | Atomic audits, review/approval, credentials, readiness, logs, activity and restore checks. Enterprise monitoring, tamper-proof audit, multi-tenant identity and HA remain absent. |

The strongest transferable discussion is how to contain probabilistic model output within deterministic validation and transactional execution. A defensible Fortifai discussion should explicitly separate that experience from risk-model development or statistical anomaly detection that this project does not contain.

## 9. Technical Interview Deep Dive

### 1. How does hybrid retrieval rank a record, and how do you know it works?

`retrieval.hybrid_search` filters model/version/source/metadata, ranks full-text matches and cosine-distance candidates, then adds `1/(60+rank)` contributions. Default semantic cutoff is 0.60 and final k is 8. Tests verify SQL wiring and lifecycle; they do not establish relevance quality. I would need judged queries, recall@k/ranking metrics, and query-plan checks before claiming tuned retrieval or effective ANN acceleration.

### 2. Why can a malicious stored task not directly authorize a write?

`ModelRuntime.classify` sends only the current user message to the intent gate; the write planner receives numeric reference context rather than task prose. Even a write plan only becomes a proposal. API authentication, explicit approval and allowlisted handlers control execution. This reduces one injection path, but real-model robustness and wrong-target proposals are not fully eliminated (`_build_reference_context`, `create_ai_proposal`, `approve_ai_proposal`).

### 3. What happens if action three fails after two successful SQL operations?

All actions and audits execute within `approve_ai_proposal`'s transaction. Failure exits before commit, rolling back earlier row changes and audit entries; status remains uncommitted. `AIActionIntegrationTests.test_late_validation_failure_rolls_back_actions_and_audits` and `test_audit_insert_failure_rolls_back_real_domain_mutation` exercise this. Database sequence values may still advance; atomic business state does not imply gapless IDs.

### 4. Does the approval digest solve concurrent modification?

Only partly. `_build_review` hashes arguments, target identity/display names and dependencies, and approval recomputes it. Changes outside this payload need not change the hash. It is not a full before-state version check or a serializable dry-run. A stronger approach would bind expected row versions and validate them while holding appropriate mutation locks.

### 5. What exactly did you train or optimize?

The repository demonstrates no training or weight fine-tuning. It invokes pretrained bge-m3 and Qwen through Ollama. Work represented in code is prompt/schema design, orchestration, deterministic validation, retrieval configuration and engineering optimizations such as hashing/batching/client reuse. No empirical hyperparameter search or measured performance improvement is recorded.

### 6. Can a healthy index still answer with stale data?

Yes. `index_status` counts malformed/outdated stored index rows but does not compare source records to indexed hashes or detect missing new records. Background `reindex` eventually refreshes them; per-batch commits allow partial refresh. Health and source freshness are different contracts. For stronger guarantees I would add change/version tracking and a measurable freshness bound.

### 7. What happens after an ambiguous network timeout on a write request?

`_execute_write` returns the proposal UUID and instructs the user to check pending proposals. It does not automatically replay the request. Approval locks state and rejects repeated decisions, but a new chat request can create a new UUID for the same logical operation. This is not exactly-once delivery; durable idempotency and result reconciliation would need a stronger client/server contract.

### 8. What would break first under many concurrent users?

There is no load-test evidence to identify a measured first bottleneck. Plausible limits include single-parallel Ollama inference, held DB connections during indexing, full-source scans, and process-local authentication/sync state. Multi-user access also requires a tenant/identity design, not just more replicas. Evidence is in `compose.yaml`, both `db.py` modules, `indexer.reindex` and `auth.py`.

## 10. Evidence Index

Strength: **A** = source plus targeted test; **B** = source/configuration evidence without quantified runtime validation; **C** = historical narrative only. These labels measure support for a claim, not overall software quality.

| Technical claim | Supporting file path | Relevant function/class/test | Strength | Qualification |
| --- | --- | --- | --- | --- |
| Local pretrained model inference | `ai/app/ollama.py`; `ai/app/settings.py`; `compose.yaml` | `ModelRuntime.chat`, `embeddings`, `get_settings` | B | Third-party weights/runtime; Compose 4b vs standalone 8b default. |
| 1,024-dimensional embedding contract | `ai/app/ollama.py`; `database/init.sql` | `embeddings`; `ai_entity_embeddings` | B | Numeric shape checks; no explicit per-element finite test. |
| Twelve structured retrieval sources | `ai/app/indexer.py`; `tests/test_ai_classifier.py` | `SOURCE_QUERIES`; `test_source_queries_and_reference_context_are_aligned` | A | Selected projections, not full schema semantics. |
| Hash/version-based embedding reuse | `ai/app/indexer.py`; `tests/test_ai_classifier.py` | `_hash`, `reindex`; `test_reindex_uses_content_hash_and_index_version` | A | Full scans remain; metadata-only changes re-embed. |
| Hybrid RRF retrieval | `ai/app/retrieval.py`; `tests/test_ai_classifier.py` | `hybrid_search`; `test_hybrid_search_uses_generated_lexical_index_and_source_keys` | A | Wiring tested; relevance and query plans unmeasured. |
| HNSW and GIN index definitions | `database/init.sql` | `idx_ai_entity_embeddings_vector`, `..._content`, `..._metadata` | B | No proof of planner use or benchmarked speedup. |
| Deterministic source/task filters | `ai/app/main.py`; `tests/test_ai_classifier.py` | `_retrieval_scope`; `test_retrieval_scope_applies_explicit_domain_and_task_filters` | A | Regex rules, not learned semantic parsing. |
| Retrieved text excluded from intent gate | `ai/app/ollama.py`; `tests/test_ai_classifier.py` | `classify`; `test_retrieved_prompt_injection_cannot_change_read_intent` | A | Mocked structural test, not real-model attack rate. |
| Bounded structured action planning | `ai/app/ollama.py`; `api/app/schemas.py`; `tests/test_ai_actions.py` | `ClassifierActionPlan`, `AIActionRequest`, `AllowlistTests` | A | Arguments receive full validation later. |
| Safe reference/name resolution | `api/app/mutations.py`; `tests/test_ai_actions.py` | `_resolve_references`, `_resolve_entity_id`; `test_name_resolution_is_exact_and_ambiguity_safe` | A | Exact identity checks do not prove user intent. |
| Grounded answer prompts | `ai/app/main.py`; `tests/test_ai_classifier.py` | `_answer_read`, `_grounded_messages`; `test_read_answer_marks_stored_commands_as_untrusted_data` | A | No factuality scoring. |
| Streaming through application layers | `ai/app/ollama.py`; `ai/app/main.py`; `api/app/routers/ai.py`; `frontend/nginx.conf` | `stream_chat`, `_chat_stream_events`, `_proxy_ai_chat_stream` | B | No measured latency improvement. |
| Proposal persistence without writes | `api/app/routers/ai.py`; `tests/test_ai_actions.py` | `create_ai_proposal`; `test_internal_proposal_persists_without_executing_domain_action` | A | Full domain validation deferred until execution. |
| Explicit approval and rejection | `api/app/routers/ai.py`; `frontend/src/components/ChatBubble.tsx`; `tests/test_ai_actions.py` | `approve_ai_proposal`, `reject_ai_proposal`, `decideProposal`, `ApprovalWorkflowTests` | A | Review digest covers review fields, not full row state. |
| Atomic ordered mutations and audits | `api/app/routers/ai.py`; `tests/test_ai_actions.py` | `_run_action_batch`; `test_late_validation_failure_rolls_back_actions_and_audits` | A | Test availability plus prior verification record; not rerun here. |
| Duplicate audit/request protection | `database/init.sql`; `api/app/routers/ai.py` | `uq_ai_mutation_audit_request_action`, `approve_ai_proposal` | B | No universal idempotent response cache or logical deduplication. |
| Runtime database privilege separation | `alembic/versions/009_separate_runtime_roles.py`; `scripts/startup/run_migrations.py` | `upgrade`, `provision_runtime_roles` | B | Service roles, not tenant isolation. |
| Numeric/schema constraints | `api/app/schemas.py`; `alembic/versions/010_finite_numeric_constraints.py`; `tests/test_ai_actions.py` | Domain models; `test_decimal_constraints_match_postgresql_precision` | A | Constraints validate domain values, not anomalies. |
| Persistent credential hashing/reset | `api/app/credentials.py`; `tests/test_credentials.py` | `set_password`, `verify`, `fingerprint` | A | Legacy plaintext accepted; session state remains in memory. |
| Authentication and mutation boundary | `api/app/auth.py`; `api/app/main.py`; `tests/test_auth.py` | `require_operator`, `operator_boundary` | A | Local single-operator design; demo intentionally differs. |
| Transactional backup/restore | `api/app/routers/backups.py`; `tests/test_backups.py` | `export_backup`, `restore_backup`, `BackupIntegrationTests` | A | JSON snapshots; no measured disaster-recovery objectives. |
| Transactional activity/source isolation | `alembic/versions/011_recent_activity.py`; `api/app/db.py`; `tests/test_activity.py` | `record_activity`, `connection`, `ActivityIntegrationTests` | A | Generic Operator attribution; no immutable audit storage. |
| Readiness and sync failure state | `ai/app/main.py`; `ai/app/indexer.py`; `tests/test_ai_classifier.py` | `health`, `index_status`; `test_failed_initial_index_sync_degrades_health_and_is_reported` | A | Stored index validity is not source freshness. |
| Operational request timing | `api/app/main.py` | `request_log` | B | Logs individual durations; no published percentile benchmark. |
| Deterministic showcase fixture | `docker/demo/seed_showcase.py`; `tests/test_showcase_seed.py` | `EXPECTED`, `seed_showcase`, `inspect_showcase` | A | Small fixture, not a scored LLM golden set. |
| Live smoke and constraint diagnostics | `docker/tests/smoke.py`; `docker/tests/check_constraints.py` | `run_read_checks`, `run_write_check`, `count_violations` | B | Smoke health does not score actual model answers. |
| Historical successful test/deployment checks | `tests/VERIFICATION.md` | Clean-install, upgrade/recovery and test-image record | C | Reported 17 October results; no rerun or raw logs here. |
| No training/anomaly evaluation implementation found | `ai/app/`; `ai/requirements.txt`; `tests/test_ai_classifier.py` | Inspected inference/index/retrieval modules and tests | B | Scoped absence finding; does not assert anything about work outside this repository. |

## Claims Safe to Use on a Resume

Candidate achievements for human review. Use personal-action wording only after confirming actual contribution; these statements describe repository capabilities, not inferred sole authorship.

- Integrated local pretrained LLM and embedding inference into a Python dashboard with structured action planning and record-grounded responses.
- Implemented PostgreSQL hybrid full-text/vector retrieval with metadata filters, reciprocal rank fusion, and hash/version-based embedding synchronization.
- Built an operator-approved action workflow with allowlisted operations, ordered references, transactional execution, and before/after mutation audits.
- Developed deterministic and PostgreSQL integration tests for schema boundaries, ambiguous entity resolution, rollback, index lifecycle, and backup integrity.
- Containerized separate API and AI services with runtime database roles, persistent credential setup, readiness checks, and deployment verification tooling.
