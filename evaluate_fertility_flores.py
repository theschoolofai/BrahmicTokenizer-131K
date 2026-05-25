#!/usr/bin/env python3
"""
evaluate_fertility_flores.py
============================

Reproduces Table 4 of the BrahmicTokenizer-131K paper: per-word fertility on
FLORES-200 dev+devtest, for 11 publicly downloadable tokenizers, on the 11 target
Brahmic languages plus English. Lower fertility = better compression.

Methodology (matches the paper):
  - Corpus: FLORES-200 dev (997 sents/lang) + devtest (1012 sents/lang) = 2009 sents/lang.
  - Word count: whitespace split (`line.split()`), same as MUTANT's tokenizer_evaluator.
  - Token count: `tokenizer.encode(line, add_special_tokens=False)`, corpus-level sum.
  - Fertility: Σ tokens / Σ words across all 2009 sentences per language.
  - Mean column: arithmetic mean over the 11 Brahmic languages (excludes English).

Usage
-----
    # Run all 11 tokenizers on all 12 languages (default — matches paper Appendix D):
    python evaluate_fertility_flores.py --tokenizers all --languages all

    # Subset:
    python evaluate_fertility_flores.py --tokenizers BrahmicTokenizer-131K,Tekken/Sarvam-m --languages Hi,Or

Data prerequisite
-----------------
FLORES-200 dev and devtest folders under --flores-dir (default /tmp/flores200_dataset).
Download from canonical source (one-liner):
    curl -sL -o /tmp/flores200_dataset.tar.gz \
      https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz
    tar -xzf /tmp/flores200_dataset.tar.gz -C /tmp/

The 11 tokenizer comparators are downloaded from their HuggingFace canonical
sources on first run (some require accepting model terms / gated access on
HuggingFace — Llama-3.1-8B, Sarvam-30B, DeepSeek-R1).

Output
------
JSON results at --out (default ./evaluate_fertility_flores.json).
A reference output produced against the shipped tokenizer is committed to the
repo at reference_outputs/evaluate_fertility_flores.json for comparison.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Paper Table 4 row order: English first, then 11 Brahmic targets.
LANGS = [
    ("eng_Latn", "En"), ("hin_Deva", "Hi"), ("ben_Beng", "Bn"), ("tam_Taml", "Ta"),
    ("tel_Telu", "Te"), ("kan_Knda", "Kn"), ("mal_Mlym", "Ml"), ("mar_Deva", "Mr"),
    ("guj_Gujr", "Gu"), ("pan_Guru", "Pa"), ("ory_Orya", "Or"), ("asm_Beng", "As"),
]

# Paper Table 4 tokenizer set. Display order = rank order printed in the paper.
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


def make_encoder(kind, src):
    if kind == "local":
        from tokenizers import Tokenizer
        t = Tokenizer.from_file(src)
        return lambda s: t.encode(s).ids
    if kind == "hf":
        from transformers import AutoTokenizer
        t = AutoTokenizer.from_pretrained(src, trust_remote_code=True)
        return lambda s: t.encode(s, add_special_tokens=False)
    raise ValueError(kind)


def load_texts(flores_dir, langs):
    dev = Path(flores_dir) / "dev"
    devtest = Path(flores_dir) / "devtest"
    if not dev.is_dir() or not devtest.is_dir():
        sys.exit(f"ERROR: {flores_dir}/dev and {flores_dir}/devtest must exist.\n"
                 f"Download FLORES-200 first — see script docstring.")
    texts = {}
    for code, lbl in langs:
        dev_lines = (dev / f"{code}.dev").read_text(encoding="utf-8").splitlines()
        devt_lines = (devtest / f"{code}.devtest").read_text(encoding="utf-8").splitlines()
        texts[code] = [l for l in dev_lines + devt_lines if l.strip()]
    return texts


def parse_csv(arg, all_options, label):
    if arg == "all":
        return all_options
    wanted = [s.strip() for s in arg.split(",") if s.strip()]
    avail = {o if isinstance(o, str) else o[0] for o in all_options}
    bad = [w for w in wanted if w not in avail]
    if bad:
        sys.exit(f"ERROR: unknown {label}: {bad}. Available: {sorted(avail)}")
    if isinstance(all_options[0], tuple):
        keep = set(wanted)
        return [o for o in all_options if o[0] in keep]
    return [o for o in all_options if o in keep]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tokenizers", default="all",
                    help='"all" (default) or comma list, e.g. "BrahmicTokenizer-131K,Tekken/Sarvam-m"')
    ap.add_argument("--languages", default="all",
                    help='"all" (default, 12 langs) or comma list of paper labels, e.g. "Hi,Or,En"')
    ap.add_argument("--flores-dir", default="/tmp/flores200_dataset",
                    help="root of FLORES-200 release (must contain dev/ and devtest/)")
    ap.add_argument("--out", default="./evaluate_fertility_flores.json",
                    help="output JSON path")
    args = ap.parse_args()

    # Language filter — keep paper row order even when subsetting
    if args.languages == "all":
        langs = LANGS
    else:
        wanted = {s.strip() for s in args.languages.split(",")}
        langs = [(c, l) for c, l in LANGS if l in wanted]
        if not langs:
            sys.exit(f"ERROR: no matching languages. Available labels: {[l for _, l in LANGS]}")

    # Tokenizer filter — keep paper rank order
    if args.tokenizers == "all":
        tokenizers = TOKENIZERS
    else:
        wanted = {s.strip() for s in args.tokenizers.split(",")}
        tokenizers = [t for t in TOKENIZERS if t[0] in wanted]
        if not tokenizers:
            sys.exit(f"ERROR: no matching tokenizers. Available: {[t[0] for t in TOKENIZERS]}")

    print(f"Loading FLORES dev+devtest from {args.flores_dir}...", flush=True)
    texts = load_texts(args.flores_dir, langs)
    for code, lbl in langs:
        print(f"  {lbl} ({code}): {len(texts[code])} sentences", flush=True)

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
            tot_tok = sum(len(enc(line)) for line in texts[code])
            tot_w = sum(len(line.split()) for line in texts[code])
            fert = tot_tok / max(tot_w, 1)
            per_lang[lbl] = round(fert, 4)
            print(f"  {lbl:<3} fert={fert:.4f}  tok={tot_tok}  w={tot_w}", flush=True)
        brahmic = [per_lang[lbl] for _, lbl in langs if lbl != "En" and lbl in per_lang]
        if brahmic:
            per_lang["Mean"] = round(sum(brahmic) / len(brahmic), 4)
            print(f"  Mean(Brahmic) = {per_lang['Mean']}  ({time.time()-t0:.1f}s)", flush=True)
        out[name] = per_lang

    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
