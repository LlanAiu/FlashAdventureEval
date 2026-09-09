#!/bin/bash
# Entrypoint for vLLM model services.
#
# Env vars (set by docker-compose.yml):
#   MODEL_ID       — HuggingFace model to load
#   SERVED_NAME    — primary name the model is served under
#   MODEL_ALIAS    — secondary name (optional, for backward compat)
#   TP             — tensor parallel size
#   MAX_MODEL_LEN  — max context length
#   GPU_MEM        — GPU memory utilization
#   QUANT_FLAG     — quantization flag (e.g. "--quantization awq" or empty)
#   KV_QUANT       — kv-cache dtype (e.g. "fp8" or empty)
#
# ${VAR:+"$VAR"} emits the quoted value only when VAR is non-empty,
# so flags drop out cleanly when not needed.

set -euo pipefail

# Build the fp8 kv-cache flag only when KV_QUANT is set.
# vllm expects: --kv-cache-dtype <dtype>
if [ -n "${KV_QUANT:-}" ]; then
    FP8_ARGS=(--kv-cache-dtype "$KV_QUANT")
else
    FP8_ARGS=()
fi

exec vllm serve \
    "$MODEL_ID" \
    --served-model-name "$SERVED_NAME" \
    ${MODEL_ALIAS:+"--model" "$MODEL_ALIAS"} \
    ${QUANT_FLAG:+"$QUANT_FLAG"} \
    "${FP8_ARGS[@]:+${FP8_ARGS[@]}}" \
    --tensor-parallel-size "$TP" \
    --max-model-len "$MAX_MODEL_LEN" \
    --gpu-memory-utilization "$GPU_MEM" \
    --host 0.0.0.0 --port 8000 \
    --enable-prefix-caching \
    --enable-chunked-prefill
