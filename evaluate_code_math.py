#!/usr/bin/env python3
"""
T14 + T15 — Code and math/LaTeX fertility for all 13 tokenizers.

Corpora:
  T14 (code):
    - HumanEval (164 problems): prompt + canonical_solution
    - MBPP-sanitized (257 problems test split): code field
  T15 (math/LaTeX):
    - GSM8K (7,473 train problems): question + answer
    - arXiv-summarization (100 random abstracts): the abstract field

Metrics:
  - tokens / word
  - tokens / char (standard for code)
  - bytes / token  (standard compression metric)
"""
import os, csv, time, random
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from pathlib import Path
from datasets import load_dataset

OUT = Path("./reference_outputs")
OLD_TOK = "./old_tokenizer.json"
NEW_TOK = "./tokenizer.json"

TOKENIZERS = [
    ("OLD",          ("local", OLD_TOK)),
    ("HYBRID",       ("local", NEW_TOK)),
    ("o200k_base",   ("tiktoken", "o200k_base")),
    ("Tekken",       ("hf", "mistralai/Mistral-Nemo-Base-2407")),
    ("LLaMA-3",      ("hf", "NousResearch/Meta-Llama-3-8B")),
    ("Gemma-3-1B",   ("hf", "google/gemma-3-1b-pt")),
    ("Gemma-2-9B",   ("hf", "google/gemma-2-9b")),
    ("Qwen-2.5-7B",  ("hf", "Qwen/Qwen2.5-7B")),
    ("Sarvam-1",     ("hf", "sarvamai/sarvam-1")),
    ("Sarvam-m",     ("hf", "sarvamai/sarvam-m")),
    ("Krutrim-1",    ("hf", "krutrim-ai-labs/Krutrim-1-instruct")),
    ("Airavata",     ("hf", "ai4bharat/Airavata")),
    ("GPT-OSS-120B", ("hf", "openai/gpt-oss-120b")),
]


def make_adapter(kind, src):
    if kind == "local":
        from tokenizers import Tokenizer
        t = Tokenizer.from_file(src)
        return lambda s, t=t: t.encode(s).ids
    if kind == "tiktoken":
        import tiktoken
        e = tiktoken.get_encoding(src)
        return lambda s, e=e: e.encode(s, disallowed_special=())
    if kind == "hf":
        from transformers import AutoTokenizer
        t = AutoTokenizer.from_pretrained(src)
        return lambda s, t=t: t.encode(s, add_special_tokens=False)
    raise ValueError(kind)


def load_corpora():
    print("Loading corpora...")
    he = load_dataset("openai_humaneval", split="test")
    humaneval_texts = [r["prompt"] + r["canonical_solution"] for r in he]
    print(f"  HumanEval: {len(humaneval_texts)} examples")

    mbpp = load_dataset("google-research-datasets/mbpp", "sanitized", split="test")
    mbpp_texts = [r["code"] for r in mbpp if r["code"]]
    print(f"  MBPP-sanitized: {len(mbpp_texts)} examples")

    gsm = load_dataset("openai/gsm8k", "main", split="train")
    gsm_texts = [r["question"] + "\n" + r["answer"] for r in gsm]
    print(f"  GSM8K: {len(gsm_texts)} examples")

    arx = load_dataset("ccdv/arxiv-summarization", split="test")
    random.seed(42)
    idxs = random.sample(range(len(arx)), min(100, len(arx)))
    arx_texts = [arx[i]["abstract"] for i in idxs if arx[i]["abstract"]]
    print(f"  arXiv abstracts (sampled): {len(arx_texts)}")

    return {
        "HumanEval": humaneval_texts,
        "MBPP": mbpp_texts,
        "GSM8K": gsm_texts,
        "arXiv-abs": arx_texts,
    }


def bench(name, encode, corpora):
    rows = []
    for corp, texts in corpora.items():
        tot_tok = tot_words = tot_chars = tot_bytes = 0
        for s in texts:
            if not isinstance(s, str) or not s: continue
            ids = encode(s)
            tot_tok += len(ids)
            tot_words += len(s.split())
            tot_chars += len(s)
            tot_bytes += len(s.encode("utf-8"))
        rows.append({
            "tokenizer": name, "corpus": corp,
            "n_examples": sum(1 for s in texts if isinstance(s, str) and s),
            "n_tokens": tot_tok, "n_words": tot_words,
            "n_chars": tot_chars, "n_bytes": tot_bytes,
            "tokens_per_word": tot_tok / max(tot_words, 1),
            "tokens_per_char": tot_tok / max(tot_chars, 1),
            "bytes_per_token": tot_bytes / max(tot_tok, 1),
        })
    return rows


def write_csv_md(rows, csv_name, md_title, prefix_corpora):
    csv_path = OUT / csv_name
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"wrote {csv_path}")

    # Build MD tables
    by_tok = {}
    for r in rows:
        by_tok.setdefault(r["tokenizer"], {})[r["corpus"]] = r

    md = [f"# {md_title}\n"]
    # tokens/char table
    md.append("## tokens/char (lower = better compression)\n")
    md.append("| Tokenizer | " + " | ".join(prefix_corpora) + " |")
    md.append("|---" * (len(prefix_corpora)+1) + "|")
    for tn, _ in TOKENIZERS:
        if tn not in by_tok: continue
        vals = [f"{by_tok[tn][c]['tokens_per_char']:.4f}" if c in by_tok[tn] else "-" for c in prefix_corpora]
        md.append(f"| **{tn}** | " + " | ".join(vals) + " |")
    md.append("")
    md.append("## tokens/word\n")
    md.append("| Tokenizer | " + " | ".join(prefix_corpora) + " |")
    md.append("|---" * (len(prefix_corpora)+1) + "|")
    for tn, _ in TOKENIZERS:
        if tn not in by_tok: continue
        vals = [f"{by_tok[tn][c]['tokens_per_word']:.3f}" if c in by_tok[tn] else "-" for c in prefix_corpora]
        md.append(f"| **{tn}** | " + " | ".join(vals) + " |")
    md.append("")
    md.append("## bytes/token (higher = more compression)\n")
    md.append("| Tokenizer | " + " | ".join(prefix_corpora) + " |")
    md.append("|---" * (len(prefix_corpora)+1) + "|")
    for tn, _ in TOKENIZERS:
        if tn not in by_tok: continue
        vals = [f"{by_tok[tn][c]['bytes_per_token']:.3f}" if c in by_tok[tn] else "-" for c in prefix_corpora]
        md.append(f"| **{tn}** | " + " | ".join(vals) + " |")
    md_path = OUT / (csv_name.replace(".csv", ".md"))
    md_path.write_text("\n".join(md))
    print(f"wrote {md_path}")


def main():
    corpora = load_corpora()
    all_rows = []
    for name, (kind, src) in TOKENIZERS:
        print(f"\n=== {name} ===")
        t0 = time.time()
        try: enc = make_adapter(kind, src)
        except Exception as e:
            print(f"  load FAIL: {e}"); continue
        rows = bench(name, enc, corpora)
        all_rows.extend(rows)
        for r in rows:
            print(f"  {r['corpus']:<10}  tok/word={r['tokens_per_word']:.3f}  tok/char={r['tokens_per_char']:.4f}  b/tok={r['bytes_per_token']:.3f}")
        print(f"  ({time.time()-t0:.1f}s)")

    # Split into code (T14) and math (T15)
    code_rows = [r for r in all_rows if r["corpus"] in ("HumanEval", "MBPP")]
    math_rows = [r for r in all_rows if r["corpus"] in ("GSM8K", "arXiv-abs")]

    write_csv_md(code_rows, "fertility_table_code.csv",
                 "T14 — Code fertility (HumanEval + MBPP-sanitized)",
                 ["HumanEval", "MBPP"])
    write_csv_md(math_rows, "fertility_table_math.csv",
                 "T15 — Math/LaTeX fertility (GSM8K + arXiv abstracts)",
                 ["GSM8K", "arXiv-abs"])


if __name__ == "__main__":
    main()
