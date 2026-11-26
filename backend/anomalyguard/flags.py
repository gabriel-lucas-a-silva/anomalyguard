import json
import socket
import urllib.error
import urllib.request


class FlagError(Exception):
    pass


class FlagClient:
    def __init__(self, base_url, opener=urllib.request.urlopen, timeout=10):
        self.base_url = base_url.rstrip("/")
        self.opener = opener
        self.timeout = timeout

    def request(self, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base_url + path, data=data, method="POST" if data is not None else "GET", headers={"Content-Type": "application/json"})
        try:
            with self.opener(request, timeout=self.timeout) as response:
                payload = response.read()
        except urllib.error.HTTPError as e:
            raise FlagError("o serviço de falhas do Demo respondeu HTTP %d" % e.code)
        except (urllib.error.URLError, OSError, socket.timeout) as e:
            raise FlagError("o serviço de falhas do Demo está inacessível: %s" % getattr(e, "reason", e))
        try:
            return json.loads(payload) if payload else {}
        except ValueError:
            raise FlagError("resposta inválida do serviço de falhas do Demo")

    def read(self):
        data = self.request("/api/read-file")
        if not isinstance(data.get("flags"), dict):
            raise FlagError("o serviço de falhas do Demo não devolveu a lista de falhas")
        return data

    def get(self, flag):
        flags = self.read()["flags"]
        if flag not in flags:
            raise FlagError("a falha %s não existe no Demo" % flag)
        return flags[flag]["defaultVariant"]

    def set(self, flag, variant):
        data = self.read()
        flags = data["flags"]
        if flag not in flags:
            raise FlagError("a falha %s não existe no Demo" % flag)
        if variant not in flags[flag].get("variants", {}):
            raise FlagError("a falha %s não tem a variante %s" % (flag, variant))
        flags[flag]["defaultVariant"] = variant
        self.request("/api/write-to-file", {"data": data})
        if self.get(flag) != variant:
            raise FlagError("o Demo não confirmou a mudança da falha %s" % flag)
