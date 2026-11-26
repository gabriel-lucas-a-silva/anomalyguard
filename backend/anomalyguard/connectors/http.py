import json
import time
import urllib.error
import urllib.request

from .base import SourceError, SourceUnavailable


class HttpClient:
    def __init__(self, timeout=20.0, retries=3, backoff=0.5, sleep=time.sleep, opener=urllib.request.urlopen):
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.sleep = sleep
        self.opener = opener

    def request(self, url, body=None, method=None):
        data = json.dumps(body).encode() if body is not None else None
        last = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(url, data=data, method=method or ("POST" if data is not None else "GET"),
                                             headers={"Content-Type": "application/json"})
                with self.opener(req, timeout=self.timeout) as response:
                    payload = response.read()
            except urllib.error.HTTPError as e:
                if 400 <= e.code < 500:
                    raise SourceError("HTTP %d from %s" % (e.code, _short(url)))
                last = "HTTP %d from %s" % (e.code, _short(url))
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                last = "%s: %s" % (_short(url), getattr(e, "reason", e))
            else:
                try:
                    return json.loads(payload) if payload else None
                except ValueError:
                    raise SourceError("invalid JSON from %s" % _short(url))
            if attempt + 1 < self.retries:
                self.sleep(self.backoff * (2 ** attempt))
        raise SourceUnavailable("unavailable after %d attempts: %s" % (self.retries, last))


def _short(url):
    return url if len(url) <= 120 else url[:117] + "..."
