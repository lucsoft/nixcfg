#!/usr/bin/env bash
# A/B benchmark for the `cachy` specialisation in performance.nix.
#
#   ./bench.sh          run the suite, tagged with whichever entry booted
#   ./bench.sh compare  newest baseline run vs newest cachy run
#
# Both boot entries share one userland, so a delta has one possible cause.
# Takes ~4 minutes and pins every core; run it on an idle machine.

set -euo pipefail

REV="cf9d2fb3e50fa1cd5114c47505ea9177f7ff5f49"
NIXPKGS="https://github.com/NixOS/nixpkgs/archive/${REV}.tar.gz"
RESULTS="$(dirname "$(readlink -f "$0")")/bench-results"

# Tools come from the system's pinned nixpkgs, so they match on both sides.
if [ -z "${BENCH_IN_SHELL:-}" ]; then
  export BENCH_IN_SHELL=1
  exec nix-shell -I "nixpkgs=${NIXPKGS}" \
    -p stress-ng hyperfine fio jq bc \
    --run "exec $(printf '%q' "$(readlink -f "$0")") $(printf '%q ' "$@")"
fi

PROFILE="$(cat /etc/bench-profile 2>/dev/null || echo unknown)"
PROFILE="${PROFILE%%[[:space:]]*}"
NCPU="$(nproc)"

# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------
if [ "${1:-run}" = "compare" ]; then
  a="$(ls -t "$RESULTS"/baseline-* 2>/dev/null | head -1 || true)"
  b="$(ls -t "$RESULTS"/cachy-* 2>/dev/null | head -1 || true)"
  if [ -z "$a" ] || [ -z "$b" ]; then
    echo "Need one run from each profile. Have:" >&2
    ls "$RESULTS" 2>/dev/null >&2 || echo "  (no results yet)" >&2
    exit 1
  fi
  echo "baseline: $(basename "$a")"
  echo "cachy:    $(basename "$b")"
  echo
  printf '%-40s %14s %14s %12s\n' METRIC BASELINE CACHY DELTA
  printf '%-40s %14s %14s %12s\n' \
    '----------------------------------------' '--------------' '--------------' '------------'
  # Lines are "key<TAB>value<TAB>unit<TAB>direction", direction being which
  # way counts as an improvement.
  join -t$'\t' -j1 \
      <(grep -v '^#' "$a" | sort -t$'\t' -k1,1) \
      <(grep -v '^#' "$b" | sort -t$'\t' -k1,1) \
    | awk -F'\t' '{
        key=$1; av=$2+0; unit=$3; dir=$4; bv=$5+0;
        if (av == 0) { pct="n/a" } else {
          d=(bv-av)/av*100;
          better=(dir=="lower") ? (d<0) : (d>0);
          mark=(d>-0.05 && d<0.05) ? "" : (better ? " +" : " -");
          pct=sprintf("%+.1f%%%s", d, mark);
        }
        printf "%-40s %14.2f %14.2f %12s\n", key" ("unit")", av, bv, pct;
      }'
  echo
  echo '"+" means the metric moved the better way for its kind. Read the'
  echo 'control.* rows first: the tuning does not touch them, so if they'
  echo 'moved the run was noisy. Below ~2%, assume noise.'
  exit 0
fi

# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------
mkdir -p "$RESULTS"
OUT="$RESULTS/${PROFILE}-$(date +%Y%m%d-%H%M%S).tsv"
TMP="$(mktemp -d)"
cleanup() { pkill -P $$ stress-ng 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT

emit() { printf '%s\t%s\t%s\t%s\n' "$1" "${2:-0}" "$3" "$4" >> "$OUT"; }

# bogo ops/sec from a stress-ng metrics line. Matching the name on $4 matters:
# a bare /cpu / also hits the "passed: 1: cpu (1)" summary and reads garbage.
bogo() { awk -v want="$1" '$2=="metrc:" && $4==want {print $(NF-1)}' | tail -1; }

{
  echo "# profile:    $PROFILE"
  echo "# date:       $(date -Is)"
  echo "# kernel:     $(uname -r)"
  echo "# system:     $(readlink -f /run/current-system)"
  echo "# sched_ext:  $(cat /sys/kernel/sched_ext/state 2>/dev/null || echo none)"
  echo "# preempt:    $(grep -o 'preempt=[a-z]*' /proc/cmdline || echo '(default)')"
  echo "# swap:       $(awk 'NR>1{printf "%s:%dMB ", $1, $3/1024}' /proc/swaps || true)"
  echo "# swappiness: $(sysctl -n vm.swappiness)"
} > "$OUT"

echo "profile: $PROFILE  ->  $OUT"
echo

# --- 1. Control: the tuning touches neither of these ------------------------
echo "[1/5] control: single-thread CPU + disk (should NOT change)"
emit control.cpu1_bogo_ops_sec \
  "$(stress-ng --cpu 1 --cpu-method matrixprod --metrics-brief -t 15s 2>&1 | bogo cpu)" \
  ops/s higher

fio --name=ctl --directory="$TMP" --size=512M --rw=randread --bs=4k \
    --ioengine=io_uring --iodepth=32 --direct=1 --runtime=15 --time_based \
    --output-format=json --output="$TMP/fio.json" >/dev/null 2>&1 || true
emit control.disk_randread_iops \
  "$(jq -r '.jobs[0].read.iops // 0' "$TMP/fio.json" 2>/dev/null || echo 0)" \
  iops higher

# --- 2. How long a new task waits for a CPU under contention ----------------
echo "[2/5] foreground latency under ${NCPU}-way CPU load (~80s)"
stress-ng --cpu "$NCPU" --cpu-method matrixprod -t 80s >/dev/null 2>&1 &
load=$!
sleep 5
hyperfine --warmup 20 --runs 300 --style none \
          --export-json "$TMP/lat.json" -N -- 'true' >/dev/null 2>&1 || true
kill "$load" 2>/dev/null || true; wait "$load" 2>/dev/null || true
if [ -s "$TMP/lat.json" ]; then
  emit latency.spawn_mean   "$(jq -r '.results[0].mean*1000'   "$TMP/lat.json")" ms lower
  emit latency.spawn_stddev "$(jq -r '.results[0].stddev*1000' "$TMP/lat.json")" ms lower
  emit latency.spawn_max    "$(jq -r '.results[0].max*1000'    "$TMP/lat.json")" ms lower
fi

# --- 3. Wakeup latency; the tail is what a dropped frame feels like ---------
echo "[3/5] wakeup latency percentiles under load (~40s)"
stress-ng --cpu "$NCPU" --cpu-method matrixprod -t 40s >/dev/null 2>&1 &
load=$!
sleep 3
# --cyclic-samples must be raised or the percentile table comes out empty:
# the default 10000-slot buffer overflows within seconds.
stress-ng --cyclic 1 --cyclic-policy other --cyclic-samples 100000 \
          -t 30s > "$TMP/cyc.txt" 2>&1 || true
kill "$load" 2>/dev/null || true; wait "$load" 2>/dev/null || true

while read -r label key; do
  v=$(grep -oP "cyclic:\s+${label}%:\s+\K[0-9]+" "$TMP/cyc.txt" | tail -1 || true)
  [ -n "${v:-}" ] && emit "latency.cyclic_${key}" "$v" ns lower || true
done <<'PCT'
50.00 p50
99.00 p99
99.90 p999
PCT
v=$(grep -oP 'cyclic:\s+mean:\s+\K[0-9.]+' "$TMP/cyc.txt" | tail -1 || true)
[ -n "${v:-}" ] && emit latency.cyclic_mean "$v" ns lower || true
v=$(grep -oP 'cyclic:\s+min:.*?max:\s+\K[0-9]+' "$TMP/cyc.txt" | tail -1 || true)
[ -n "${v:-}" ] && emit latency.cyclic_max "$v" ns lower || true

# --- 4. The bill for any latency won by switching more often ----------------
echo "[4/5] all-core throughput (~45s)"
emit throughput.matrix_bogo_ops_sec \
  "$(stress-ng --matrix "$NCPU" --metrics-brief -t 30s 2>&1 | bogo matrix)" \
  ops/s higher
emit throughput.ctxswitch_bogo_ops_sec \
  "$(stress-ng --switch "$NCPU" --metrics-brief -t 15s 2>&1 | bogo switch)" \
  ops/s higher

# --- 5. The zram half. 60% of RAM: leans on reclaim, stays clear of the OOM
#        killer taking out the desktop session.
echo "[5/5] memory pressure (~25s)"
mb=$(( $(awk '/MemTotal/{print $2}' /proc/meminfo) / 1024 * 60 / 100 ))
start=$(date +%s.%N)
stress-ng --vm 4 --vm-bytes "$((mb / 4))M" --vm-method flip \
          --vm-keep -t 20s >/dev/null 2>&1 || true
end=$(date +%s.%N)
emit memory.pressure_walltime "$(echo "$end - $start" | bc)" s lower
emit memory.swap_used_kb "$(awk 'NR>1{s+=$4} END{print s+0}' /proc/swaps)" kB higher

echo
echo "done -> $OUT"
echo
grep -v '^#' "$OUT" | column -t -s$'\t'
echo
echo "Now reboot into the other entry, run this again, then: ./bench.sh compare"
