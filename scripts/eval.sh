#!/usr/bin/env bash
#
# eval.sh - one-shot rerun of the evaluation notebooks, in place (profile-aware via PROFILE).
#
# Every notebook is executed via papermill and the executed result is saved
# back over the same source file (experiments/notebooks/<name>.ipynb), so the
# committed notebooks always carry fresh outputs after a run.
#
# Runtime artifacts (both git-ignored, see .gitignore: *.out and *.log):
#   experiments/notebooks/<name>.out   per-job papermill stdout / stderr
#   experiments/notebooks/progress.log rolling queue status
# Monitor with: `tail -f experiments/notebooks/progress.log`
#
# Run modes (mutually exclusive; the last one wins if several are set):
#   AUDIO_ONLY=1      only the 2 audio window/hop ablation notebooks
#   VISUAL_ONLY=1     only the 8 visual eval notebooks (gemini + mistral chains)
#   REID_ONLY=1       only the 4 vlm_rag_reid visual notebooks (embedding stores)
#   MULTIMODAL_ONLY=1 only the 8 multimodal eval notebooks (SQL-only)
#   (none)            full: audio + visual in parallel, then multimodal
#
# Example: MULTIMODAL_ONLY=1 PROFILE=hpc-slurm ./scripts/eval.sh  or  make hpc-slurm-eval
#
# Exit status: 0 = every notebook succeeded, 1 = at least one failed.
#
set -u

# ---- config -------------------------------------------------------------
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Strict: no silent fallback to a wrong profile/mode.
PROFILE="${PROFILE:-}"
VALID_PROFILES="local hpc hpc-slurm docker mac"
case " $VALID_PROFILES " in
  *" $PROFILE "*) ;;
  "") echo "ERROR: PROFILE not set (use one of: $VALID_PROFILES)" >&2; exit 2 ;;
  *) echo "ERROR: invalid PROFILE='$PROFILE' (use one of: $VALID_PROFILES)" >&2; exit 2 ;;
esac

NOTEBOOKS_DIR="$ROOT/experiments/notebooks"
LOG="$NOTEBOOKS_DIR/progress.log"
case "$PROFILE" in
  hpc|hpc-slurm)
    PY="pipenv"
    PY_ARGS="run python"
    KERNEL="python3"
    ;;
  docker)
    PY="docker"
    PY_ARGS="compose exec backend python"
    KERNEL="python3"
    ;;
   local|mac)
    PY="pipenv"
    PY_ARGS="run python"
    KERNEL="python3"
    ;;
esac

AUDIO_ONLY="${AUDIO_ONLY:-0}"
VISUAL_ONLY="${VISUAL_ONLY:-0}"
REID_ONLY="${REID_ONLY:-0}"
MULTIMODAL_ONLY="${MULTIMODAL_ONLY:-0}"

mode_count=$(( AUDIO_ONLY + VISUAL_ONLY + REID_ONLY + MULTIMODAL_ONLY ))
if [ "$mode_count" -gt 1 ]; then
  echo "ERROR: AUDIO_ONLY, VISUAL_ONLY, REID_ONLY and MULTIMODAL_ONLY are mutually exclusive." >&2
  exit 2
fi

# results file: one "<notebook> <rc>" line per job, in completion order
RESULTS="$(mktemp)"
trap 'rm -f "$RESULTS"' EXIT

# ---- helpers -------------------------------------------------------------
ts()    { date '+%Y-%m-%d %H:%M:%S'; }
nowms() { date +%s%3N; }
banner(){ printf '%s\n' '----------------------------------------' | tee -a "$LOG"; }
log()   { echo "[$(ts)] $*" | tee -a "$LOG"; }

# run_nb <notebook_basename_without_.ipynb>   -- execute in place
run_nb() {
  local nb="$1" rc start
  start=$(nowms)
  log "START  ${nb}.ipynb [profile=$PROFILE]"
  if [[ -n "${PY_ARGS:-}" ]]; then
    # shellcheck disable=SC2086
    $PY $PY_ARGS -m papermill "$NOTEBOOKS_DIR/${nb}.ipynb" "$NOTEBOOKS_DIR/${nb}.ipynb" \
        -k "$KERNEL" --cwd "$NOTEBOOKS_DIR" --no-progress-bar \
        --stdout-file "$NOTEBOOKS_DIR/${nb}.out" --log-level WARNING \
        > /dev/null 2>&1
    rc=$?
  else
    "$PY" -m papermill "$NOTEBOOKS_DIR/${nb}.ipynb" "$NOTEBOOKS_DIR/${nb}.ipynb" \
        -k "$KERNEL" --cwd "$NOTEBOOKS_DIR" --no-progress-bar \
        --stdout-file "$NOTEBOOKS_DIR/${nb}.out" --log-level WARNING \
        > /dev/null 2>&1
    rc=$?
  fi
  echo "$nb $rc" >> "$RESULTS"
  if [ "$rc" -eq 0 ]; then
    log "DONE(0) ${nb}.ipynb  ($(( ($(nowms)-start)/1000 ))s)"
  else
    log "FAIL(${rc}) ${nb}.ipynb  ($(( ($(nowms)-start)/1000 ))s)  -- see ${nb}.out"
  fi
  return "$rc"
}

# worker_chain <chain_label> <nb1> <nb2> ...   -- runs the list SEQUENTIALLY
worker_chain() {
  local label="$1"; shift
  local total=$# i=0 nb
  for nb in "$@"; do
    i=$((i + 1))
    log "== ${label} chain: ${i}/${total} - running ${nb}"
    run_nb "$nb" || return 1
  done
  return 0
}

# ---- job definitions -----------------------------------------------------
AUDIO_NBS=(
  window_hop_ablation_panns
  window_hop_ablation_qwen2_audio
)

VISUAL_GEMINI=(
  visual_eval_gemini_2_5_flash_vlm_rag_reid
  visual_eval_gemini_2_5_flash_no_reid
  visual_eval_gemini_3_6_flash_vlm_rag_reid
  visual_eval_gemini_3_6_flash_no_reid
)

VISUAL_MISTRAL=(
  visual_eval_ministral_3_14b_vlm_rag_reid
  visual_eval_ministral_3_14b_no_reid
  visual_eval_pixtral_12b_vlm_rag_reid
  visual_eval_pixtral_12b_no_reid
)

VISUAL_REID=(
  visual_eval_gemini_2_5_flash_vlm_rag_reid
  visual_eval_gemini_3_6_flash_vlm_rag_reid
  visual_eval_ministral_3_14b_vlm_rag_reid
  visual_eval_pixtral_12b_vlm_rag_reid
)

MULTIMODAL=(
  multimodal_eval_gemini_2_5_flash_vlm_rag_reid_panns
  multimodal_eval_gemini_2_5_flash_vlm_rag_reid_qwen2_audio
  multimodal_eval_gemini_3_6_flash_vlm_rag_reid_panns
  multimodal_eval_gemini_3_6_flash_vlm_rag_reid_qwen2_audio
  multimodal_eval_ministral_3_14b_vlm_rag_reid_panns
  multimodal_eval_ministral_3_14b_vlm_rag_reid_qwen2_audio
  multimodal_eval_pixtral_12b_vlm_rag_reid_panns
  multimodal_eval_pixtral_12b_vlm_rag_reid_qwen2_audio
)

# ---- launch --------------------------------------------------------------
if [ "$AUDIO_ONLY" -eq 1 ]; then      mode_label="audio only"
elif [ "$VISUAL_ONLY" -eq 1 ]; then   mode_label="visual only"
elif [ "$REID_ONLY" -eq 1 ]; then     mode_label="reid only"
elif [ "$MULTIMODAL_ONLY" -eq 1 ]; then mode_label="multimodal only"
else                                  mode_label="full"
fi

banner
log "eval queue start  (root=$ROOT, kernel=$KERNEL)  mode=$mode_label"
banner

if [ "$AUDIO_ONLY" -eq 1 ]; then
  log "audio phase (n=${#AUDIO_NBS[@]}) in parallel"
  for nb in "${AUDIO_NBS[@]}"; do
    ( run_nb "$nb" ) &
  done
  wait

elif [ "$VISUAL_ONLY" -eq 1 ]; then
  log "visual phase: gemini chain (n=${#VISUAL_GEMINI[@]}) + mistral chain (n=${#VISUAL_MISTRAL[@]}) in parallel"
  ( worker_chain "gemini" "${VISUAL_GEMINI[@]}" ) &
  ( worker_chain "mistral" "${VISUAL_MISTRAL[@]}" ) &
  wait

elif [ "$REID_ONLY" -eq 1 ]; then
  log "reid phase: 4 vlm_rag_reid notebooks (embeddings) in parallel"
  for nb in "${VISUAL_REID[@]}"; do
    ( run_nb "$nb" ) &
  done
  wait

else
  if [ "$MULTIMODAL_ONLY" -ne 1 ]; then
    log "phase 1: audio x2 + gemini chain + mistral chain in parallel"
    for nb in "${AUDIO_NBS[@]}"; do
      ( run_nb "$nb" ) &
    done
    ( worker_chain "gemini" "${VISUAL_GEMINI[@]}" ) &
    ( worker_chain "mistral" "${VISUAL_MISTRAL[@]}" ) &
    wait
    banner
    log "PHASE 1 COMPLETE. Starting multimodal...  (n=${#MULTIMODAL[@]})"
  else
    log "multimodal phase (n=${#MULTIMODAL[@]}) in parallel  [SQL-only]"
  fi
  banner
  for nb in "${MULTIMODAL[@]}"; do
    ( run_nb "$nb" ) &
  done
  wait
fi

# ---- summary -------------------------------------------------------------
banner
log "SUMMARY:"
sort "$RESULTS" | while read -r nb rc; do
  if [ "$rc" -eq 0 ]; then status="OK"; else status="FAIL(${rc})"; fi
  printf '  %-58s %s\n' "${nb}.ipynb" "$status" | tee -a "$LOG"
done

failures=0
while read -r nb rc; do
  [ "$rc" -eq 0 ] || failures=1
done < "$RESULTS"

banner
if [ "$failures" -eq 0 ]; then
  log "ALL DONE. Every notebook completed successfully."
else
  log "FAILURES detected. Failed job output:"
  while read -r nb rc; do
    if [ "$rc" -ne 0 ]; then
      log "----- tail of ${nb}.out -----"
      tail -n 40 "$NOTEBOOKS_DIR/${nb}.out" | sed 's/^/    /' | tee -a "$LOG"
    fi
  done < "$RESULTS"
fi
log "progress log: $LOG"
banner
exit "$failures"