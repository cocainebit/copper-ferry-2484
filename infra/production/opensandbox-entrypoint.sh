#!/bin/sh
set -eu
: "${OPENSANDBOX_SERVER_API_KEY:?A strong OpenSandbox API key is required}"
[ "${#OPENSANDBOX_SERVER_API_KEY}" -ge 32 ] || { echo 'OpenSandbox key must contain at least 32 characters' >&2; exit 1; }
[ -f /isolation/firewall-ready ] || { echo 'Apply and verify the dedicated Linux host firewall first' >&2; exit 1; }
exec opensandbox-server --config /etc/opensandbox/config.toml
