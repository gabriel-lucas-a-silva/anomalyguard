import hashlib
import json
import os
import shutil
import sys
import urllib.request
import zipfile

ARTICLE = "31938495"
DEST = sys.argv[1] if len(sys.argv) > 1 else "/opt/rcaeval"


def main():
    meta = json.load(urllib.request.urlopen("https://api.figshare.com/v2/articles/" + ARTICLE, timeout=60))
    info = meta["files"][0]
    archive = "/tmp/" + info["name"]
    with urllib.request.urlopen(info["download_url"], timeout=300) as response, open(archive, "wb") as out:
        shutil.copyfileobj(response, out)
    digest = hashlib.md5(open(archive, "rb").read()).hexdigest()
    if digest != info["computed_md5"]:
        raise SystemExit("checksum mismatch: %s != %s" % (digest, info["computed_md5"]))
    with zipfile.ZipFile(archive) as z:
        z.extractall("/tmp/rcaeval-src")
    root = next(os.path.join(d, n) for d, names, _ in os.walk("/tmp/rcaeval-src") for n in names if n == "RCAEval" and os.path.isdir(os.path.join(d, n)))
    shutil.copytree(os.path.dirname(root), DEST)
    with open(os.path.join(DEST, "SOURCE.txt"), "w") as f:
        f.write("figshare article %s, file %s, md5 %s\n" % (ARTICLE, info["name"], digest))
    print("code ready in %s (md5 %s)" % (DEST, digest))


main()
