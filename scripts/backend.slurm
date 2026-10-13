#!/bin/bash
#SBATCH -p cuda
#SBATCH --gres=gpu:1
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH -J backend
#SBATCH -o backend-%j.out

ROOT=$HOME/multimodal-surveillance-iseql/backend
CONDA_BASE=$HOME/miniconda3
ENV_DIR=$CONDA_BASE/envs/py310
PORT=8000

echo "=== Job $SLURM_JOB_ID on $(hostname) ==="
if [ -n "${OLLAMA_BASE_URL:-}" ]; then
  echo "OLLAMA_BASE_URL=$OLLAMA_BASE_URL"
else
  echo "OLLAMA_BASE_URL not set, backend uses config default"
fi
nvidia-smi || true

export PATH="$ENV_DIR/bin:$PATH"
export LD_LIBRARY_PATH="$ENV_DIR/lib:${LD_LIBRARY_PATH:-}"
cd $ROOT
export PROFILE=hpc-slurm
export PYTHONPATH=src
exec pipenv run uvicorn start_application:StartApplication --host 0.0.0.0 --port $PORT
