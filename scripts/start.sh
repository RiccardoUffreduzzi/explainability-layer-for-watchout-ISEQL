#!/usr/bin/env bash
# scripts/start.sh - unified runner (PROFILE=local|hpc|hpc-slurm|docker|mac)
# local: auto-detects conda (anaconda3/miniconda3, or installs Miniconda3),
#        ensures conda py310 + ffmpeg, runs backend via pipenv.
# hpc:      backend on the GPU node via direct SSH (SSH tunnel), frontend on the login node.
# hpc-slurm: backend via Slurm sbatch (cuda partition), frontend on the login node.
# Usage: make {local,hpc,hpc-slurm} or PROFILE=local bash scripts/start.sh backend
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

PROFILE="${PROFILE:-}"
case "$PROFILE" in
  local|hpc|hpc-slurm|docker|mac) ;;
  "") echo "ERROR: PROFILE not set (use local|hpc|hpc-slurm|docker|mac)" >&2; exit 2 ;;
  *) echo "ERROR: invalid PROFILE='$PROFILE' (use local|hpc|hpc-slurm|docker|mac)" >&2; exit 2 ;;
esac

MODE="${1:-all}"
case "$MODE" in
  all|backend|frontend) ;;
  *) echo "ERROR: invalid mode='$MODE' (use all|backend|frontend)" >&2; exit 2 ;;
esac

BACKEND_JOBID_FILE="${BACKEND_JOBID_FILE:-$HOME/.cache/backend-slurm.jobid}"
BACKEND_SLURM="${BACKEND_SLURM:-$HERE/backend.slurm}"

# Direct-SSH target for PROFILE=hpc (flexible fallback when Slurm is broken).
# Defaults to compute-0-3 so `make hpc` works with zero config; override with
# BACKEND_HOST=<node> for other GPU nodes.
REMOTE_GPU="${BACKEND_HOST:-compute-0-3}"

# ---- conda bootstrap -------------------------------------------------------
CONDA_BASE=""

find_conda() {
  local candidates=(
    "$HOME/miniconda3" "$HOME/anaconda3" "$HOME/miniconda" "$HOME/anaconda"
    "${CONDA_EXE%/bin/*}" "${CONDA_PREFIX%/envs/*}"
  )
  for c in "${candidates[@]}"; do
    if [ -n "$c" ] && [ -x "$c/bin/conda" ]; then CONDA_BASE="$c"; return; fi
  done
  local cbin
  cbin="$(command -v conda 2>/dev/null || true)"
  if [ -n "$cbin" ]; then CONDA_BASE="$(dirname "$(dirname "$cbin")")"; fi
}

ensure_conda() {
  if [ -z "$CONDA_BASE" ]; then find_conda; fi
  if [ -z "$CONDA_BASE" ]; then
    echo ">> no conda found; installing Miniconda3 to $HOME/miniconda3"
    local url="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh"
    local inst="$HOME/miniconda3.sh"
    curl -fsSLo "$inst" "$url"
    bash "$inst" -b -p "$HOME/miniconda3"
    rm -f "$inst"
    CONDA_BASE="$HOME/miniconda3"
  fi
  echo ">> conda: $CONDA_BASE"
}

# conda env dir for the pipenv base python + ffmpeg libs
py310_env() { echo "$CONDA_BASE/envs/py310"; }

ensure_ffmpeg() {
  ensure_conda
  local env_dir py
  env_dir="$(py310_env)"
  py="$env_dir/bin/python"
  if [ ! -x "$py" ]; then
    echo ">> [backend] creating conda env $env_dir (python 3.10)..."
    "$CONDA_BASE/bin/conda" create -p "$env_dir" python=3.10 -y
  fi
  # torchaudio/torio needs FFmpeg 6 ABI (libavutil.so.58). conda-forge's
  # latest ffmpeg is 8.x (libavutil.so.60) which torio cannot load, so pin 6.
  if ! "$env_dir/bin/ffmpeg" -version 2>/dev/null | grep -q "^ffmpeg version 6"; then
    echo ">> [backend] installing ffmpeg 6.0.0 into $env_dir..."
    "$CONDA_BASE/bin/conda" install -p "$env_dir" -c conda-forge "ffmpeg=6.0.0" -y
  fi
  export PATH="$env_dir/bin:$PATH"
  export LD_LIBRARY_PATH="$env_dir/lib:${LD_LIBRARY_PATH:-}"
}

# macOS: ffmpeg via Homebrew (no conda/CUDA), matching the Pipfile.mac CPU deps.
ensure_ffmpeg_mac() {
  if command -v ffmpeg >/dev/null 2>&1; then
    echo ">> [backend] ffmpeg found: $(command -v ffmpeg)"
    return
  fi
  if command -v brew >/dev/null 2>&1; then
    echo ">> [backend] installing ffmpeg via Homebrew..."
    brew install ffmpeg
  else
    echo "ERROR: ffmpeg not found and Homebrew not available. Install ffmpeg (e.g. 'brew install ffmpeg')." >&2
    exit 2
  fi
}

hpc_job_id() { [ -f "$BACKEND_JOBID_FILE" ] && cat "$BACKEND_JOBID_FILE" 2>/dev/null || true; }
hpc_job_node() {
  local jid
  jid=$(hpc_job_id)
  [ -z "$jid" ] && return 1
  squeue -j "$jid" -h -o "%N" 2>/dev/null | head -n 1
}
# Next bigger MIG slice (dslow~1c < mid~2c < fast~4c < generic=max).
slice_up() {
  case "${1:-gpu:1}" in
    gpu:dslow:1) echo "gpu:mid:1" ;;
    gpu:mid:1) echo "gpu:fast:1" ;;
    *) echo "gpu:1" ;;
  esac
}
# Wake-proxy layout: clients (vite, zrok, you) always talk to :8000. The proxy
# holds :8000 permanently and pipes to the Slurm tunnel on :8001 when the job
# is up -- else it flags demand and holds/503s while the job wakes.
UPSTREAM_PORT=8001
NEED_FILE="$HOME/.cache/backend-wake.need"
SUPERVISE_PID_FILE="$HOME/.cache/backend-supervise.pid"
PROXY_MARK="backend-wake-proxy"
PROXY_LOG="$HOME/.cache/backend-proxy.log"
# Seconds a first connection waits for the GPU job before getting 503+Retry.
WAKE_HOLD_SECS="${WAKE_HOLD_SECS:-180}"
# Double a Slurm --mem value (64G->128G), cap 256G.
_double_mem() {
  local m="${1:-64G}" num mb
  num=$(echo "$m" | grep -oiE '[0-9]+' | head -n 1); num=${num:-64}
  if [[ "$m" =~ [Mm]$ ]]; then mb=$(( num * 2 )); else mb=$(( num * 2048 )); fi
  [ "$mb" -gt 262144 ] && mb=262144
  if [[ "$m" =~ [Mm]$ ]]; then echo "${mb}M"; else echo "$(( mb / 1024 ))G"; fi
}
# Wake proxy: holds :8000 forever, pipes to :UPSTREAM_PORT when the job is
# up, else flags demand (NEED file) and holds/503s while it wakes.
# Embedded here so the service stays one file; quoted heredoc = byte-identical.
proxy_alive() { pgrep -f "$PROXY_MARK" >/dev/null 2>&1; }

proxy_up() {
  if proxy_alive; then return 0; fi
  if (ss -tln 2>/dev/null | grep -q ":8000 ") && ! proxy_alive; then
    pkill -f "ssh.*-L 8000:localhost:8000" 2>/dev/null || true
    sleep 1
  fi
  WAKE_HOLD_SECS="$WAKE_HOLD_SECS" nohup python3 - "8000" "$UPSTREAM_PORT" "$NEED_FILE" "$PROXY_MARK" <<'PYEOF' >"$PROXY_LOG" 2>&1 &
import socket, threading, sys, os, time
LPORT, UPORT, NEED = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
HOLD = int(os.environ.get("WAKE_HOLD_SECS", "180"))
def upstream_ok():
    try:
        s = socket.create_connection(("127.0.0.1", UPORT), timeout=3)
        s.close()
        return True
    except OSError:
        return False
def handle(c):
    try:
        if not upstream_ok():
            # Level-triggered demand: touch on EVERY connection while down,
            # so a wake-up can never be lost no matter who consumed the flag.
            # (Health polls count as demand too -- an open frontend means a user.)
            open(NEED, "a").close()
            try:
                c.settimeout(3)
                head = c.recv(4096, socket.MSG_PEEK)
            except OSError:
                head = b""
            finally:
                try:
                    c.settimeout(None)
                except OSError:
                    pass
            # Real API calls hold for the wake; health polls fail fast so
            # waiting UIs keep polling instead of hanging.
            if b"/api/health" not in head:
                t0 = time.time()
                while time.time() - t0 < HOLD:
                    if upstream_ok():
                        break
                    time.sleep(2)
            if not upstream_ok():
                try:
                    c.sendall(b"HTTP/1.1 503 Service Unavailable\r\nRetry-After: 30\r\nContent-Length: 20\r\nConnection: close\r\n\r\nwaking gpu job...\n")
                except OSError:
                    pass
                try:
                    c.close()
                except OSError:
                    pass
                return
        u = socket.create_connection(("127.0.0.1", UPORT), timeout=10)
        def fwd(a, b):
            try:
                while True:
                    d = a.recv(65536)
                    if not d:
                        break
                    b.sendall(d)
            except OSError:
                pass
            finally:
                try:
                    b.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
        t = threading.Thread(target=fwd, args=(u, c), daemon=True)
        t.start()
        fwd(c, u)
    except OSError:
        try:
            c.close()
        except OSError:
            pass
srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", LPORT))
srv.listen(64)
while True:
    c, _ = srv.accept()
    threading.Thread(target=handle, args=(c,), daemon=True).start()
PYEOF
  echo $! > "$HOME/.cache/backend-proxy.pid"
  sleep 1
  proxy_alive || { echo ">> [backend] proxy failed to start -- tail $PROXY_LOG" >&2; return 1; }
  echo ">> [backend] proxy holding :8000 -> :$UPSTREAM_PORT"
}

proxy_down() {
  pkill -f "$PROXY_MARK" 2>/dev/null || true
  rm -f "$HOME/.cache/backend-proxy.pid"
}
# Mutual idempotency: `hpc` and `hpc-slurm` share local :8000 (and possibly the
# same GPU node remote :8000), so starting one must stop the other's backend
# side first. Frontend (:5173) is shared and left alone.
stop_slurm_side() {
  echo ">> [backend] stopping any hpc-slurm side (proxy/job/tunnel)..."
  if [ -f "$SUPERVISE_PID_FILE" ]; then
    _spid=$(cat "$SUPERVISE_PID_FILE" 2>/dev/null || true)
    if [ -n "$_spid" ] && [ "$_spid" != "$$" ]; then kill "$_spid" 2>/dev/null || true; fi
    rm -f "$SUPERVISE_PID_FILE"
  fi
  proxy_down 2>/dev/null || true
  pkill -f "ssh.*-L $UPSTREAM_PORT:localhost:8000" 2>/dev/null || true
  local _jid
  _jid=$(hpc_job_id || true)
  if [ -n "$_jid" ]; then scancel "$_jid" 2>/dev/null || true; rm -f "$BACKEND_JOBID_FILE"; echo ">> [backend] Slurm job $_jid cancelled"; fi
  rm -f "$NEED_FILE"
}
stop_ssh_side() {
  echo ">> [backend] stopping any hpc (direct-SSH) side (tunnel/remote uvicorn)..."
  pkill -f "ssh.*-L 8000:localhost:8000" 2>/dev/null || true
  ssh -o BatchMode=yes -o ConnectTimeout=5 "$REMOTE_GPU" "pkill -f 'uvicorn.*8000' 2>/dev/null || true" 2>/dev/null || true
  pkill -f "uvicorn.*8000" 2>/dev/null || true
  sleep 1
}
# Non-health API hits in a uvicorn stdout log (health probes excluded so the
# watch itself never counts as activity).
backend_traffic() {
  local log="${1:-}" total probes
  [ -f "$log" ] || { echo 0; return 0; }
  total=$(grep -acE '"(GET|POST|PUT|DELETE) /api/' "$log" 2>/dev/null || true)
  probes=$(grep -acE '"(GET|POST|PUT|DELETE) /api/health' "$log" 2>/dev/null || true)
  echo $(( ${total:-0} - ${probes:-0} ))
}
# Supervisor: NEED file -> ensure job; dead job stays dead until demanded
# (any live user re-creates NEED via the :8000 proxy); live-but-idle job is
# released after IDLE_STOP_MINS. Runs forever until killed by the trap.
backend_supervise() {
  local interval=15 idle_secs idle_since now cur last log jid st
  idle_secs=$(( ${IDLE_STOP_MINS:-30} * 60 ))
  idle_since=$(date +%s)
  jid=$(hpc_job_id || true)
  last=$(backend_traffic "$ROOT/backend/backend-$jid.out")
  while true; do
    sleep "$interval"
    if [ -f "$NEED_FILE" ]; then
      echo ">> [backend] wake requested -- ensuring job..."
      if backend_ensure; then
        rm -f "$NEED_FILE"
      else
        echo ">> [backend] ensure failed -- keeping demand, retry in 60s..."
      fi
      jid=$(hpc_job_id || true)
      idle_since=$(date +%s)
      last=$(backend_traffic "$ROOT/backend/backend-$jid.out")
      continue
    fi
    jid=$(hpc_job_id || true)
    if [ -z "$jid" ]; then idle_since=$(date +%s); continue; fi
    st=$(squeue -j "$jid" -h -o "%T" 2>/dev/null | head -n 1 || true)
    if [ -z "$st" ]; then idle_since=$(date +%s); continue; fi
    if [ "$st" = "RUNNING" ]; then
      if ! pgrep -f "ssh.*-L $UPSTREAM_PORT:localhost:8000" >/dev/null 2>&1 \
        || ! curl -s --max-time 5 http://127.0.0.1:$UPSTREAM_PORT/api/health 2>/dev/null | grep -q '"status":"ok"'; then
        _node=$(hpc_job_node || true)
        if [ -n "$_node" ]; then
          echo ">> [backend] tunnel down, re-dialing $_node..."
          pkill -f "ssh.*-L $UPSTREAM_PORT:localhost:8000" 2>/dev/null || true
          ssh -o BatchMode=yes -f -N -L $UPSTREAM_PORT:localhost:8000 "$_node" 2>/dev/null || true
        fi
      fi
    fi
    if [ "$idle_secs" -le 0 ]; then continue; fi
    log="$ROOT/backend/backend-$jid.out"
    cur=$(backend_traffic "$log")
    if [ "$cur" != "$last" ]; then idle_since=$(date +%s); last="$cur"; continue; fi
    now=$(date +%s)
    if [ $(( now - idle_since )) -ge "$idle_secs" ]; then
      echo ">> [backend] idle ${IDLE_STOP_MINS:-30}m (no API traffic) -- releasing GPU slice (job $jid)..."
      scancel "$jid" 2>/dev/null || true
      rm -f "$BACKEND_JOBID_FILE"
      pkill -f "ssh.*-L $UPSTREAM_PORT:localhost:8000" 2>/dev/null || true
      idle_since=$(date +%s)
    fi
  done
}

cleanup() {
  trap - INT TERM EXIT
  if [[ "$PROFILE" == "hpc-slurm" ]]; then
    [[ -n "${TUNNEL_PID:-}" ]] && kill -0 "$TUNNEL_PID" 2>/dev/null && kill "$TUNNEL_PID" 2>/dev/null || true
    [[ -n "${SUPERVISE_PID:-}" ]] && kill -0 "$SUPERVISE_PID" 2>/dev/null && kill "$SUPERVISE_PID" 2>/dev/null || true
    rm -f "$SUPERVISE_PID_FILE"
    proxy_down 2>/dev/null || true
    local _jid
    _jid=$(hpc_job_id || true)
    if [ -n "$_jid" ]; then scancel "$_jid" 2>/dev/null || true; rm -f "$BACKEND_JOBID_FILE"; fi
  elif [[ "$PROFILE" == "hpc" ]]; then
    [[ -n "${TUNNEL_PID:-}" ]] && kill -0 "$TUNNEL_PID" 2>/dev/null && kill "$TUNNEL_PID" 2>/dev/null || true
    ssh -o BatchMode=yes "$REMOTE_GPU" "pkill -f 'uvicorn.*8000' 2>/dev/null || true" 2>/dev/null || true
  else
    [[ -n "${BACK_PID:-}" ]] && kill -0 "$BACK_PID" 2>/dev/null && kill "$BACK_PID" 2>/dev/null || true
  fi
  [[ -n "${FRONT_PID:-}" ]] && kill -0 "$FRONT_PID" 2>/dev/null && kill "$FRONT_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  echo ""; echo ">> WATCHOUT ISEQL ($PROFILE) stopped."
}
trap cleanup INT TERM EXIT

# One-shot: ensure a live healthy backend (submit + wait + tunnel + health).
# Sizes from E_MEM/E_GRES globals (set by caller; OOM regrows mutate them so
# later ensures inherit the growth). TUNNEL_PID is global. Returns 0 on ready.
backend_ensure() {
  local _jid _node _st _wait_n _backend_ok _h _healthy _attempt _oom _next
  _jid=$(hpc_job_id || true)
  if [ -n "$_jid" ]; then
    _st=$(squeue -j "$_jid" -h -o "%T" 2>/dev/null | head -n 1 || true)
    if [ -z "$_st" ]; then echo ">> [backend] stale job $_jid gone, resubmitting..."; rm -f "$BACKEND_JOBID_FILE"; _jid=""; fi
  fi
  for _attempt in 1 2 3; do
  if [ -z "$_jid" ]; then
    echo ">> [backend] submitting $BACKEND_SLURM to cuda (--gres=$E_GRES --mem=$E_MEM, attempt $_attempt)..."
    _ollama_url=""
    _ollama_jid_file="$HOME/.cache/ollama-slurm.jobid"
    if [ -f "$_ollama_jid_file" ]; then
      _ojid=$(cat "$_ollama_jid_file" 2>/dev/null || true)
      _onode=$(squeue -j "$_ojid" -h -o "%N" 2>/dev/null | head -n 1 || true)
      if [ -n "$_onode" ]; then _ollama_url="http://$_onode:11434"; fi
    fi
    if [ -n "$_ollama_url" ]; then
      echo ">> [backend] OLLAMA_BASE_URL=$_ollama_url"
      _jid=$(sbatch --parsable --gres="$E_GRES" --mem="$E_MEM" --export=ALL,OLLAMA_BASE_URL="$_ollama_url" "$BACKEND_SLURM" 2>&1 | tail -n 1)
    else
      _jid=$(sbatch --parsable --gres="$E_GRES" --mem="$E_MEM" "$BACKEND_SLURM" 2>&1 | tail -n 1)
    fi
    if ! [[ "$_jid" =~ ^[0-9]+$ ]]; then
      echo ">> [backend] sbatch failed: $_jid" >&2
      return 1
    fi
    echo "$_jid" > "$BACKEND_JOBID_FILE"
    echo ">> [backend] job $_jid submitted"
  fi
  echo ">> [backend] waiting for job $_jid RUNNING (Ctrl-C aborts; slices free up when others stop)..."
  _wait_n=0; _backend_ok=0
  while true; do
    _st=$(squeue -j "$_jid" -h -o "%T" 2>/dev/null | head -n 1 || true)
    if [ "$_st" = "RUNNING" ]; then _backend_ok=1; break; fi
    if [ -z "$_st" ]; then
      echo ">> [backend] job $_jid gone -- tail backend-$_jid.out" >&2
      _oom=$(grep -aiE "out ?of ?memory|oom|memoryerror|cuda oom|killed|failed to allocate" "backend-$_jid.out" 2>/dev/null | head -n 5 || true)
      if [ "$_attempt" -lt 3 ] && [ -n "$_oom" ]; then
        echo "$_oom" | head -n 3 >&2
        if echo "$_oom" | grep -aiqE "cuda|vram|gpu|cublas"; then
          _next=$(slice_up "$E_GRES")
          if [ "$_next" != "$E_GRES" ]; then
            echo ">> [backend] VRAM OOM -- moving slice $E_GRES -> $_next..."
            E_GRES="$_next"
          else
            echo ">> [backend] VRAM OOM on biggest slice -- doubling --mem instead..."
            E_MEM=$(_double_mem "$E_MEM")
          fi
        else
          E_MEM=$(_double_mem "$E_MEM")
          echo ">> [backend] host OOM -- regrowing to --mem=$E_MEM..."
        fi
        rm -f "$BACKEND_JOBID_FILE"; _jid=""
        continue 2
      fi
      rm -f "$BACKEND_JOBID_FILE"; break 2
    fi
    _wait_n=$((_wait_n + 1))
    if [ $(( _wait_n % 8 )) -eq 0 ]; then
      echo ">> [backend] still waiting ($(( _wait_n * 4 ))s): $(squeue -j "$_jid" -h -o "%T %R" 2>/dev/null | head -n 1 || echo job gone)"
    fi
    sleep 4
  done
  break
  done
  if [ "$_backend_ok" != "1" ]; then
    echo ">> [backend] FAILED to reach RUNNING (fix: free a GPU slice, then retry)" >&2
    return 1
  fi
  _node=$(hpc_job_node || true)
  echo ">> [backend] job $_jid on ${_node:-unknown}"
  pkill -f "ssh.*-L $UPSTREAM_PORT:localhost:8000" 2>/dev/null || true
  sleep 1
  ssh -o BatchMode=yes -f -N -L $UPSTREAM_PORT:localhost:8000 "$_node" 2>/dev/null || true
  TUNNEL_PID=$(pgrep -f "ssh.*-L $UPSTREAM_PORT:localhost:8000.*$_node" | tail -1 || true)
  sleep 3
  echo ">> [backend] waiting for /api/health (job up, uvicorn still booting)..."
  _healthy=0
  for _h in $(seq 1 36); do
    if curl -s --max-time 5 http://127.0.0.1:$UPSTREAM_PORT/api/health 2>/dev/null | grep -q '"status":"ok"'; then _healthy=1; break; fi
    sleep 5
  done
  if [ "$_healthy" != "1" ]; then
    echo ">> [backend] tunnel up but API never healthy (ssh $_node tail backend log)" >&2
    return 1
  fi
  echo ">> [backend] remote ready"
  rm -f "$NEED_FILE"
  return 0
}

run_backend() {
  case "$PROFILE" in
    hpc)
      stop_slurm_side
      ensure_ffmpeg
      cd "$ROOT/backend"
      echo ">> [backend] installing deps if needed..."
      pipenv sync --dev --quiet 2>/dev/null || true
      echo ">> [backend] starting on $REMOTE_GPU..."
      # clear any stale tunnel + remote backend left by a previous run (ssh -f
      # double-forks and can survive Ctrl-C), otherwise :8000 is held or points
      # at a dead backend -> ECONNRESET from the vite proxy.
      pkill -f "ssh.*-L 8000:localhost:8000" 2>/dev/null || true
      ssh -o BatchMode=yes "$REMOTE_GPU" "pkill -f 'uvicorn.*8000' 2>/dev/null; sleep 1" 2>/dev/null || true
      sleep 1
      ssh -o BatchMode=yes -f -N -L 8000:localhost:8000 "$REMOTE_GPU" 2>/dev/null || true
      TUNNEL_PID=$(pgrep -f "ssh.*-L 8000:localhost:8000.*$REMOTE_GPU" | tail -1 || true)
      REMOTE_ENV="$CONDA_BASE/envs/py310"
      ssh -o BatchMode=yes "$REMOTE_GPU" "cd $ROOT/backend && PATH=$REMOTE_ENV/bin:\$PATH LD_LIBRARY_PATH=$REMOTE_ENV/lib:\${LD_LIBRARY_PATH:-} PROFILE=hpc PYTHONPATH=src pipenv run uvicorn start_application:StartApplication --host 0.0.0.0 --port 8000 --reload" &
      sleep 3
      curl -s --max-time 5 http://127.0.0.1:8000/api/health >/dev/null 2>&1 && echo ">> [backend] remote ready" || echo ">> [backend] remote starting..."
      ;;
    hpc-slurm)
      stop_ssh_side
      ensure_ffmpeg
      cd "$ROOT/backend"
      echo ">> [backend] installing deps if needed..."
      pipenv sync --dev --quiet 2>/dev/null || true
      # Slurm-native: proxy holds :8000; one sbatch job per backend behind it.
      proxy_up || return 1
      # Job RAM: BACKEND_MEM= (or MEM=), default 64G. GPU VRAM is --gres.
      # GPU slice: BACKEND_GRES= pins it (default gpu:1 = any free MIG slice).
      # OOM regrows + idle release happen inside backend_ensure/supervise.
      E_MEM="${BACKEND_MEM:-${MEM:-64G}}"
      E_GRES="${BACKEND_GRES:-${GRES:-gpu:1}}"
      backend_ensure || { echo ">> [backend] FAILED -- frontend NOT started" >&2; return 1; }
      rm -f "$NEED_FILE"
      if [ "${IDLE_STOP_MINS:-30}" != "0" ]; then
        backend_supervise &
        SUPERVISE_PID=$!
        echo "$SUPERVISE_PID" > "$SUPERVISE_PID_FILE"
        echo ">> [backend] supervise armed (wake-on-demand + ${IDLE_STOP_MINS:-30}m idle-release, pid $SUPERVISE_PID; 0 disables)"
      fi
      ;;
    local)
      ensure_ffmpeg
      cd "$ROOT/backend"
      echo ">> [backend] installing deps if needed..."
      pipenv --python "$(py310_env)/bin/python" sync --dev --quiet 2>/dev/null || true
      if [ -f "$ROOT/backend/.env" ]; then set -a; source "$ROOT/backend/.env"; set +a; fi
      echo ">> [backend] starting uvicorn (pipenv)..."
      # idempotent: clear a stray backend from a previous run so :8000 is free
      pkill -f "uvicorn.*8000" 2>/dev/null || true
      sleep 1
      PYTHONPATH=src pipenv run uvicorn start_application:StartApplication --host 0.0.0.0 --port 8000 --reload &
      BACK_PID=$!
      ;;
    mac)
      ensure_ffmpeg_mac
      cd "$ROOT/backend"
      echo ">> [backend] installing deps if needed (Pipfile.mac, CPU)..."
      export PIPENV_PIPFILE=Pipfile.mac
      pipenv install --dev --quiet 2>/dev/null || true
      if [ -f "$ROOT/backend/.env" ]; then set -a; source "$ROOT/backend/.env"; set +a; fi
      echo ">> [backend] starting uvicorn (pipenv, macOS)..."
      pkill -f "uvicorn.*8000" 2>/dev/null || true
      sleep 1
      PYTHONPATH=src pipenv run uvicorn start_application:StartApplication --host 0.0.0.0 --port 8000 --reload &
      BACK_PID=$!
      ;;
  esac
}

run_frontend() {
  cd "$ROOT/frontend"
  echo ">> [frontend] starting vite dev..."
  # idempotent: clear a stray vite from a previous run so :5173 is free
  pkill -f "vite.*5173" 2>/dev/null || true
  sleep 1
  export PUBLIC_PROFILE="$PROFILE"
  pnpm dev --host 0.0.0.0 --port 5173 &
  FRONT_PID=$!
}

case "$MODE" in
  backend)
    run_backend
    echo ">> Backend http://localhost:8000 [$PROFILE]"
    wait
    ;;
  frontend)
    run_frontend
    echo ">> Frontend http://localhost:5173 [$PROFILE]"
    wait
    ;;
  *)
    if [[ "$PROFILE" == "hpc" ]]; then
      echo ">> Starting WATCHOUT ISEQL (hpc)"; echo "   Backend  -> http://localhost:8000 (via $REMOTE_GPU:8000)"; echo "   Frontend -> http://localhost:5173"
    elif [[ "$PROFILE" == "hpc-slurm" ]]; then
      echo ">> Starting WATCHOUT ISEQL (hpc-slurm)"; echo "   Backend  -> http://localhost:8000 (via Slurm job $(hpc_job_id || echo pending))"; echo "   Frontend -> http://localhost:5173"
    else
      echo ">> Starting WATCHOUT ISEQL (local)"; echo "   Backend  -> http://localhost:8000 (conda py310 + pipenv)"; echo "   Frontend -> http://localhost:5173"
    fi
    run_backend; run_frontend
    echo ">> Both running. Ctrl-C to stop."
    wait
    ;;
esac
