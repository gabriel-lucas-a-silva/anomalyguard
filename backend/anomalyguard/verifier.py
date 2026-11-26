import re

CITATION = re.compile(r"\[([^\]]*)\]")
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
ALWAYS_ALLOWED = (1.0, 2.0, 3.0, 15.0, 60.0, 180.0, 300.0)
MAX_RATIO = 1000.0


def parse_number(token):
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", token):
        token = token.replace(".", "")
    return float(token.replace(",", "."))


def allowed_values(evidence, suspects):
    values = set(ALWAYS_ALLOWED)
    raw = []
    for item in evidence:
        keys = ("normal_median", "incident_max", "normal_display", "incident_display", "ratio")
        raw.extend(item[k] for k in keys if item.get(k) is not None)
    raw.extend(s["share"] * 100 for s in suspects)
    for value in raw:
        for digits in (0, 1, 2):
            values.add(round(float(value), digits))
        values.add(float(value))
    if any(v >= MAX_RATIO for v in raw):
        values.add(MAX_RATIO)
    return values


def is_allowed(value, allowed):
    return any(abs(value - a) <= max(0.051, abs(a) * 0.01) for a in allowed)


def verify(text, evidence, suspects):
    problems = []
    if not text.strip():
        return ["texto vazio"]
    valid = {str(item["id"]) for item in evidence}
    citations = CITATION.findall(text)
    cited = [c for c in citations if c in valid]
    for citation in dict.fromkeys(citations):
        if not citation.isdigit():
            problems.append("colchetes com texto em vez de número: [%s]" % citation)
        elif citation not in valid:
            problems.append("citação a uma evidência que não existe: [%s]" % citation)
    if not cited:
        problems.append("nenhuma citação válida")
    allowed = allowed_values(evidence, suspects)
    stripped = CITATION.sub(" ", text)
    for token in dict.fromkeys(NUMBER.findall(stripped)):
        try:
            value = parse_number(token)
        except ValueError:
            problems.append("número ilegível: %s" % token)
            continue
        if not is_allowed(value, allowed):
            problems.append("número que não está nas evidências: %s" % token)
    return problems
