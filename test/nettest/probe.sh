#!/bin/sh
# What a project's container on a node may reach, tried from inside one
# (R178): DNS, the internet, the controller, the node's 80 and 443, and not
# the node's other ports, not the private ranges, not IPv6. Each line is
# PASS, FAIL or SKIP with what was expected; the last line is the count.
# The container then sleeps, so the row stays up and the log stays readable.
pass=0; fail=0; skip=0
say() { echo "$1 $2"; case "$1" in PASS) pass=$((pass+1));; FAIL) fail=$((fail+1));; SKIP) skip=$((skip+1));; esac; }
# reach HOST PORT: open, refused or filtered, by nc and how long it took.
reach() {
  s=$(date +%s)
  if nc -z -w 5 "$1" "$2" 2>/dev/null; then echo open; return; fi
  e=$(( $(date +%s) - s ))
  [ "$e" -ge 4 ] && echo filtered || echo refused
}
gw=$(ip route 2>/dev/null | awk '/default/ {print $3; exit}')
node=${NETTEST_NODE:-$gw}
echo "nettest: from $(hostname) at $(ip -4 addr show scope global 2>/dev/null | awk '/inet /{print $2; exit}'), gateway $gw, node $node"

# DNS: must work.
if nslookup example.com >/dev/null 2>&1; then say PASS "dns: example.com resolves"; else say FAIL "dns: example.com did not resolve (expected to)"; fi
# The internet: must work.
code=$(curl -sS -m 10 -o /dev/null -w '%{http_code}' https://example.com 2>/dev/null)
case "$code" in 2*|3*) say PASS "internet: https://example.com answered $code";; *) say FAIL "internet: https://example.com did not answer (got '$code'; expected to)";; esac
# The controller: must work.
if [ -n "$NETTEST_CTL" ]; then
  code=$(curl -sS -k -m 10 -o /dev/null -w '%{http_code}' "$NETTEST_CTL/" 2>/dev/null)
  case "$code" in 2*|3*|4*) say PASS "controller: $NETTEST_CTL answered $code";; *) say FAIL "controller: $NETTEST_CTL did not answer (got '$code'; expected to)";; esac
else say SKIP "controller: NETTEST_CTL not set"; fi
# The node's 80 and 443: reachable (open, or refused when nothing listens), never filtered.
for p in 80 443; do
  r=$(reach "$node" "$p")
  case "$r" in open|refused) say PASS "node $node:$p: $r (reachable, as 80 and 443 are)";; *) say FAIL "node $node:$p: $r (expected reachable)";; esac
done
# The node's 22: must be kept from it.
r=$(reach "$node" 22)
case "$r" in open) say FAIL "node $node:22: open (expected blocked)";; *) say PASS "node $node:22: $r (blocked, as the node's other ports are)";; esac
# A private range the node is not on: rejected at once, never a slow timeout and never open.
r=$(reach "$NETTEST_PRIVATE" 80)
case "$r" in refused) say PASS "private $NETTEST_PRIVATE:80: rejected at once";; open) say FAIL "private $NETTEST_PRIVATE:80: open (expected rejected)";; *) say FAIL "private $NETTEST_PRIVATE:80: $r (expected rejected at once; a timeout means the rule is not there or the range is unrouted)";; esac
# Docker's default bridge (another bridge, the node's docker0): dropped.
r=$(reach 172.17.0.1 2375)
case "$r" in open) say FAIL "docker0 172.17.0.1:2375: open (expected blocked)";; *) say PASS "docker0 172.17.0.1:2375: $r (blocked)";; esac
# IPv6: dropped where the host has it.
if ip -6 addr show scope global 2>/dev/null | grep -q inet6; then
  if curl -6 -sS -m 8 -o /dev/null https://example.com 2>/dev/null; then say FAIL "ipv6: reached example.com over v6 (expected dropped)"; else say PASS "ipv6: nothing over v6 (dropped)"; fi
else say SKIP "ipv6: no global v6 address here"; fi
echo "nettest: $pass pass, $fail fail, $skip skip"
exec sleep 2147483647
