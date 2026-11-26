import json
import os
import shutil
import sys

FLAGS = os.path.expanduser("~/otel-demo/src/flagd/demo.flagd.json")


def main():
    flag, variant = sys.argv[1], sys.argv[2]
    if not os.path.exists(FLAGS + ".orig"):
        shutil.copy(FLAGS, FLAGS + ".orig")
    with open(FLAGS, "r+") as f:
        data = json.load(f)
        if variant not in data["flags"][flag]["variants"]:
            raise SystemExit("unknown variant %s for %s" % (variant, flag))
        data["flags"][flag]["defaultVariant"] = variant
        f.seek(0)
        json.dump(data, f, indent=2)
        f.truncate()
    print("%s = %s" % (flag, variant))


main()
