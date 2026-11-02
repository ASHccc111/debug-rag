"""Create lazy runtime components without loading a model or calling any network."""

from debug_rag.budget import BudgetLedger
from debug_rag.generation.provider import DeepSeekGenerator
from debug_rag.retrieval.embedding import LocalEmbedder
from debug_rag.retrieval.indexing import IndexBuilder
from debug_rag.retrieval.remote_embedding import VikingEmbedder
from debug_rag.retrieval.rerank import BailianReranker
from debug_rag.retrieval.rewrite import QueryRewriter
from debug_rag.retrieval.service import RagService
from debug_rag.storage.milvus import MilvusVectors


def components(settings, engine):
    vectors = MilvusVectors(settings)
    ledger = BudgetLedger(engine, settings.monthly_budget_cny)
    embedder = (
        VikingEmbedder(settings, ledger)
        if settings.embedding_backend == "viking"
        else LocalEmbedder(settings.embedding_model_path)
    )
    generator = DeepSeekGenerator(settings, ledger)
    return (
        IndexBuilder(settings, engine, embedder, vectors),
        RagService(
            settings,
            engine,
            embedder,
            vectors,
            generator,
            rewriter=QueryRewriter(generator),
            reranker=BailianReranker(settings, ledger),
        ),
        ledger,
    )
