#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export PYTHONPATH="${PYTHONPATH:-python/runner-core/src}"

run_quant() {
  local quant="$1"
  local filename="$2"
  local output_dir="$3"

  python3 -m infergrade run \
    --model TinyLlama/TinyLlama-1.1B-Chat-v1.0 \
    --backend llama.cpp \
    --tier canary \
    --quant-artifact "hf://TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/${filename}" \
    --quant-artifact-filename "$filename" \
    --execution-mode local_native \
    --deployment-profile interactive_chat_v1 \
    --capability none \
    --output "$output_dir" \
    --real-run
}

run_quant "Q2_K" "tinyllama-1.1b-chat-v1.0.Q2_K.gguf" "runs/sprint59_tinyllama_q2_k"
run_quant "Q4_K_M" "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf" "runs/sprint59_tinyllama_q4_k_m"

python3 -m infergrade inspect-bundle runs/sprint59_tinyllama_q2_k
python3 -m infergrade inspect-bundle runs/sprint59_tinyllama_q4_k_m
