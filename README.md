# BrahmicTokenizer-131K

A 131,072-vocabulary byte-level BPE tokenizer that closes the Brahmic compression gap at the 131K-vocabulary class while preserving the English, EU-language, and code compression of OpenAI's o200k_base. Drop-in replacement for any o200k_base training pipeline.

**Model artifact**: <https://huggingface.co/theschoolofai/BrahmicTokenizer-131K>
**Paper**: <https://arxiv.org/abs/2605.29379>

## Citation

```
@misc{shravan2026brahmictokenizer,
  title={BrahmicTokenizer-131K: An Indic-Capable Drop-In Replacement for o200k\_base},
  author={Rohan Shravan},
  year={2026},
  eprint={2605.29379},
  archivePrefix={arXiv},
  primaryClass={cs.CL},
  url={https://arxiv.org/abs/2605.29379}
}
```

## Headline results

| Axis | BrahmicTokenizer-131K | Best comparator at 131K (Tekken/Sarvam-m) | Improvement |
|---|---|---|---|
| 27M-doc Indic corpus | 6.62 B tokens | 9.04 B tokens | **−26.7%** |
| Indic Or (4.31× compression on 27M corpus) | 228 M tokens | 984 M tokens | **−76.79%** |
| FLORES-200 mean Brahmic fertility | 2.84 | 4.87 | **−41.8%** |
| FLORES-200 Odia | 4.13 tokens/word | 18.18 (byte-fallback) | 4.40× ratio |
| HumanEval tokens/char | 0.295 | 0.307 | −4.0% |
| MBPP tokens/char | 0.320 | 0.338 | −5.4% |
| GSM8K tokens/char | 0.301 | 0.351 | −14.2% |
| English fertility | 1.235 | 1.267 | −2.5% (matches o200k_base 1.232) |

Across the 14-tokenizer benchmark, BrahmicTokenizer-131K is the **only tokenizer simultaneously competitive on Brahmic, English, EU, code, and math** at the 131K vocabulary budget.

## Quick start

```python
from transformers import AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained("theschoolofai/BrahmicTokenizer-131K")

print(tokenizer.encode("भारत एक देश है", add_special_tokens=False))
# -> [66526, 2420, 13092, 732]

print(tokenizer.encode("1234567890", add_special_tokens=False))
# -> [4660, 14932, 23133, 26]
```

## Repository contents

```
.
├── tokenizer.json                       # the BPE artifact (vocab 131,072, merges 301,398)
├── verify_no_cross_script_merges.py     # 4 reviewer-runnable verification scripts
├── verify_max_byte_length.py
├── verify_kronecker_constraints_unified.py
├── verify_sarvam_m_structural_identity.py
├── evaluate_fertility_flores.py         # reproduces paper Table 4 (FLORES-200 fertility)
├── evaluate_fertility_in22.py           # reproduces paper Table 5 (IN22-Gen fertility)
├── evaluate_code_math.py                # reproduces paper Table 11 (HumanEval/MBPP/GSM8K)
├── tokenize_full_indic_corpus.py        # reproduces paper Table 3 (27M-corpus headline)
├── reference_outputs/                   # committed outputs from the above scripts
│   ├── evaluate_fertility_flores.json
│   └── evaluate_fertility_in22.json
├── audit/                               # 23-test internal audit suite (§4.4, App B)
│   ├── tokenizer_audit.py
│   ├── audit_log_hybrid.txt
│   └── report_hybrid_full/
├── LICENSE                              # Apache 2.0
└── README.md
```

## Reproduction

### 5-minute smoke test (paper Appendix A)

```bash
BRAHMIC=./tokenizer.json
python verify_no_cross_script_merges.py        $BRAHMIC && \
python verify_max_byte_length.py               $BRAHMIC && \
python verify_kronecker_constraints_unified.py $BRAHMIC && \
python verify_sarvam_m_structural_identity.py  $BRAHMIC $BRAHMIC
```

Expected output: 4 PASS lines, exit 0. Key checked claims:

- `merge-rule entries: 301,398`, `cross-script: 0`, PASS: no cross-script entries in the merge list
- `vocab size: 131,072`, `normal: 130,716`, `special: 356`, `tokens > 32 bytes: 0`, PASS: all 130,716 normal tokens are within 32 bytes
- Kronecker constraints satisfied at POS_DIM=32 (max byte length ≤ 32, zero cross-script tokens)
- Tekken ≡ Sarvam-m structural identity (vocab + merges + added tokens byte-identical)

### Fertility reproduction (paper Tables 4 and 5)

```bash
python evaluate_fertility_flores.py --tokenizers all --languages all
python evaluate_fertility_in22.py   --tokenizers all --languages all
```

Each script downloads the 11 paper-benchmark tokenizers from HuggingFace (Sarvam-30B, Sarvam-1, Gemma-3-1B, GPT-OSS-120B, Tekken, Krutrim-1, DeepSeek-R1, IndicBERTv2-SS, Qwen3-8B, Llama-3.1-8B) on first run. Some are gated; see each tokenizer's HF page to accept terms. FLORES-200 download (one-liner):

```bash
curl -sL -o /tmp/flores200_dataset.tar.gz \
  https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz
tar -xzf /tmp/flores200_dataset.tar.gz -C /tmp/
```

IN22-Gen is gated on HuggingFace; accept terms at <https://huggingface.co/datasets/ai4bharat/IN22-Gen> and run `huggingface-cli login` before the script.

The committed `reference_outputs/evaluate_fertility_flores.json` and `evaluate_fertility_in22.json` are the exact outputs against the shipped `tokenizer.json` — diff your run against them to confirm reproduction.

### 27M-corpus reproduction (paper Table 3)

```bash
python tokenize_full_indic_corpus.py --tokenizer brahmic
python tokenize_full_indic_corpus.py --tokenizer tekken
python tokenize_full_indic_corpus.py --tokenizer sarvam1
python tokenize_full_indic_corpus.py --tokenizer sarvam30b
```

Reads the AI4Bharat Sangraha monolingual subsets, Bharat Parallel Corpus Collection, Samanantar, NLLB-filtered, IndicComparable, ILCI, and Sarvam-AI's Samvaad-Hi. Each run takes 80–120 minutes on an M1 Mac.

### 23-test audit suite (paper §4.4, Appendix B)

```bash
python audit/tokenizer_audit.py --tokenizer FINAL_TOKENIZER/ --report audit_report/
```

The committed `audit/audit_log_hybrid.txt` and `audit/report_hybrid_full/` are the outputs from running the suite on the shipped tokenizer. Headline result: 18 PASS, 4 INFO, 1 WARN, 0 FAIL; vocab utilization 99.2%, byte-fragment rate 1.0% corpus-wide, garbage tokens 46 (0.035% of vocab, all inherited from o200k_base).

### Reviewer-time expectation

| Test | Wall clock |
|---|---|
| 4-script smoke test | 5 minutes |
| `evaluate_fertility_flores.py` | 30 minutes (incl. tokenizer downloads on first run) |
| `evaluate_fertility_in22.py` | 20 minutes |
| `evaluate_code_math.py` | 5 minutes |
| 23-test audit suite | 15 minutes |
| 27M-corpus run (4 tokenizers) | 6–8 hours |

Full reproduction of every paper claim: ~10 hours on a single M1 Mac.

## Environment

```
Python >= 3.9
tokenizers >= 0.15
transformers >= 4.30
tiktoken
pandas
pyarrow
datasets
```

`pip install tokenizers transformers tiktoken pandas pyarrow datasets`

## License

Apache License 2.0. This work is a derivative of OpenAI's o200k_base tokenizer, released through the MIT-licensed [tiktoken](https://github.com/openai/tiktoken) repository; Apache 2.0 is compatible with incorporating MIT-licensed material.

The reproduction scripts download public datasets (FLORES-200, IN22-Gen, HumanEval, MBPP, GSM8K, the AI4Bharat Indic stack, Sarvam-AI Samvaad-Hi) from their canonical sources at runtime; we do not redistribute them.
