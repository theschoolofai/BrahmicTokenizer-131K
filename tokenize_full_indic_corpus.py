#!/usr/bin/env python3
"""
Tokenize every Indic row in indic_tokenizer_samples_by_size/ with both
HYBRID and Sarvam-m. Aggregate token counts per (source, language).

Strategy for M1 / 64 GB:
  - Read parquet files one at a time with pyarrow.
  - Filter to non-English rows at the Arrow level.
  - Tokenize via the native Rust `tokenizers` library for BOTH tokenizers
    (Sarvam-m loaded from its local HF cache JSON — bypasses Python wrapper).
  - `encode_batch` releases GIL and uses all cores via Rayon → no need for
    multiprocessing on top (would just over-subscribe).
  - Chunk encode in batches of 50K to keep peak memory bounded.
  - Stream a CSV row per (source, lang) finished, so progress is visible
    and resumable.

Excludes: source=erav4_lang_* (per user instruction).
"""

import csv
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq
import pyarrow.compute as pc
import pyarrow as pa
from tokenizers import Tokenizer

BASE = Path("./indic_corpus")
OUT = Path("./reference_outputs")
PROGRESS_CSV = OUT / "tokenize_full_indic_progress.csv"
FINAL_CSV = OUT / "tokenize_full_indic_results.csv"

HYBRID = "./tokenizer.json"
SARVAMM = "sarvamai/sarvam-m"

EXCLUDE_SOURCES = {"erav4_lang_as", "erav4_lang_hi", "erav4_lang_kn",
                   "erav4_lang_mr", "erav4_lang_pa", "erav4_lang_te"}

# Languages we count. Anything else (en, empty, brx, etc.) is skipped.
INDIC = {"as", "bn", "gu", "hi", "kn", "ml", "mr", "or", "pa", "ta", "te"}

CHUNK = 50_000  # rows per encode_batch chunk


def load_tokenizers():
    print("Loading HYBRID...", flush=True)
    hyb = Tokenizer.from_file(HYBRID)
    print(f"  HYBRID vocab={hyb.get_vocab_size()}", flush=True)
    print("Loading Sarvam-m (native Rust, from local cache)...", flush=True)
    sm = Tokenizer.from_file(SARVAMM)
    print(f"  Sarvam-m vocab={sm.get_vocab_size()}", flush=True)
    return hyb, sm


def discover_files():
    """Return list of (source_name, parquet_path) tuples, excluded sources removed."""
    items = []
    for src_dir in sorted(os.listdir(BASE)):
        if not src_dir.startswith("source="):
            continue
        src = src_dir[len("source="):]
        if src in EXCLUDE_SOURCES:
            continue
        for f in sorted((BASE / src_dir).glob("*.parquet")):
            items.append((src, f))
    return items


def process_file(src, path, hyb, sm, lang_hint=None):
    """
    Tokenize one parquet file. Returns dict[(src, lang)] -> stats dict.

    `lang_hint`: if the source's language is implicit from the directory
    (e.g. sangraha_hi → 'hi'), we still read the per-row language column,
    but anything not in INDIC is dropped.
    """
    t0 = time.time()
    # Single-file read (avoids Hive-style dataset schema unification across files).
    pf = pq.ParquetFile(path)
    tbl = pf.read(columns=["text", "language"])
    # Filter at Arrow level: language ∈ INDIC
    langs_arr = tbl["language"]
    mask = pc.is_in(langs_arr, value_set=pa.array(sorted(INDIC)))
    tbl = tbl.filter(mask)
    n = len(tbl)
    if n == 0:
        return {}, time.time() - t0

    texts = tbl["text"].to_pylist()
    langs = tbl["language"].to_pylist()

    # Group row indices by language so we can encode each language's rows together.
    by_lang = defaultdict(list)
    for i, l in enumerate(langs):
        by_lang[l].append(i)

    out = {}
    for lang, idxs in by_lang.items():
        # Drop None or empty texts (some parquets have nulls).
        sub_texts = [texts[i] for i in idxs if texts[i]]
        n_rows = len(sub_texts)
        if n_rows == 0:
            continue

        # Word count (whitespace split).
        n_words = 0
        n_bytes = 0
        for t in sub_texts:
            n_words += len(t.split())
            n_bytes += len(t.encode("utf-8"))

        # Tokenize in chunks of CHUNK rows.
        hyb_tokens = 0
        sm_tokens = 0
        for start in range(0, n_rows, CHUNK):
            batch = sub_texts[start:start + CHUNK]
            hyb_tokens += sum(len(e.ids) for e in hyb.encode_batch(batch))
            sm_tokens += sum(len(e.ids) for e in sm.encode_batch(batch))

        out[(src, lang)] = {
            "rows": n_rows,
            "words": n_words,
            "bytes": n_bytes,
            "hybrid_tokens": hyb_tokens,
            "sarvam_m_tokens": sm_tokens,
        }

    return out, time.time() - t0


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files = discover_files()
    print(f"discovered {len(files)} parquet files across "
          f"{len({s for s, _ in files})} sources (erav4 excluded)", flush=True)
    total_parquet_bytes = sum(os.path.getsize(p) for _, p in files)
    print(f"total parquet bytes on disk: {total_parquet_bytes/1e9:.2f} GB", flush=True)

    hyb, sm = load_tokenizers()

    # Master aggregator: stats per (source, lang)
    agg = defaultdict(lambda: {"rows": 0, "words": 0, "bytes": 0,
                                "hybrid_tokens": 0, "sarvam_m_tokens": 0})

    # Streaming progress CSV — append a row each parquet finishes.
    with open(PROGRESS_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file_idx", "source", "path", "rows_indic", "elapsed_s",
                    "running_total_rows", "running_total_hyb_tok",
                    "running_total_sm_tok", "wall_clock_min"])

    t_start = time.time()
    total_rows_so_far = 0
    total_hyb = 0
    total_sm = 0

    for i, (src, path) in enumerate(files):
        per_file, dt = process_file(src, path, hyb, sm)
        file_rows = sum(s["rows"] for s in per_file.values())
        for k, v in per_file.items():
            a = agg[k]
            for kk, vv in v.items():
                a[kk] += vv
        total_rows_so_far += file_rows
        total_hyb += sum(s["hybrid_tokens"] for s in per_file.values())
        total_sm += sum(s["sarvam_m_tokens"] for s in per_file.values())
        wall_min = (time.time() - t_start) / 60
        print(f"[{i+1:>4}/{len(files)}]  {src:<28} {path.name[:40]:<40}  "
              f"rows={file_rows:>9,}  dt={dt:6.2f}s  "
              f"running_rows={total_rows_so_far:>11,}  "
              f"hyb={total_hyb:>12,}  sm={total_sm:>12,}  "
              f"wall={wall_min:6.1f}m",
              flush=True)
        with open(PROGRESS_CSV, "a", newline="") as f:
            w = csv.writer(f)
            w.writerow([i+1, src, str(path), file_rows, f"{dt:.2f}",
                        total_rows_so_far, total_hyb, total_sm,
                        f"{wall_min:.2f}"])

    # Final aggregated CSV: one row per (source, lang).
    with open(FINAL_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source", "language", "rows", "words", "bytes",
                    "hybrid_tokens", "sarvam_m_tokens",
                    "hybrid_tok_per_word", "sarvam_m_tok_per_word",
                    "hybrid_bytes_per_token", "sarvam_m_bytes_per_token",
                    "delta_sm_minus_hyb", "hybrid_savings_pct"])
        for (src, lang), s in sorted(agg.items()):
            wpw_h = s["hybrid_tokens"] / max(s["words"], 1)
            wpw_s = s["sarvam_m_tokens"] / max(s["words"], 1)
            bpt_h = s["bytes"] / max(s["hybrid_tokens"], 1)
            bpt_s = s["bytes"] / max(s["sarvam_m_tokens"], 1)
            delta = s["sarvam_m_tokens"] - s["hybrid_tokens"]
            savings = (s["sarvam_m_tokens"] - s["hybrid_tokens"]) / max(s["sarvam_m_tokens"], 1) * 100
            w.writerow([src, lang, s["rows"], s["words"], s["bytes"],
                        s["hybrid_tokens"], s["sarvam_m_tokens"],
                        f"{wpw_h:.4f}", f"{wpw_s:.4f}",
                        f"{bpt_h:.4f}", f"{bpt_s:.4f}",
                        delta, f"{savings:.2f}"])
    print(f"\nwrote {FINAL_CSV}", flush=True)
    print(f"total wall clock: {(time.time()-t_start)/60:.2f} min", flush=True)
    print(f"final totals — HYBRID: {total_hyb:,}  Sarvam-m: {total_sm:,}  "
          f"delta: {total_sm - total_hyb:+,}  "
          f"HYBRID savings: {(total_sm-total_hyb)/max(total_sm,1)*100:.2f}%",
          flush=True)


if __name__ == "__main__":
    main()
