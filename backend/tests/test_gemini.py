import io
import json
import urllib.error

import pytest

from anomalyguard.gemini import GeminiClient, GeminiError


class FakeResponse(list):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def sse(*pieces, finish=None):
    lines = []
    for i, piece in enumerate(pieces):
        chunk = {"candidates": [{"content": {"parts": [{"text": piece}]}}]}
        if finish and i == len(pieces) - 1:
            chunk["candidates"][0]["finishReason"] = finish
        lines.append(("data: " + json.dumps(chunk) + "\n").encode())
        lines.append(b"\n")
    return FakeResponse(lines)


def client(opener):
    return GeminiClient("secret-key", opener=opener)


def test_the_text_pieces_are_yielded_in_order():
    c = client(lambda request, timeout: sse("Olá, ", "mundo", finish="STOP"))
    assert list(c.stream("m", "prompt")) == ["Olá, ", "mundo"]
    assert c.last_finish == "STOP"


def test_the_key_goes_in_the_header_and_never_in_the_url():
    seen = {}

    def opener(request, timeout):
        seen["url"], seen["headers"], seen["body"] = request.full_url, dict(request.header_items()), json.loads(request.data)
        return sse("x")

    list(client(opener).stream("gemini-3.5-flash-lite", "p", system="s", max_tokens=700, thinking_budget=0))
    assert "secret-key" not in seen["url"] and seen["headers"]["X-goog-api-key"] == "secret-key"
    assert seen["url"].endswith("/models/gemini-3.5-flash-lite:streamGenerateContent?alt=sse")
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "s"
    assert seen["body"]["generationConfig"] == {"temperature": 0.2, "maxOutputTokens": 700, "thinkingConfig": {"thinkingBudget": 0}}


def test_no_thinking_config_is_sent_by_default():
    seen = {}

    def opener(request, timeout):
        seen["body"] = json.loads(request.data)
        return sse("x")

    list(client(opener).stream("m", "p"))
    assert "thinkingConfig" not in seen["body"]["generationConfig"]


def test_lines_that_are_not_data_or_not_json_are_skipped():
    response = FakeResponse([b": heartbeat\n", b"data: {quebrado\n", b'data: {"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}\n'])
    assert list(client(lambda r, timeout: response).stream("m", "p")) == ["ok"]


def test_an_http_error_carries_the_status_and_the_message():
    def opener(request, timeout):
        body = io.BytesIO(json.dumps({"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota"}}).encode())
        raise urllib.error.HTTPError(request.full_url, 429, "x", {}, body)

    with pytest.raises(GeminiError) as caught:
        list(client(opener).stream("m", "p"))
    assert caught.value.status == 429 and "RESOURCE_EXHAUSTED" in str(caught.value)


def test_a_network_failure_is_reported_without_a_status():
    def opener(request, timeout):
        raise urllib.error.URLError("sem rede")

    with pytest.raises(GeminiError) as caught:
        list(client(opener).stream("m", "p"))
    assert caught.value.status is None and "inacessível" in str(caught.value)
