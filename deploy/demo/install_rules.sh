#!/usr/bin/env bash
set -e
ROOT="${AG_V2:-/mnt/c/Users/gabri/OneDrive/Desktop/MBA/Monografia V2}"
DEST="$HOME/otel-demo/anomalyguard/rules/anomalyguard.rules.yml"
[ -f "$DEST.orig" ] || cp "$DEST" "$DEST.orig"
cp "$ROOT/deploy/demo/rules/anomalyguard.rules.yml" "$DEST"
for tentativa in $(seq 1 20); do curl -sf -X POST localhost:9090/-/reload && break; sleep 3; done
sleep 3
curl -s localhost:9090/api/v1/rules | python3 -c 'import sys,json; [print(r["name"], r["query"].split(">")[-1].strip()) for g in json.load(sys.stdin)["data"]["groups"] for r in g["rules"]]'
