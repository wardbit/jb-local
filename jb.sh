#!/usr/bin/env bash
set -eu
script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' 'Python 3.9+ is required. Install Python, then run this script again.' >&2
    exit 1
fi
exec python3 "$script_dir/jb.py" "$@"
