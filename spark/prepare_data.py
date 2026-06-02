"""Convert the raw Zenodo ``public_v2.json`` dump into newline-delimited JSON.

The Zenodo "Web robot detection" export is a single, multi-gigabyte JSON
*object* (``{"<id>": {..record..}, ...}``) with exactly one record per
physical line.  Spark cannot split a single giant JSON object, so we stream
the file line-by-line and emit one flat NDJSON record per line containing
only the fields the ETL needs:

    ip, timestamp, useragent, path, method, status_code, bytes_sent

Running this is optional: ``etl.py`` already reads NDJSON directly, and the
repo ships a small ``sample_logs.json`` for smoke tests.  Use this script to
turn the full 3.2 GB dump into something Spark can parallelise.

Usage:
    python spark/prepare_data.py --input data/raw/public_v2.json \\
                                 --output data/raw/logs.ndjson
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterator, Optional

# Map of raw Zenodo field names -> canonical ETL field names.
_FIELD_MAP = {
    "ip": "ip",
    "timestamp": "timestamp",
    "useragent": "useragent",
    "resource": "path",
    "method": "method",
    "response": "status_code",
    "bytes": "bytes_sent",
}


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _normalise(record: dict[str, Any]) -> dict[str, Any]:
    """Project a raw Zenodo record onto the canonical ETL schema."""
    out: dict[str, Any] = {}
    for raw_key, canon_key in _FIELD_MAP.items():
        out[canon_key] = record.get(raw_key)
    out["status_code"] = _to_int(out.get("status_code"))
    out["bytes_sent"] = _to_int(out.get("bytes_sent"))
    return out


def iter_records(input_path: Path) -> Iterator[dict[str, Any]]:
    """Yield raw record dicts from the giant single-object JSON file.

    Relies on the dump's one-record-per-line layout.  Falls back to ``ijson``
    (streaming parser) when a line cannot be parsed standalone.
    """
    input_path = Path(input_path)
    with input_path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line in ("{", "}"):
                continue
            line = line.rstrip(",")
            brace = line.find("{")
            if brace == -1:
                continue
            try:
                yield json.loads(line[brace:])
            except json.JSONDecodeError:
                continue


def _iter_records_ijson(input_path: Path) -> Iterator[dict[str, Any]]:
    """Robust streaming fallback using ijson (handles pretty-printed dumps)."""
    import ijson  # type: ignore

    with input_path.open("rb") as fh:
        for _key, record in ijson.kvitems(fh, ""):
            yield record


def convert(input_path: Path, output_path: Path, use_ijson: bool = False) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    source = _iter_records_ijson(input_path) if use_ijson else iter_records(input_path)
    written = 0
    with output_path.open("w", encoding="utf-8") as out:
        for record in source:
            if not isinstance(record, dict):
                continue
            out.write(json.dumps(_normalise(record), ensure_ascii=False))
            out.write("\n")
            written += 1
            if written % 500_000 == 0:
                print(f"  ... {written:,} records", file=sys.stderr)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--ijson",
        action="store_true",
        help="Use the ijson streaming fallback (slower, handles any layout).",
    )
    args = parser.parse_args()

    print(f"Converting {args.input} -> {args.output}", file=sys.stderr)
    n = convert(args.input, args.output, use_ijson=args.ijson)
    print(f"Done. Wrote {n:,} NDJSON records to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
