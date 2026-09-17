#!/usr/bin/env bash

set -e

cd "$(dirname "$0")"

if [[ "${1:-}" == "--turbo" ]]; then
    export WHISPER_TURBO=1
fi

source .venv/bin/activate

export LD_LIBRARY_PATH="$(
python - <<'PY'
import nvidia.cublas.lib
import nvidia.cudnn.lib

print(
    next(iter(nvidia.cublas.lib.__path__))
    + ":"
    + next(iter(nvidia.cudnn.lib.__path__))
)
PY
):${LD_LIBRARY_PATH:-}"

exec uvicorn server:app \
    --host 0.0.0.0 \
    --port 8000
