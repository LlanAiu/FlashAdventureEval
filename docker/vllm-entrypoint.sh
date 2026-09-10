#!/bin/bash
# Entrypoint for vLLM model services.
#
# Env vars (set by docker-compose.yml):
#   MODEL_ID       — HuggingFace model to load
#   SERVED_NAME    — primary name the model is served under
#   TP             — tensor parallel size
#   MAX_MODEL_LEN  — max context length
#   GPU_MEM        — GPU memory utilization
#   W_QUANT        — quantization flag (e.g. "--quantization awq" or empty)
#   KV_QUANT       — kv-cache dtype (e.g. "fp8" or empty)


set -euo pipefail

if [ -n "${KV_QUANT:-}" ]; then
    KV_QUANT_ARGS=(--kv-cache-dtype "$KV_QUANT")
else
    KV_QUANT_ARGS=()
fi

if [ -n "${W_QUANT:-}"]; then
    W_QUANT_ARGS=(--quantization "$W_QUANT")
else
    W_QUANT_ARGS=()
fi


CUDA_VISIBLE_DEVICES="$GPUS" exec vllm serve \
    "$MODEL_ID" \
    --served-model-name "$SERVED_NAME" \
    ${W_QUANT_ARGS[@]:+"${W_QUANT_ARGS[@]}"} \
    ${KV_QUANT_ARGS[@]:+"${KV_QUANT_ARGS[@]}"} \
    --tensor-parallel-size "$TP" \
    --max-model-len "$MAX_MODEL_LEN" \
    --gpu-memory-utilization "$GPU_MEM" \
    --host 0.0.0.0 --port 8000 \
    --enable-prefix-caching \
    --enable-chunked-prefill \
    --max-num-batched-tokens 8192 \
    --max-num-seqs 32 \
    --enable-auto-tool-choice \
    --tool-call-parser "hermes" \
