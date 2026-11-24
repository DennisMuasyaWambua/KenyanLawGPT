#!/usr/bin/env bash
# Convert a Hugging Face Whisper fine-tune into the CTranslate2 format that
# faster-whisper loads, on the server, in a throwaway container (the AI image
# stays free of torch/transformers).
#
#   services/ai/scripts/convert_whisper_ct2.sh microsoft/paza-whisper-large-v3-turbo \
#       /opt/wakiliai/models/paza-whisper-large-v3-turbo-ct2
#
# Then set WHISPER_MODEL=/models/<dir name> in /opt/wakiliai/.env (docker-compose
# mounts ./models read-only at /models) and `docker compose up -d ai`.
#
# Weights are loaded directly as float16 (~1.6 GB peak for a large-v3-turbo
# fine-tune instead of ~3.5 GB in float32), so the conversion fits beside the
# running stack on an 8 GB box. faster-whisper then runs it as int8 on CPU.
set -euo pipefail

REPO="${1:?Hugging Face repo id, e.g. microsoft/paza-whisper-large-v3-turbo}"
OUT="${2:?output directory, e.g. /opt/wakiliai/models/paza-whisper-large-v3-turbo-ct2}"
WORK="$(mktemp -d /tmp/ct2-convert.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$(dirname "$OUT")"

cat > "$WORK/convert.py" <<'PY'
import sys
import torch
from huggingface_hub import snapshot_download
from ctranslate2.converters import TransformersConverter


class FP16Converter(TransformersConverter):
    def load_model(self, model_class, model_name_or_path, **kwargs):
        kwargs["torch_dtype"] = torch.float16
        return model_class.from_pretrained(model_name_or_path, **kwargs)


repo, out = sys.argv[1], sys.argv[2]
src = snapshot_download(repo, local_dir="/work/hf",
                        allow_patterns=["*.json", "*.txt", "model.safetensors"])
files = [f for f in ("tokenizer_config.json", "preprocessor_config.json", "vocab.json", "merges.txt",
                     "added_tokens.json", "special_tokens_map.json", "normalizer.json")]
FP16Converter(src, copy_files=files, low_cpu_mem_usage=True).convert(out, quantization="float16", force=True)
print("converted", repo, "->", out)
PY

docker run --rm --memory 3g --memory-swap 3g --cpus 2 \
  -v "$WORK:/work" -v "$(dirname "$OUT"):/out" python:3.12-slim bash -c "
    pip -q install --index-url https://download.pytorch.org/whl/cpu torch &&
    pip -q install 'ctranslate2==4.6.*' 'transformers<5' huggingface_hub safetensors &&
    python /work/convert.py '$REPO' '/out/$(basename "$OUT")'"
ls -la "$OUT"
