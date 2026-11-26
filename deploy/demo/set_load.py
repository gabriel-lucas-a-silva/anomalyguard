import json
import subprocess
import sys

SNIPPET = """
import json, sys, urllib.parse, urllib.request
users = int(sys.argv[1])
if users > 0:
    body = urllib.parse.urlencode({"user_count": users, "spawn_rate": 2}).encode()
    urllib.request.urlopen(urllib.request.Request("http://localhost:8089/swarm", data=body), timeout=10).read()
stats = json.load(urllib.request.urlopen("http://localhost:8089/stats/requests", timeout=10))
print(json.dumps({"state": stats["state"], "user_count": stats["user_count"], "rps": round(stats["total_rps"], 2)}))
"""


def main():
    users = sys.argv[1] if len(sys.argv) > 1 else "0"
    out = subprocess.run(["wsl", "-d", "Ubuntu-22.04", "--", "docker", "exec", "load-generator", "python3", "-c", SNIPPET, users], capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(out.stderr.strip() or "could not reach the load generator")
    print(json.loads(out.stdout.strip().splitlines()[-1]))


main()
