def percent(share):
    return "%d%%" % round(share * 100)


def citations(ids):
    return "".join("[%d]" % i for i in ids)


def fixed_report(context):
    suspects = context["suspects"]
    by_id = {e["id"]: e for e in context["evidence"]}
    alert = context["alert"]
    if not suspects:
        return "Não há suspeitos para este alerta.", []
    top = suspects[0]
    headline = "%s é a hipótese mais provável para o alerta %s." % (top["service"], alert["name"])
    paragraphs = []
    for suspect in suspects:
        facts = " ".join(by_id[i]["text"] for i in suspect["evidence_ids"] if i in by_id)
        if suspect["rank"] == 1:
            lead = "%s concentra %s da anomalia." % (suspect["service"], percent(suspect["share"]))
        else:
            lead = "%s aparece em %dº lugar, com %s da anomalia." % (suspect["service"], suspect["rank"], percent(suspect["share"]))
        body = ("%s %s %s" % (lead, facts, citations(suspect["evidence_ids"]))).strip()
        paragraphs.append(body)
    if context.get("limitations"):
        paragraphs.append("Limitações: %s" % " ".join(context["limitations"][:4]))
    paragraphs.append("Esta é uma leitura automática das evidências, não uma causa definitiva.")
    return headline, paragraphs
