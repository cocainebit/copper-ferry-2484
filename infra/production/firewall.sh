#!/usr/bin/env bash
# Dedicated Linux Docker host only. Does not flush or change unrelated chains.
set -euo pipefail
mode=${1:---check}
[[ $(uname -s) == Linux && $EUID == 0 ]] || { echo 'Requires root on the dedicated Linux host' >&2; exit 1; }
[[ $mode == --apply || $mode == --check ]] || { echo 'Usage: firewall.sh --apply|--check' >&2; exit 1; }
bridge=br-ad-sbx
manager=172.30.0.2
for program in iptables ip6tables docker sysctl rg; do command -v "$program" >/dev/null; done
[[ $(sysctl -n net.bridge.bridge-nf-call-iptables) == 1 ]] || { echo 'Enable br_netfilter and bridge-nf-call-iptables before starting desktops' >&2; exit 1; }
[[ $(sysctl -n net.bridge.bridge-nf-call-ip6tables) == 1 ]] || { echo 'Enable bridge-nf-call-ip6tables before starting desktops' >&2; exit 1; }
docker network inspect agent-desktop-sandboxes --format '{{ index .Options "com.docker.network.bridge.name" }}' | rg -qx "$bridge"
[[ $(docker network inspect agent-desktop-sandboxes --format '{{ (index .IPAM.Config 0).Subnet }}') == 172.30.0.0/24 ]] || { echo 'Unexpected sandbox subnet' >&2; exit 1; }
iptables -w -S DOCKER-USER >/dev/null
# All rules are appended to our own chains and verified idempotently. No global flush.
chain() { local tool=$1 name=$2; if ! "$tool" -w -S "$name" >/dev/null 2>&1; then [[ $mode == --apply ]] && "$tool" -w -N "$name"; fi; }
rule() { local tool=$1 name=$2; shift 2; if ! "$tool" -w -C "$name" "$@" 2>/dev/null; then [[ $mode == --apply ]] && "$tool" -w -A "$name" "$@"; fi; }
jump() { local tool=$1 from=$2 to=$3; if ! "$tool" -w -C "$from" -j "$to" 2>/dev/null; then [[ $mode == --apply ]] && "$tool" -w -I "$from" 1 -j "$to"; fi; }
chain iptables AD-SANDBOX
chain iptables AD-SANDBOX-HOST
chain ip6tables AD-SANDBOX6
chain ip6tables AD-SANDBOX6-HOST
# Return traffic for connections initiated by trusted control plane or sandbox public egress.
rule iptables AD-SANDBOX -i "$bridge" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
rule iptables AD-SANDBOX -o "$bridge" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
# The sandbox manager has this explicitly reserved address. Tenants cannot set network addresses.
rule iptables AD-SANDBOX -i "$bridge" -s "$manager" -o "$bridge" -j ACCEPT
rule iptables AD-SANDBOX -i br-ad-control -o "$bridge" -j ACCEPT
# No public incoming connections to any published sandbox port or neighboring tenant.
rule iptables AD-SANDBOX -o "$bridge" -j DROP
# Private, metadata, loopback, multicast, benchmarking and reserved targets.
for network in 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 192.0.0.0/24 198.18.0.0/15 224.0.0.0/4 240.0.0.0/4; do
  rule iptables AD-SANDBOX -i "$bridge" -d "$network" -j DROP
done
rule iptables AD-SANDBOX -j RETURN
# Host-local control interfaces and services are inaccessible even via host public IP.
rule iptables AD-SANDBOX-HOST -i "$bridge" -j DROP
rule iptables AD-SANDBOX-HOST -j RETURN
# No IPv6 for desktop networks in this initial deployment. Prevent IPv6 private/metadata bypass.
rule ip6tables AD-SANDBOX6 -i "$bridge" -j DROP
rule ip6tables AD-SANDBOX6 -o "$bridge" -j DROP
rule ip6tables AD-SANDBOX6 -j RETURN
rule ip6tables AD-SANDBOX6-HOST -i "$bridge" -j DROP
rule ip6tables AD-SANDBOX6-HOST -j RETURN
jump iptables DOCKER-USER AD-SANDBOX
jump iptables INPUT AD-SANDBOX-HOST
jump ip6tables FORWARD AD-SANDBOX6
jump ip6tables INPUT AD-SANDBOX6-HOST
if [[ $mode == --apply ]]; then
  install -d -m 0755 /var/lib/agent-desktop/isolation
  date -u +%FT%TZ > /var/lib/agent-desktop/isolation/firewall-ready
fi
printf '%s\n' 'Scoped sandbox firewall rules verified. Re-run after Docker/firewall changes and each host boot.'
