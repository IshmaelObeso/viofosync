#!/usr/bin/env bash
set -eu

# Build up the common flags
flags=()

# keep
[ -n "${KEEP:-}" ] && flags+=( --keep "$KEEP" )

# grouping
[ -n "${GROUPING:-}" ] && flags+=( --grouping "$GROUPING" )

# priority
[ -n "${PRIORITY:-}" ] && flags+=( --priority "$PRIORITY" )

# max disk usage
[ -n "${MAX_USED_DISK:-}" ] && flags+=( --max-used-disk "$MAX_USED_DISK" )

# timeout
[ -n "${TIMEOUT:-}" ] && flags+=( --timeout "$TIMEOUT" )

# verbosity
if [ "${VERBOSE:-0}" -gt 0 ]; then
  for i in $(seq 1 "$VERBOSE"); do
    flags+=( --verbose )
  done
fi

# quiet
[ -n "${QUIET:-}" ] && flags+=( --quiet )

# dry-run
[ -n "${DRY_RUN:-}" ] && flags+=( --dry-run )

# gps extract
[ -n "${GPS_EXTRACT:-}" ] && flags+=( --gps-extract )

# run-once vs monitor
if [ -n "${RUN_ONCE:-}" ]; then
  flags+=( --run-once )
else
  flags+=( --monitor )
fi

# finally exec the Python script
exec python3 /viofosync.py \
     "$ADDRESS" \
     --destination /recordings \
     "${flags[@]}"
