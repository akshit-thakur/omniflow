import json
from typing import Any

from .db import connection
from .indexer import SOURCE_QUERIES
from .ollama import runtime
from .settings import get_settings


async def hybrid_search(
    query: str,
    *,
    limit: int | None = None,
    metadata_filter: dict[str, Any] | None = None,
    source_tables: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    settings = get_settings()
    bounded_limit = min(max(limit or settings.retrieval_limit, 1), 20)
    normalized_sources = list(dict.fromkeys(source_tables or SOURCE_QUERIES))
    unknown_sources = set(normalized_sources) - set(SOURCE_QUERIES)
    if unknown_sources:
        raise ValueError(
            "Unknown retrieval source table(s): " + ", ".join(sorted(unknown_sources))
        )
    vector = (await runtime.embeddings([query]))[0]
    filter_json = json.dumps(metadata_filter or {})
    async with connection() as conn:
        rows = await conn.fetch(
            """
            WITH eligible AS (
              SELECT * FROM ai_entity_embeddings
              WHERE embedding_model=$3 AND index_version=$4
                AND metadata @> $5::jsonb
                AND entity_table=ANY($6::text[])
            ),
            lexical AS (
              SELECT id,
                     row_number() OVER (
                       ORDER BY ts_rank_cd(search_document, websearch_to_tsquery('simple',$1)) DESC
                     ) AS rank
              FROM eligible
              WHERE search_document @@ websearch_to_tsquery('simple',$1)
              LIMIT 50
            ),
            semantic_candidates AS (
              SELECT id,embedding <=> $2::vector AS distance
              FROM eligible
              WHERE embedding IS NOT NULL
            ),
            semantic AS (
              SELECT id,row_number() OVER (ORDER BY distance) AS rank
              FROM semantic_candidates
              WHERE distance <= $7
              LIMIT 50
            ),
            fused AS (
              SELECT COALESCE(l.id,s.id) AS id,
                     COALESCE(1.0/(60+l.rank),0) + COALESCE(1.0/(60+s.rank),0) AS score
              FROM lexical l FULL OUTER JOIN semantic s ON s.id=l.id
            )
            SELECT e.entity_table,e.entity_id,e.content,e.metadata,
                   fused.score,e.updated_at
            FROM fused JOIN eligible e ON e.id=fused.id
            ORDER BY fused.score DESC
            LIMIT $8
            """,
            query,
            json.dumps(vector),
            settings.embedding_model,
            settings.index_version,
            filter_json,
            normalized_sources,
            settings.max_semantic_distance,
            bounded_limit,
        )
    return [
        {
            "source_table": row["entity_table"],
            "source_id": row["entity_id"],
            "text": row["content"],
            "metadata": (
                json.loads(row["metadata"], parse_float=str)
                if isinstance(row["metadata"], str)
                else row["metadata"]
            ),
            "score": float(row["score"]),
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]
