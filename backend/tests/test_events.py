from anomalyguard.events import EventHub, encode


def test_an_event_reaches_only_the_matching_topic():
    hub = EventHub()
    a, b = [], []
    hub.subscribe("INV-0001", a.append)
    hub.subscribe("*", b.append)
    hub.publish("INV-0001", "log", {"message": "x"})
    assert [e["event"] for e in a] == ["log"] and b == []


def test_event_ids_increase():
    hub = EventHub()
    first = hub.publish("*", "a", {})
    second = hub.publish("*", "b", {})
    assert second["id"] > first["id"]


def test_a_closed_subscription_stops_receiving():
    hub = EventHub()
    received = []
    subscription = hub.subscribe("*", received.append)
    subscription.close()
    hub.publish("*", "a", {})
    assert received == []


def test_the_sse_encoding_has_id_event_and_json_data():
    text = encode({"id": 7, "event": "log", "data": {"message": "serviço"}})
    assert text == 'id: 7\nevent: log\ndata: {"message":"serviço"}\n\n'


def test_made_events_are_not_delivered():
    hub = EventHub()
    received = []
    hub.subscribe("*", received.append)
    hub.make("snapshot", {})
    assert received == []
