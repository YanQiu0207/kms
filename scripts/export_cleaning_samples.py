from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import load_config
from app.ingest import MarkdownIngestLoader, SourceSpec


def main() -> int:
    parser = argparse.ArgumentParser(description="Export cleaned document samples for M14 review.")
    parser.add_argument("--config", default="config.yaml", help="Config file path.")
    parser.add_argument("--output", required=True, help="Output JSON path.")
    parser.add_argument("--path", action="append", dest="paths", required=True, help="Markdown file path to inspect.")
    parser.add_argument("--chunk-preview-limit", type=int, default=3, help="Chunk preview count per document.")
    parser.add_argument("--text-preview-limit", type=int, default=800, help="Preview char limit for raw/cleaned text.")
    args = parser.parse_args()

    config = load_config(args.config)
    payload: list[dict[str, object]] = []
    for raw_path in args.paths:
        path = Path(raw_path).expanduser()
        loader = MarkdownIngestLoader(
            (SourceSpec(path=str(path), excludes=tuple()),),
            chunk_size=config.chunker.chunk_size,
            chunk_overlap=config.chunker.chunk_overlap,
            chunker_version=config.chunker.version,
            embedding_model=config.models.embedding,
            cleaning=config.cleaning,
        )
        document = next(loader.iter_documents())
        chunks = loader.iter_chunks(document)
        raw_text = path.read_text(encoding="utf-8", errors="replace")
        payload.append(
            {
                "file_path": str(path.resolve(strict=False)).replace("\\", "/"),
                "relative_path": document.relative_path,
                "cleaning": document.metadata.get("cleaning") or {},
                "raw_preview": raw_text[: args.text_preview_limit],
                "cleaned_preview": document.text[: args.text_preview_limit],
                "chunks": [
                    {
                        "chunk_id": chunk.chunk_id,
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                        "preview": chunk.text[: args.text_preview_limit],
                    }
                    for chunk in chunks[: args.chunk_preview_limit]
                ],
            }
        )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
