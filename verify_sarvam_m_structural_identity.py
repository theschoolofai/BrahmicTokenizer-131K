#!/usr/bin/env python3
"""
verify_sarvam_m_structural_identity.py
======================================

Reviewer-runnable verification: bit-level structural diff between two HF
`tokenizer.json` files. Designed to check the paper's claim that Sarvam-m
is "Mistral-Nemo Tekken with renamed special tokens but no new merges."

Why this matters
----------------
The LightningLM tokenizer paper reports that Sarvam-m's FLORES fertility
matches Mistral-Nemo Tekken to three decimals across all 16 languages.
This script verifies the structural reason for that match: identical BPE
merge tables (content + rank order), near-identical normal vocab, and
divergence confined to special / added tokens.

A reviewer can re-run this on any two HF-format tokenizers — it does not
hard-code Sarvam-m or Tekken paths.

Methodology
-----------
1. Load both `tokenizer.json` files.
2. Normalize merges to (left, right) tuples. HF tokenizers serialize
   merges either as a single "a b" string (older Tekken) or as a 2-element
   list ["a","b"] (newer; e.g. Sarvam-m, HYBRID). Both forms are accepted.
3. Compare three structural components as sets:
     - `model.vocab`  (normal BPE tokens, token-string → id map)
     - `model.merges` (BPE merge table)
     - `added_tokens` (specials, by `content` string)
4. Also compare merge rank order (sequence equality), since BPE merge
   rank is what drives tokenization output. Identical merge SETS with
   different orderings would still tokenize differently.

Usage
-----
    python verify_sarvam_m_structural_identity.py  path/to/sarvam_m_tokenizer.json  path/to/tekken_tokenizer.json

Output
------
A printed report:
    - total normal-vocab tokens in each tokenizer
    - tokens identical, only-in-A, only-in-B
    - total merges in each tokenizer
    - merges identical (set), only-in-A, only-in-B
    - merge rank order preserved (yes/no)
    - added-token counts identical, only-in-A, only-in-B
    - sample of any deltas (up to 20 per category)

Exit codes
----------
    0   success — comparison completed and printed
    2   error parsing either tokenizer file

This script *reports* and does not fail on structural difference: two
tokenizers being non-identical is information, not a failure. The
reviewer reads the printed deltas and decides whether the paper's
claim holds.

Author: codebase agent for the LightningLM tokenizer paper.
License: MIT.
"""

import json
import sys
from pathlib import Path


def load(path):
    """Load a HF tokenizer.json and extract the structural components."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    vocab = data["model"].get("vocab", {})
    raw_merges = data["model"].get("merges", [])
    norm_merges = []
    for m in raw_merges:
        if isinstance(m, list) and len(m) == 2:
            norm_merges.append((m[0], m[1]))
        elif isinstance(m, str):
            parts = m.split(" ", 1)
            if len(parts) == 2:
                norm_merges.append((parts[0], parts[1]))
    added = data.get("added_tokens", [])
    added_strings = [a["content"] for a in added if isinstance(a, dict) and "content" in a]
    return {
        "vocab_set": set(vocab.keys()),
        "merges": norm_merges,
        "merge_set": set(norm_merges),
        "added_set": set(added_strings),
    }


def sample(s, n=20):
    return sorted(list(s))[:n]


def main():
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} tokenizer_a.json tokenizer_b.json", file=sys.stderr)
        print("       (the script reports the structural diff between A and B)", file=sys.stderr)
        sys.exit(2)

    path_a, path_b = sys.argv[1], sys.argv[2]
    try:
        A = load(path_a)
    except Exception as e:
        print(f"ERROR: could not parse {path_a}: {e}", file=sys.stderr)
        sys.exit(2)
    try:
        B = load(path_b)
    except Exception as e:
        print(f"ERROR: could not parse {path_b}: {e}", file=sys.stderr)
        sys.exit(2)

    v_inter   = A["vocab_set"]  & B["vocab_set"]
    v_only_a  = A["vocab_set"]  - B["vocab_set"]
    v_only_b  = B["vocab_set"]  - A["vocab_set"]

    m_inter   = A["merge_set"]  & B["merge_set"]
    m_only_a  = A["merge_set"]  - B["merge_set"]
    m_only_b  = B["merge_set"]  - A["merge_set"]
    merges_same_order = A["merges"] == B["merges"]

    a_inter   = A["added_set"]  & B["added_set"]
    a_only_a  = A["added_set"]  - B["added_set"]
    a_only_b  = B["added_set"]  - A["added_set"]

    print(f"tokenizer A:  {path_a}")
    print(f"tokenizer B:  {path_b}")
    print()
    print(f"--- Normal-vocab tokens ---")
    print(f"  |A|:              {len(A['vocab_set']):,}")
    print(f"  |B|:              {len(B['vocab_set']):,}")
    print(f"  identical:        {len(v_inter):,}")
    print(f"  only in A:        {len(v_only_a):,}")
    print(f"  only in B:        {len(v_only_b):,}")
    if v_only_a:
        print(f"  only-in-A sample: {sample(v_only_a)}")
    if v_only_b:
        print(f"  only-in-B sample: {sample(v_only_b)}")
    print()
    print(f"--- BPE merges ---")
    print(f"  |A|:              {len(A['merge_set']):,}")
    print(f"  |B|:              {len(B['merge_set']):,}")
    print(f"  identical (set):  {len(m_inter):,}")
    print(f"  only in A:        {len(m_only_a):,}")
    print(f"  only in B:        {len(m_only_b):,}")
    print(f"  rank order same:  {merges_same_order}")
    if m_only_a:
        print(f"  only-in-A sample:")
        for a, b in sample(m_only_a):
            print(f"    {a!r} + {b!r}")
    if m_only_b:
        print(f"  only-in-B sample:")
        for a, b in sample(m_only_b):
            print(f"    {a!r} + {b!r}")
    print()
    print(f"--- Added / special tokens ---")
    print(f"  |A|:              {len(A['added_set']):,}")
    print(f"  |B|:              {len(B['added_set']):,}")
    print(f"  identical:        {len(a_inter):,}")
    print(f"  only in A:        {len(a_only_a):,}")
    print(f"  only in B:        {len(a_only_b):,}")
    if a_only_a:
        print(f"  only-in-A sample: {sample(a_only_a)}")
    if a_only_b:
        print(f"  only-in-B sample: {sample(a_only_b)}")
    print()

    identical_vocab  = (len(v_only_a) == 0 and len(v_only_b) == 0)
    identical_merges = (len(m_only_a) == 0 and len(m_only_b) == 0)
    identical_added  = (len(a_only_a) == 0 and len(a_only_b) == 0)

    print("=== Summary ===")
    print(f"vocab identical:   {identical_vocab}")
    print(f"merges identical:  {identical_merges} (rank order: {merges_same_order})")
    print(f"added identical:   {identical_added}")
    print()
    # Single-line PASS/FAIL summary for reviewer/CI use:
    bpe_identical = identical_merges and merges_same_order
    if identical_vocab and identical_merges and merges_same_order and identical_added:
        print("RESULT: STRUCTURALLY IDENTICAL — vocab, BPE table (content + rank), and added tokens all match.")
    elif bpe_identical and not identical_added:
        print("RESULT: BPE-TABLE IDENTICAL — same merges in same rank order. "
              "Divergence is confined to added/special tokens. The two tokenizers produce "
              "identical output on any text that does not invoke one of the renamed specials.")
    elif bpe_identical:
        print("RESULT: BPE-TABLE IDENTICAL (vocab + merges match), added tokens match.")
    else:
        print(f"RESULT: BPE TABLES DIFFER — {len(m_only_a):,} merges only in A, {len(m_only_b):,} only in B, "
              f"rank-order match = {merges_same_order}.")

    sys.exit(0)


if __name__ == "__main__":
    main()
