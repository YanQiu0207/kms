from __future__ import annotations

from pathlib import Path

import pytest

from app.vendors import flag_embedding


def test_core_modules_depend_on_vendor_layer_instead_of_direct_third_party_imports():
    targets = [
        Path("app/store/fts_store.py"),
        Path("app/store/vector_store.py"),
        Path("app/retrieve/semantic.py"),
        Path("app/retrieve/rerank.py"),
        Path("app/services/embeddings.py"),
    ]
    forbidden = (
        "import chromadb",
        "from chromadb",
        "import jieba",
        "from FlagEmbedding",
    )

    for path in targets:
        text = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in text, f"{path} should not directly import {marker}"


def test_vendor_layer_is_present():
    exports = Path("app/vendors/__init__.py").read_text(encoding="utf-8")

    assert "get_persistent_client" in exports
    assert "create_flag_auto_model" in exports
    assert "create_flag_reranker" in exports
    assert "cut_tokens" in exports


def test_flag_auto_model_fallback_wraps_non_typeerror(monkeypatch):
    class FakeAutoModel:
        @staticmethod
        def from_finetuned(model_name: str, **kwargs):
            if "devices" in kwargs:
                raise TypeError("legacy signature")
            raise RuntimeError("boom")

    monkeypatch.setattr(flag_embedding, "_load_flag_auto_model", lambda: FakeAutoModel)

    with pytest.raises(flag_embedding.VendorFlagEmbeddingError):
        flag_embedding.create_flag_auto_model("demo-model", device="cpu")


def test_flag_reranker_fallback_wraps_non_typeerror(monkeypatch):
    class FakeReranker:
        def __init__(self, model_name: str, **kwargs):
            if "devices" in kwargs:
                raise TypeError("legacy signature")
            raise RuntimeError("boom")

    monkeypatch.setattr(flag_embedding, "_load_flag_reranker", lambda: FakeReranker)

    with pytest.raises(flag_embedding.VendorFlagEmbeddingError):
        flag_embedding.create_flag_reranker("demo-model", device="cpu")


def test_flag_auto_model_prefers_local_cache_before_network(monkeypatch, tmp_path):
    calls: list[dict[str, object]] = []

    class FakeAutoModel:
        @staticmethod
        def from_finetuned(model_name: str, **kwargs):
            calls.append(kwargs)
            if kwargs.get("local_files_only"):
                raise RuntimeError("offline miss")
            return {"model_name": model_name, "kwargs": kwargs}

    monkeypatch.setattr(flag_embedding, "_load_flag_auto_model", lambda: FakeAutoModel)

    result = flag_embedding.create_flag_auto_model("demo-model", device="cuda", hf_cache=tmp_path)

    assert result["model_name"] == "demo-model"
    assert len(calls) == 2
    assert calls[0]["local_files_only"] is True
    assert calls[0]["cache_dir"] == str(tmp_path)
    assert calls[1]["cache_dir"] == str(tmp_path)


def test_flag_reranker_prefers_local_cache_before_network(monkeypatch, tmp_path):
    calls: list[dict[str, object]] = []

    class FakeReranker:
        def __init__(self, model_name: str, **kwargs):
            calls.append(kwargs)
            if kwargs.get("local_files_only"):
                raise RuntimeError("offline miss")
            self.model_name = model_name
            self.kwargs = kwargs

    monkeypatch.setattr(flag_embedding, "_load_flag_reranker", lambda: FakeReranker)

    result = flag_embedding.create_flag_reranker("demo-model", device="cuda", hf_cache=tmp_path)

    assert result.model_name == "demo-model"
    assert len(calls) == 2
    assert calls[0]["local_files_only"] is True
    assert calls[0]["cache_dir"] == str(tmp_path)
    assert calls[1]["cache_dir"] == str(tmp_path)


def test_flag_auto_model_uses_local_snapshot_path_when_cache_exists(monkeypatch, tmp_path):
    snapshot = tmp_path / "hub" / "models--BAAI--demo-model" / "snapshots" / "rev-1"
    snapshot.mkdir(parents=True)
    (tmp_path / "hub" / "models--BAAI--demo-model" / "refs").mkdir(parents=True)
    (tmp_path / "hub" / "models--BAAI--demo-model" / "refs" / "main").write_text("rev-1", encoding="utf-8")
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (snapshot / "tokenizer.json").write_text("{}", encoding="utf-8")

    seen: list[str] = []
    seen_kwargs: list[dict[str, object]] = []

    class FakeAutoModel:
        @staticmethod
        def from_finetuned(model_name: str, **kwargs):
            seen.append(model_name)
            seen_kwargs.append(kwargs)
            return {"model_name": model_name}

    monkeypatch.setattr(flag_embedding, "_load_flag_auto_model", lambda: FakeAutoModel)

    result = flag_embedding.create_flag_auto_model("BAAI/demo-model", hf_cache=tmp_path)

    assert result["model_name"] == str(snapshot)
    assert seen == [str(snapshot)]
    assert "model_class" not in seen_kwargs[0]


def test_flag_auto_model_sets_model_class_for_local_bge_m3_snapshot(monkeypatch, tmp_path):
    snapshot = tmp_path / "hub" / "models--BAAI--bge-m3" / "snapshots" / "rev-1"
    snapshot.mkdir(parents=True)
    (tmp_path / "hub" / "models--BAAI--bge-m3" / "refs").mkdir(parents=True)
    (tmp_path / "hub" / "models--BAAI--bge-m3" / "refs" / "main").write_text("rev-1", encoding="utf-8")
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (snapshot / "tokenizer.json").write_text("{}", encoding="utf-8")

    seen_kwargs: list[dict[str, object]] = []

    class FakeAutoModel:
        @staticmethod
        def from_finetuned(model_name: str, **kwargs):
            seen_kwargs.append(kwargs)
            return {"model_name": model_name}

    monkeypatch.setattr(flag_embedding, "_load_flag_auto_model", lambda: FakeAutoModel)

    result = flag_embedding.create_flag_auto_model("BAAI/bge-m3", hf_cache=tmp_path)

    assert result["model_name"] == str(snapshot)
    assert seen_kwargs[0]["model_class"] == "encoder-only-m3"
