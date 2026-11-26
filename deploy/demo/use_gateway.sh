#!/usr/bin/env bash
set -e
ROOT="${AG_V2:-/mnt/c/Users/gabri/OneDrive/Desktop/MBA/Monografia V2}"
DST="$HOME/otel-demo/anomalyguard/alertmanager.yml"
[ -f "$DST.bak" ] || cp "$DST" "$DST.bak"
TOKEN=$(grep '^AG_WEBHOOK_TOKEN=' "$ROOT/.env" | cut -d= -f2)
sed "s/REPLACE_WITH_TOKEN/$TOKEN/" "$ROOT/deploy/demo/alertmanager.gateway.yml" > "$DST"
docker restart alertmanager >/dev/null
sleep 6
curl -s localhost:9093/api/v2/status | python3 -c 'import sys,json; c=json.load(sys.stdin)["config"]["original"]; print([l.strip() for l in c.splitlines() if l.strip().startswith("url:")])'
