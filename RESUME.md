# OmniFlow — Resume Claim Explanations

**Python | FastAPI | PostgreSQL | pgvector | bge-m3 | Qwen3 | Ollama**

This document explains the implementation behind the three resume claims, with examples and details useful for interview discussion. [WALKTHROUGH.md](WALKTHROUGH.md) covers the broader architecture.

## 1. Two-stage LLM pipeline for intent classification and action planning

OmniFlow turns a natural-language request into either a read response, ordinary conversation, or a proposed set of database changes. The AI service calls a locally served Qwen3 model through Ollama. The model is configurable: Docker Compose defaults to `qwen3:4b`, while the application settings fallback is `qwen3:8b`.

The first model call classifies the current user message as `read`, `write`, or `chat`. Ollama receives the JSON Schema generated from the Pydantic `IntentResponse` model, and the returned JSON is validated again in Python. This call receives neither retrieved records nor conversation history, so stored record text cannot directly supply instructions to the intent classifier.

Only a `write` classification triggers the second model call. This call produces an ordered list of allowlisted actions, each containing an action name and an arguments object. For example, a request to complete a task can produce a `task.complete` action. The planner receives the current message and trusted numeric entity references, rather than raw retrieved record text. `ClassifierActionPlan` validates the output structure, restricts action names, and caps a plan at 20 actions. An empty plan becomes a chat result instead of an executable write.

“Schema-validated” has two layers here: model output must match the intent/plan schema, and the execution backend later validates each action's actual arguments against domain rules. A structurally valid plan is still a proposal; it does not establish that every argument is valid or that the requested change is correct.

This separation keeps the decision to mutate data distinct from constructing the mutation plan. Read and chat requests skip the planning call. Retrieval can occur before classification in the request lifecycle, but its raw text is excluded from both intent classification and write planning.

**Code references:** [ModelRuntime.classify and Pydantic schemas](ai/app/ollama.py), [request orchestration](ai/app/main.py), [model settings](ai/app/settings.py), [Compose configuration](compose.yaml).

## 2. Hybrid retrieval with semantic search, full-text search, and RRF

The application maintains a searchable projection of dashboard records in PostgreSQL. The indexer converts records into text and metadata, embeds their text with `bge-m3` through Ollama, and stores the 1024-dimensional vectors in pgvector. Content hashes let indexing skip unchanged records; obsolete entries are removed during reindexing.

For a user query, `hybrid_search` generates a query embedding and searches eligible records through two branches. Source-table and metadata filters, along with embedding-model and index-version checks, constrain the records searched.

- **Semantic search:** pgvector's `<=>` operator calculates cosine distance between the query embedding and stored vectors. Smaller distance means greater similarity. Candidates beyond the configured distance cutoff are excluded, and the remaining records receive ranks by distance. This helps retrieve related wording even when the query and record do not share exact terms.
- **Lexical search:** PostgreSQL matches the stored `search_document` against `websearch_to_tsquery('simple', query)` and ranks matches using `ts_rank_cd`. This captures explicit words and names that are useful alongside semantic matches.

The branches contribute up to 50 candidates each. Reciprocal-rank fusion combines their rankings using:

```text
RRF score = 1 / (60 + lexical rank) + 1 / (60 + semantic rank)
```

A missing branch contributes zero. A record ranked first in both branches scores `2 / 61`, while one ranked first in only one branch scores `1 / 61`. The combined results are sorted by this score and limited to the requested result count, which defaults to eight.

RRF combines rank positions because lexical relevance scores and cosine distances have different scales. It rewards records supported by both search methods while retaining records found by only one. The fused score is a ranking signal, not a probability that a result is correct.

For example, a query such as “leg training” could benefit from semantic matches to differently worded exercise records, while an exact exercise name benefits from lexical matching. This illustrates the intended benefit; it is not a measured retrieval-quality result. Retrieval also depends on embedding availability: because query embedding happens before the SQL search, the current implementation does not provide a lexical-only fallback if embedding fails.

**Code references:** [hybrid search and fusion SQL](ai/app/retrieval.py), [index maintenance](ai/app/indexer.py), [embedding configuration](ai/app/settings.py), [search columns and indexes](database/init.sql).

## 3. Approval-gated execution, dependency resolution, and rollback

The model does not directly execute its action plan. The AI service submits it to the API, which stores a pending proposal and a review representation with a digest. The frontend presents the proposal for an explicit approve or reject decision.

On approval, the API locks the proposal row, checks that its status is still pending, verifies the submitted review digest, and rebuilds the review to detect changed targets. The pending-state check and row lock prevent the same proposal from being committed twice through repeated approvals. The review check detects changes represented in the review; it is not a snapshot of all database state.

The backend executes approved actions in their listed order. Before each action, it resolves references, checks entity selectors, and validates arguments. Exact-name lookups reject ambiguous matches, referenced IDs must exist, and unsupported arguments are rejected. The final mutation uses backend-owned parameterized SQL.

Dependency resolution allows a later action to use a value produced by an earlier action. For example, a composite request can create an ingredient and then use its new ID when adding it to a recipe. A reference such as `$ref:actions.0.entity_id` is replaced with the entity ID returned by the first action. References can also access trusted execution context. This is ordered reference resolution: the planner must put dependencies first; the executor does not rearrange an arbitrary dependency graph.

All actions run inside one PostgreSQL transaction. Each action's audit entry, including its arguments and before/after state, is written in that same transaction, and the proposal is marked committed only after the batch succeeds.

If a later action fails validation or a database operation fails, the transaction rolls back earlier mutations, audit inserts, and the proposal's committed-status update. For example, if ingredient creation succeeds but the following recipe action fails, the newly created ingredient is rolled back too. The proposal remains pending. “Automatic rollback” therefore means database transaction rollback, not a second model call generating compensating actions. Failed batches do not leave committed mutation-audit rows.

The practical benefit is that a composite request either commits as one unit or leaves no partial domain changes. Human approval controls whether execution begins, while backend validation and transactions control how it is applied.

**Code references:** [proposal approval and batch execution](api/app/routers/ai.py), [reference resolution and mutation validation](api/app/mutations.py), [proposal schemas](api/app/schemas.py), [frontend review controls](frontend/src/components/ChatBubble.tsx).
