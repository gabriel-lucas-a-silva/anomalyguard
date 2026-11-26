#!/usr/bin/env bash
set -e
DST="$HOME/otel-demo/anomalyguard/alertmanager.yml"
cp "$DST.bak" "$DST"
docker restart alertmanager >/dev/null
sleep 5
curl -s localhost:9093/api/v2/status | python3 -c 'import sys,json; c=json.load(sys.stdin)["config"]["original"]; print([l.strip() for l in c.splitlines() if l.strip().startswith("url:")])'
