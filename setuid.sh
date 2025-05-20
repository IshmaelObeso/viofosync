#!/usr/bin/env bash

if [[ ${PUID:-0} -gt 0 ]]; then
    usermod -o -u "$PUID" dashcam
fi

if [[ ${PGID:-0} -gt 0 ]]; then
    groupmod -o -g "$PGID" dashcam
fi
