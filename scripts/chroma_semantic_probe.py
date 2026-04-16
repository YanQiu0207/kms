from __future__ import annotations

import argparse
import faulthandler
import json
from pathlib import Path
import shutil
import sys
from typing import Sequence

from app.vendors import clear_persistent_client_cache, get_persistent_client


def _collection(persist_directory: Path, collection_name: str):
    client = get_persistent_client(str(persist_directory))
    return client.get_or_create_collection(name=collection_name)


def _metadata_profile(metadata: dict[str, object] | None, *, mode: str) -> dict[str, object]:
    raw = dict(metadata or {})
    if mode == "full":
        return raw
    if mode != "minimal":
        raise ValueError(f"unsupported metadata mode: {mode}")

    keep = (
        "chunk_id",
        "document_id",
        "file_path",
        "title_path",
        "title_path_json",
        "start_line",
        "end_line",
        "section_index",
        "chunk_index",
        "file_hash",
    )
    return {key: raw[key] for key in keep if key in raw and raw[key] is not None}


def _as_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        converted = tolist()
        if isinstance(converted, list):
            return converted
        if isinstance(converted, tuple):
            return list(converted)
        return [converted]
    return list(value)


def inspect_collection(persist_directory: Path, collection_name: str) -> int:
    collection = _collection(persist_directory, collection_name)
    payload = collection.get(include=["metadatas"])
    metadatas = payload.get("metadatas") or []

    sizes: list[int] = []
    key_counts: dict[str, int] = {}
    for metadata in metadatas:
        encoded = json.dumps(metadata or {}, ensure_ascii=False)
        sizes.append(len(encoded))
        for key in (metadata or {}).keys():
            key_counts[key] = key_counts.get(key, 0) + 1
    sizes.sort()
    report = {
        "persist_directory": str(persist_directory),
        "collection_name": collection_name,
        "record_count": len(metadatas),
        "metadata_size_avg": round(sum(sizes) / len(sizes), 2) if sizes else 0,
        "metadata_size_p95": sizes[int(len(sizes) * 0.95)] if sizes else 0,
        "metadata_size_max": sizes[-1] if sizes else 0,
        "metadata_keys": key_counts,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def clone_collection(
    source_directory: Path,
    target_directory: Path,
    *,
    collection_name: str,
    metadata_mode: str,
    replace: bool,
) -> int:
    if target_directory.exists():
        if not replace:
            raise SystemExit(f"target already exists: {target_directory}")
        resolved = target_directory.resolve()
        workspace_root = Path.cwd().resolve()
        if workspace_root not in resolved.parents and resolved != workspace_root:
            raise SystemExit(f"refuse to delete non-workspace target: {resolved}")
        shutil.rmtree(target_directory)

    source = _collection(source_directory, collection_name)
    payload = source.get(include=["documents", "metadatas", "embeddings"])

    ids = _as_list(payload.get("ids"))
    documents = _as_list(payload.get("documents"))
    metadatas = _as_list(payload.get("metadatas"))
    embeddings = _as_list(payload.get("embeddings"))

    target_directory.mkdir(parents=True, exist_ok=True)
    clear_persistent_client_cache()
    target = _collection(target_directory, collection_name)
    batch_size = 512
    for start in range(0, len(ids), batch_size):
        end = start + batch_size
        target.upsert(
            ids=ids[start:end],
            documents=documents[start:end],
            embeddings=embeddings[start:end],
            metadatas=[
                _metadata_profile(metadata, mode=metadata_mode)
                for metadata in metadatas[start:end]
            ],
        )

    report = {
        "source_directory": str(source_directory),
        "target_directory": str(target_directory),
        "collection_name": collection_name,
        "record_count": len(ids),
        "metadata_mode": metadata_mode,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def query_collection(
    persist_directory: Path,
    *,
    collection_name: str,
    queries: Sequence[str],
    limit: int,
) -> int:
    faulthandler.enable(all_threads=True)
    collection = _collection(persist_directory, collection_name)

    query_vectors = None
    # Use Chroma-side embedding function stored in collection metadata/state if available.
    if query_vectors is None:
        from app.config import load_config
        from app.retrieve.semantic import build_embedding_encoder

        config = load_config("config.notes-frontmatter.yaml")
        encoder = build_embedding_encoder(
            config.models.embedding,
            device=config.models.device,
            dtype=config.models.dtype,
            batch_size=config.models.embedding_batch_size,
            hf_cache=config.data.hf_cache,
        )
        try:
            query_vectors = encoder.embed_texts(tuple(queries))
        finally:
            encoder.close()

    result = collection.query(
        query_embeddings=query_vectors,
        n_results=limit,
        include=["documents", "metadatas", "distances"],
    )
    summary = {
        "persist_directory": str(persist_directory),
        "collection_name": collection_name,
        "query_count": len(tuple(queries)),
        "limit": limit,
        "result_lengths": [len(items) for items in (result.get("ids") or [])],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe Chroma semantic crash on notes-frontmatter collections.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--persist-directory", required=True)
    inspect_parser.add_argument("--collection-name", default="chunks")

    clone_parser = subparsers.add_parser("clone")
    clone_parser.add_argument("--source-directory", required=True)
    clone_parser.add_argument("--target-directory", required=True)
    clone_parser.add_argument("--collection-name", default="chunks")
    clone_parser.add_argument("--metadata-mode", choices=("full", "minimal"), required=True)
    clone_parser.add_argument("--replace", action="store_true")

    query_parser = subparsers.add_parser("query")
    query_parser.add_argument("--persist-directory", required=True)
    query_parser.add_argument("--collection-name", default="chunks")
    query_parser.add_argument("--query", action="append", dest="queries", required=True)
    query_parser.add_argument("--limit", type=int, default=5)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "inspect":
        return inspect_collection(Path(args.persist_directory), args.collection_name)
    if args.command == "clone":
        return clone_collection(
            Path(args.source_directory),
            Path(args.target_directory),
            collection_name=args.collection_name,
            metadata_mode=args.metadata_mode,
            replace=bool(args.replace),
        )
    if args.command == "query":
        return query_collection(
            Path(args.persist_directory),
            collection_name=args.collection_name,
            queries=tuple(args.queries),
            limit=args.limit,
        )
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
