#!/usr/bin/env python3
"""
evaluate_fertility_in22.py
==========================

Reproduces Table 5 of the BrahmicTokenizer-131K paper: per-word fertility on
AI4Bharat IN22-Gen (1024 aligned sentences × 22 languages), evaluated on the same
11-tokenizer set as Table 4. Used as the out-of-distribution corroboration that
the FLORES-200 rank ordering is robust to corpus variation.

Methodology: identical to evaluate_fertility_flores.py (whitespace word split,
add_special_tokens=False, corpus-level fertility = Σ tokens / Σ words). The Mean
column is the arithmetic mean over the 11 Brahmic target languages.

Usage
-----
    python evaluate_fertility_in22.py --tokenizers all --languages all

Data prerequisite
-----------------
IN22-Gen is gated on HuggingFace. Accept terms at
https://huggingface.co/datasets/ai4bharat/IN22-Gen, then:
    huggingface-cli login
    python -c "from datasets import load_dataset; load_dataset('ai4bharat/IN22-Gen')"
to prime the cache. The script reads the cached parquet directly.

Output
------
JSON results at --out (default ./evaluate_fertility_in22.json).
A reference output produced against the shipped tokenizer is committed at
reference_outputs/evaluate_fertility_in22.json.
"""
import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

LANGS = [
    ("eng_Latn", "En"), ("hin_Deva", "Hi"), ("ben_Beng", "Bn"), ("tam_Taml", "Ta"),
    ("tel_Telu", "Te"), ("kan_Knda", "Kn"), ("mal_Mlym", "Ml"), ("mar_Deva", "Mr"),
    ("guj_Gujr", "Gu"), ("pan_Guru", "Pa"), ("ory_Orya", "Or"), ("asm_Beng", "As"),
]

TOKENIZERS = [
    ("Sarvam-30B",            "hf",     "sarvamai/sarvam-30b"),
    ("Sarvam-1",              "hf",     "sarvamai/sarvam-1"),
    ("Gemma-3-1B",            "hf",     "google/gemma-3-1b-pt"),
    ("BrahmicTokenizer-131K", "local",  "./tokenizer.json"),
    ("GPT-OSS-120B",          "hf",     "openai/gpt-oss-120b"),
    ("Tekken/Sarvam-m",       "hf",     "mistralai/Mistral-Nemo-Base-2407"),
    ("Krutrim-1",             "hf",     "krutrim-ai-labs/Krutrim-1-instruct"),
    ("DeepSeek-R1",           "hf",     "deepseek-ai/DeepSeek-R1"),
    ("IndicBERTv2-SS",        "hf",     "ai4bharat/IndicBERTv2-SS"),
    ("Qwen3-8B",              "hf",     "Qwen/Qwen3-8B"),
    ("Llama-3.1-8B",          "hf",     "meta-llama/Llama-3.1-8B"),
]


def find_in22_parquet():
    candidates = sorted(glob.glob(
        os.path.expanduser('~/.cache/huggingface/hub/datasets--ai4bharat--IN22-Gen/snapshots/*/data/*.parquet')
    ))
    if not candidates:
        sys.exit("ERROR: ai4bharat/IN22-Gen not cached. See script docstring for setup.")
    return candidates[0]


def make_encoder(kind, src):
    if kind == "local":
        from tokenizers import Tokenizer
        t = Tokenizer.from_file(src)
        return lambda s: t.encode(s).ids
    from transformers import AutoTokenizer
    t = AutoTokenizer.from_pretrained(src, trust_remote_code=True)
    return lambda s: t.encode(s, add_special_tokens=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tokenizers", default="all")
    ap.add_argument("--languages", default="all")
    ap.add_argument("--in22-parquet", default=None,
                    help="path to IN22-Gen parquet (autodetect from HF cache if omitted)")
    ap.add_argument("--out", default="./evaluate_fertility_in22.json")
    args = ap.parse_args()

    if args.languages == "all":
        langs = LANGS
    else:
        wanted = {s.strip() for s in args.languages.split(",")}
        langs = [(c, l) for c, l in LANGS if l in wanted]
    if args.tokenizers == "all":
        tokenizers = TOKENIZERS
    else:
        wanted = {s.strip() for s in args.tokenizers.split(",")}
        tokenizers = [t for t in TOKENIZERS if t[0] in wanted]

    import pyarrow.parquet as pq
    parquet = args.in22_parquet or find_in22_parquet()
    print(f"Loading IN22-Gen from {parquet}", flush=True)
    df = pq.read_table(parquet).to_pandas()
    texts = {}
    for code, lbl in langs:
        if code in df.columns:
            texts[code] = [s for s in df[code].tolist() if isinstance(s, str) and s.strip()]
            print(f"  {lbl} ({code}): {len(texts[code])} sentences", flush=True)
        else:
            print(f"  {lbl} ({code}): MISSING in IN22 — skipped", flush=True)

    out = {}
    for name, kind, src in tokenizers:
        print(f"\n=== {name} ===", flush=True)
        t0 = time.time()
        try:
            enc = make_encoder(kind, src)
        except Exception as e:
            print(f"  LOAD FAIL: {e}", flush=True)
            continue
        per_lang = {}
        for code, lbl in langs:
            if code not in texts:
                continue
            tot_tok = sum(len(enc(line)) for line in texts[code])
            tot_w = sum(len(line.split()) for line in texts[code])
            fert = tot_tok / max(tot_w, 1)
            per_lang[lbl] = round(fert, 4)
            print(f"  {lbl:<3} fert={fert:.4f}", flush=True)
        brahmic = [per_lang[lbl] for _, lbl in langs if lbl != "En" and lbl in per_lang]
        if brahmic:
            per_lang["Mean"] = round(sum(brahmic) / len(brahmic), 4)
            print(f"  Mean(Brahmic) = {per_lang['Mean']}  ({time.time()-t0:.1f}s)", flush=True)
        out[name] = per_lang

    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
