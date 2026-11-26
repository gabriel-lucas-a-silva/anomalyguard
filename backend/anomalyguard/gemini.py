import json
import socket
import urllib.error
import urllib.request

BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def api_message(error):
    try:
        detail = json.loads(error.read().decode())["error"]
        return "HTTP %s %s: %s" % (error.code, detail.get("status", ""), str(detail.get("message", ""))[:300])
    except Exception:
        return "HTTP %s" % error.code


class GeminiClient:
    def __init__(self, api_key, base=BASE, opener=urllib.request.urlopen, timeout=60):
        self.api_key = api_key
        self.base = base
        self.opener = opener
        self.timeout = timeout
        self.last_finish = None

    def body(self, prompt, system, temperature, max_tokens, thinking_budget):
        config = {"temperature": temperature, "maxOutputTokens": max_tokens}
        if thinking_budget is not None:
            config["thinkingConfig"] = {"thinkingBudget": thinking_budget}
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": config}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return body

    def stream(self, model, prompt, system=None, temperature=0.2, max_tokens=900, thinking_budget=None):
        self.last_finish = None
        url = "%s/models/%s:streamGenerateContent?alt=sse" % (self.base, model)
        data = json.dumps(self.body(prompt, system, temperature, max_tokens, thinking_budget)).encode()
        request = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key})
        try:
            response = self.opener(request, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            raise GeminiError(api_message(e), e.code)
        except (urllib.error.URLError, OSError, socket.timeout) as e:
            raise GeminiError("Gemini inacessível: %s" % getattr(e, "reason", e))
        try:
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    chunk = json.loads(line[5:])
                except ValueError:
                    continue
                candidate = (chunk.get("candidates") or [{}])[0]
                piece = "".join(p.get("text", "") for p in candidate.get("content", {}).get("parts", []))
                self.last_finish = candidate.get("finishReason", self.last_finish)
                if piece:
                    yield piece
        except (OSError, socket.timeout) as e:
            raise GeminiError("a conexão com o Gemini caiu: %s" % e)
