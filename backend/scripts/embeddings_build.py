"""Builds the stored vectors for meaning-based search over the law provisions (lib/embeddings.py). Run it once after the provisions are loaded, and again whenever they change.

    python scripts/embeddings_build.py [--db vidhi_dev] [--out <folder>]

Needs EMBEDDINGS_MODEL_DIR (a folder with tokenizer.json, tokenizer_config.json and onnx/model.onnx of intfloat/multilingual-e5-small) and the packages onnxruntime, tokenizers and numpy.
Reads provisions from MongoDB, writes two files (vectors and a manifest) to EMBEDDINGS_DIR, nothing to the database, and calls no network service. Takes about two minutes for 2,331 provisions on a laptop CPU.
After a rebuild, restart the backend (or it keeps what it loaded); until the vectors match the provisions, meaning-based search stays off and keyword search is unchanged."""

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymongo import MongoClient  # noqa: E402

from lib import embeddings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("DB_NAME", "vidhi_dev"))
    ap.add_argument("--mongo-url", default=os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    d = embeddings.model_dir()
    if d is None or not (d / "onnx" / "model.onnx").exists():
        print("EMBEDDINGS_MODEL_DIR must point at the model folder (it needs onnx/model.onnx and tokenizer.json).")
        return 2
    db = MongoClient(a.mongo_url)[a.db]
    acts = {i["id"]: (i.get("short_names") or ["?"])[0] for i in db.instruments.find({}, {"id": 1, "short_names": 1})}
    provisions = list(db.provisions.find({}, {"_id": 0, "id": 1, "number": 1, "heading": 1, "text_full": 1, "instrument_id": 1, "content_sha256": 1}))
    if not any(len(p.get("text_full") or "") > 50 for p in provisions):
        print("The provisions hold no text_full: nothing to embed (refusing to embed headings only).")
        return 1
    t = time.time()
    out = embeddings.build_store(provisions, acts, Path(a.out) if a.out else None)
    print(f"embedded {out['provisions']} provisions in {time.time() - t:.0f} s; fingerprint {out['fingerprint']}; written to {out['dir']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
