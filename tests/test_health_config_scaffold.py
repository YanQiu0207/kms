from __future__ import annotations

from pydantic import ValidationError
import pytest

from app.config import ChunkerConfig, RetrievalConfig


def test_config_module_is_importable():
    config = pytest.importorskip("app.config")
    assert config.__name__ == "app.config"


def test_main_module_is_importable_without_executing_entrypoint():
    main = pytest.importorskip("app.main")
    assert main.__name__ == "app.main"
    assert callable(main.create_app)
    assert not hasattr(main, "app")


def test_health_boundary_package_present():
    module = pytest.importorskip("app")
    assert module.__name__ == "app"


def test_chunker_config_rejects_invalid_overlap():
    with pytest.raises(ValidationError):
        ChunkerConfig(chunk_size=100, chunk_overlap=100)


def test_retrieval_config_rejects_invalid_ranking_pipeline_order():
    with pytest.raises(ValidationError):
        RetrievalConfig(
            ranking_pipeline=[
                "rerank",
                "limit_rerank_candidates",
                "top_k_limit",
            ]
        )


def test_retrieval_config_rejects_non_positive_query_type_fusion_weight():
    with pytest.raises(ValidationError):
        RetrievalConfig(
            query_type_fusion_weights={
                "lookup": {
                    "lexical": 0.0,
                    "semantic": 1.0,
                }
            }
        )
