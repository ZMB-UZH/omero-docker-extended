# AI Filename Parsing Investigation

Investigation conducted 2026-04-08 for the OMP plugin's filename parsing feature.

## Goal

Find the best small AI model (under 4B parameters) that can run in Docker on CPU-only hardware to automatically parse microscopy filenames into structured variables. The model replaces external API calls (OpenAI, Anthropic, Groq, etc.) with a local, private, fast alternative.

## Current system

The OMP plugin (`omeroweb_omp_plugin/services/ai_assist.py`) sends filenames to external AI APIs with a prompt that asks the model to extract variable values while dropping structural labels. For example:

- Input: `10444-ec-01-sa-01-sc-01-20x.tif`
- Expected output: `10444,01,01,01,20x` (labels `ec`, `sa`, `sc` dropped)

## Hardware constraints

- Server: 32GB RAM, no GPU
- Must run in Docker alongside existing OMERO stack
- Latency target: under 30 seconds per pattern (not per file)
- CPU-only inference (no CUDA)

## Infrastructure

All models tested via Ollama (`ollama/ollama:0.21.0`) running in Docker on port 11434. Models stored on `/disks/omero_temp/ollama`. GGUF quantized formats.

## Test filenames

### Simple separator-delimited (labels and values alternate)

| Filename | Expected values |
| --- | --- |
| `10444-ec-01-sa-01-sc-01-20x.tif` | `10444,01,01,01,20x` |
| `10445-ec-02-sa-03-sc-04-40x.tif` | `10445,02,03,04,40x` |
| `sample_cond_ctrl_rep_3_ch_DAPI.tif` | `ctrl,3,DAPI` |
| `sample_cond_treated_rep_4_ch_GFP.tif` | `treated,4,GFP` |

### Complex (fused tokens, mixed separators, ambiguous labels)

| Filename | Expected values |
| --- | --- |
| `confocal-z01-ch01-t001.tif` | `01,01,001` |
| `slide01_region02_z003.tif` | `01,02,003` |
| `WellA01_ChannelDAPI_Seq0001.nd2` | `A01,DAPI,0001` |
| `mouse_brain_region_hippocampus_slice_04_stain_GFAP.tif` | `hippocampus,04,GFAP` |
| `IMG_20231015_cell_line_HeLa_passage_12_mag_63x.tif` | `20231015,HeLa,12,63x` |

## Approaches tested

### Approach 1: Direct multi-file parsing

Send all filenames at once, ask the model to output one line of values per filename.

**Result**: Complete failure for all models under 3B. Models under 1B produce garbage, code fences, or repeat filenames. 3B models get ~57% on simple cases but fail on complex ones.

### Approach 2: Hybrid "Parse-One-Propagate-Many"

1. Send ONE representative filename to the LLM
2. LLM classifies each token as LABEL or VALUE
3. Build a regex from the pattern
4. Apply regex deterministically to all other filenames with the same structure

**Result**: This is the winning approach. When the LLM gets the pattern right, propagation is 100% accurate and instant. The LLM only needs to be called once per unique pattern group.

## Model benchmark results

### Round 1: Sub-0.5B models (direct parsing, 12 test files)

| Model | Params | Correct | Latency | Notes |
| --- | --- | --- | --- | --- |
| SmolLM2 135M | 135M | 0/12 (0%) | ~16s | Produces garbage, code fences |
| SmolLM2 360M | 360M | 0/12 (0%) | ~16s | Repeats filenames instead of parsing |
| Qwen2.5 0.5B | 490M | 0/12 (0%) | ~7s | Outputs JSON code blocks |
| Qwen3 0.6B distilled | 600M | 0/12 (0%) | ~55s | Empty output (thinking model uses all tokens) |

**Conclusion**: Models under 1B are completely incapable of this task.

### Round 2: 1-1.5B models (direct parsing, 12 test files)

| Model | Params | Correct | Latency | Notes |
| --- | --- | --- | --- | --- |
| Llama 3.2 1B | 1B | 3/12 (25%) | ~24s | Gets simple ec-sa-sc right, fails rest |
| Qwen2.5 1.5B | 1.5B | 0/12 (0%) | ~73s | Prepends "-1" to all values |
| Granite 3.1 MoE 1B | 1B | 0/12 (0%) | ~41s | Merges all filenames into one line |

**Conclusion**: 1B models show first signs of capability but are unreliable.

### Round 3: 3B models (direct parsing, 7 test files)

| Model | Params | Correct | Latency | Notes |
| --- | --- | --- | --- | --- |
| Qwen2.5 3B | 3B | 4/7 (57%) | ~39s batch | Best structured output |
| Llama 3.2 3B | 3B | 4/7 (57%) | ~30s batch | Equal accuracy |

**Conclusion**: 3B is the minimum viable size for this task.

### Round 4: 3B models with hybrid approach (10 pattern groups, 20 files)

| Model | Groups correct | Files correct | Total LLM time |
| --- | --- | --- | --- |
| Qwen2.5 3B | 2/4 groups perfect | 6/10 (60%) | ~58s |
| Llama 3.2 3B | 2/4 groups perfect | 6/10 (60%) | ~52s |

### Round 5: Distilled and specialized models (single file test)

| Model | Params | Output | Latency | Notes |
| --- | --- | --- | --- | --- |
| DeepSeek-R1 1.5B distilled | 1.5B | Empty | ~52s | Thinking model, all tokens on reasoning |
| Qwen3 1.7B | 1.7B | Empty | ~70s | Thinking model, same problem |
| Qwen3 4B | 4B | Empty | ~83s | Thinking model, /no_think fails in Ollama |

**Conclusion**: Reasoning/thinking models are unsuitable. They spend all tokens on
internal chain-of-thought and produce no visible output.

### Key finding: LLM understands fused tokens

When testing `confocal-z01-ch01-t001.tif`, Qwen2.5:3B output:

```text
confocal:LABEL,z:LABEL,01:VALUE,ch:LABEL,01:VALUE,t:LABEL,001:VALUE
```

This is semantically CORRECT. The model correctly split `z01` into `z` (label)
and `01` (value). The regex builder could not handle this because it does naive
`split(sep)` which produces 4 tokens while the model sees 7. The model is
smarter than the propagation code.

## Winner: Qwen2.5:3B

**Why Qwen2.5:3B wins:**

1. Produces structured output (not empty, not garbage)
2. Correctly identifies labels vs values in clean separator-delimited filenames
3. Understands fused tokens (`z01` to `z:LABEL,01:VALUE`)
4. ~15-20s per pattern call on CPU (acceptable for hybrid approach)
5. 1.9GB model size, fits in 32GB RAM alongside OMERO stack
6. Apache 2.0 license
7. Consistent across runs with temperature=0

**Known limitations:**

- Fused tokens: model parses correctly but regex builder needs enhancement
- Ambiguous tokens (`hippocampus`, `20231015`): sometimes misclassified
- Cold start: first call after model load takes ~20s extra

## Production architecture

```text
OMERO.web (OMP Plugin) ---> Ollama API (:11434) ---> Qwen2.5:3B (GGUF, CPU)
    one call per                OpenAI-compatible         1.9 GB model
    pattern group               REST API                  ~15-20s/call
    regex propagation
    handles rest
```

- Ollama container in docker-compose on internal Docker network
- OMP plugin calls `POST /api/generate` or `/v1/chat/completions`
- One LLM call per unique filename pattern (hybrid approach)
- Regex propagation handles all remaining files deterministically

## Deployment

- Container: `ollama/ollama:0.21.0`
- Model: `qwen2.5:3b` (auto-pulled on first use)
- Port: 11434 (internal Docker network only)
- Volume: `/disks/omero_temp/ollama:/root/.ollama`
- Memory: ~2GB for model + ~1GB runtime overhead

## Future investigation directions

1. **Regex builder enhancement**: handle fused tokens by using LLM's sub-token splits
2. **Fine-tuning**: fine-tune Qwen2.5:3B on microscopy filename datasets
3. **Few-shot from user data**: include examples from the user's actual dataset
4. **GPU acceleration**: if GPU becomes available, same model runs 10x faster
5. **User feedback loop**: let users correct wrong classifications
6. **Batched pattern detection**: group filenames by structural similarity first
