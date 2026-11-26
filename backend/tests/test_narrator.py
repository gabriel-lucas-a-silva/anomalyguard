from anomalyguard.gemini import GeminiError
from anomalyguard.narrator import ModelSpec, Narrator, ParagraphSplitter, build_prompt
from tests.helpers import EVIDENCE, SUSPECT

CONTEXT = {
    "alert": {"name": "FrontendHighErrorRate", "service": "frontend", "started_at": "2026-11-22T02:06:40Z"},
    "suspects": [SUSPECT],
    "evidence": [EVIDENCE],
    "limitations": ["Sem logs para payment."],
}
GOOD = "payment é a hipótese mais provável [1].\n\nOs erros foram de 0 para 11 a cada 15 s [1], com 40% da anomalia."
SPECS = [ModelSpec("principal"), ModelSpec("reserva", max_tokens=1200, thinking_budget=0)]


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def stream(self, model, prompt, system=None, max_tokens=900, thinking_budget=None):
        self.calls.append({"model": model, "prompt": prompt, "max_tokens": max_tokens, "thinking_budget": thinking_budget})
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        if callable(step):
            yield from step()
            return
        for piece in step:
            yield piece


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 0.5
        return self.now


def run(script, **kwargs):
    client = FakeClient(script)
    chunks, resets = [], []
    narrator = Narrator(client, SPECS, clock=Clock(), **kwargs)
    result = narrator.write(CONTEXT, lambda i, t: chunks.append((i, t)), lambda: resets.append(True))
    return result, client, chunks, resets


def pieces(text, size=7):
    return [text[i:i + size] for i in range(0, len(text), size)]


def test_a_verified_text_becomes_the_narrative():
    result, client, chunks, resets = run([pieces(GOOD)])
    assert result["kind"] == "llm" and result["verified"] is True and result["state"] == "ready"
    assert result["headline"] == "payment é a hipótese mais provável [1]."
    assert result["paragraphs"] == ["Os erros foram de 0 para 11 a cada 15 s [1], com 40% da anomalia."]
    assert result["model"] == "principal" and result["attempts"] == 1 and resets == []
    assert result["evidence"] == [{"id": 1, "service": "payment", "text": EVIDENCE["text"]}]


def test_chunks_arrive_in_order_with_their_paragraph_index():
    _, _, chunks, _ = run([pieces(GOOD)])
    assert chunks[0][0] == 0 and chunks[-1][0] == 1
    assert "".join(t for i, t in chunks if i == 0) == "payment é a hipótese mais provável [1]."


def test_timings_are_recorded():
    result, *_ = run([pieces(GOOD)])
    assert result["ttft_ms"] is not None and result["total_ms"] >= result["ttft_ms"]


def test_a_rejected_text_is_retried_with_the_reasons():
    bad = "payment teve 47 erros [1]."
    result, client, _, resets = run([pieces(bad), pieces(GOOD)])
    assert result["kind"] == "llm" and result["verified"] is True and result["attempts"] == 2 and resets == [True]
    assert "rejected" in client.calls[1]["prompt"] and "47" in client.calls[1]["prompt"]


def test_two_rejected_texts_fall_back_to_the_fixed_report():
    bad = "payment teve 47 erros [1]."
    result, _, _, resets = run([pieces(bad), pieces(bad)])
    assert result["kind"] == "fixed" and result["verified"] is None and "não passou na verificação" in result["failure_reason"]
    assert result["headline"].startswith("payment é a hipótese mais provável") and result["attempts"] == 2


def test_an_unavailable_main_model_falls_back_to_the_reserve_model():
    result, client, _, resets = run([GeminiError("HTTP 503", 503), pieces(GOOD)])
    assert result["kind"] == "llm" and result["model"] == "reserva"
    assert client.calls[1]["max_tokens"] == 1200 and client.calls[1]["thinking_budget"] == 0 and resets == [True]


def test_when_every_model_fails_the_fixed_report_is_used():
    result, *_ = run([GeminiError("HTTP 503", 503), GeminiError("HTTP 429", 429)])
    assert result["kind"] == "fixed" and "Gemini indisponível" in result["failure_reason"]


def test_a_connection_drop_in_the_middle_resets_the_partial_text():
    def dropping():
        yield "payment é "
        raise GeminiError("a conexão caiu")

    result, _, chunks, resets = run([dropping, pieces(GOOD)])
    assert result["kind"] == "llm" and result["model"] == "reserva" and resets == [True] and chunks[0] == (0, "payment é ")


def test_without_a_client_the_narrator_is_off_and_the_fixed_report_is_used():
    result = Narrator(None, SPECS, clock=Clock()).write(CONTEXT, lambda i, t: None, lambda: None)
    assert result["kind"] == "fixed" and "sem chave" in result["failure_reason"] and result["attempts"] == 0


def test_the_prompt_carries_the_ranking_the_numbered_evidence_and_the_limitations():
    prompt = build_prompt(CONTEXT)
    assert '"share_percent": 40.0' in prompt and '"n": 1' in prompt and "Sem logs para payment." in prompt
    assert "rejected" not in prompt


def test_markdown_is_removed_from_the_blocks():
    result, *_ = run([pieces("**payment** é o suspeito [1].\n\nCom 40% [1].")])
    assert result["headline"] == "payment é o suspeito [1]."


def test_the_splitter_joins_single_line_breaks_and_splits_on_blank_lines():
    splitter = ParagraphSplitter()
    splitter.feed("primeira\nlinha\n\nsegundo bloco")
    assert splitter.blocks() == ["primeira linha", "segundo bloco"]
