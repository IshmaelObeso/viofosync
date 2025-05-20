#!/usr/bin/env bash
set -eux

docker run --rm -it \
  --name viofosync \
  -e ADDRESS=127.0.0.2 \
  -e PUID="$(id -u)" \
  -e PGID="$(id -g)" \
  -e VERBOSE=1 \
  -e DRY_RUN=1 \
  -e RUN_ONCE=1 \
  -v "$(pwd)/tmp":/recordings:rw \
  robxyz/viofosync:latest
