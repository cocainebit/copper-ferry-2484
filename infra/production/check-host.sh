#!/usr/bin/env bash
set -euo pipefail
[[ $(uname -s) == Linux ]] || { echo 'Production runtime requires a dedicated Linux host' >&2; exit 1; }
[[ ${PRODUCTION_ISOLATION_ACK:-} == reviewed ]] || { echo 'Review docs/PRODUCTION_RUNTIME.md, then set PRODUCTION_ISOLATION_ACK=reviewed' >&2; exit 1; }
docker info --format '{{json .Runtimes}}' | python3 -c 'import json,sys; assert "runsc" in json.load(sys.stdin), "gVisor runsc runtime is missing"'
bash "$(dirname "$0")/firewall.sh" --check
printf '%s\n' 'Runtime and firewall preflight passed. Quotas, backup restore and tenant penetration checks remain separate launch gates.'
