import itertools
import json
import threading

GLOBAL_TOPIC = "*"


class Subscription:
    def __init__(self, hub, topic, push):
        self.hub = hub
        self.topic = topic
        self.push = push

    def close(self):
        self.hub.unsubscribe(self)


class EventHub:
    def __init__(self):
        self.lock = threading.Lock()
        self.subscriptions = set()
        self.counter = itertools.count(1)

    def subscribe(self, topic, push):
        subscription = Subscription(self, topic, push)
        with self.lock:
            self.subscriptions.add(subscription)
        return subscription

    def unsubscribe(self, subscription):
        with self.lock:
            self.subscriptions.discard(subscription)

    def make(self, name, data):
        return {"id": next(self.counter), "event": name, "data": data}

    def publish(self, topic, name, data):
        event = self.make(name, data)
        with self.lock:
            targets = [s for s in self.subscriptions if s.topic == topic]
        for subscription in targets:
            subscription.push(event)
        return event


def encode(event):
    payload = json.dumps(event["data"], ensure_ascii=False, separators=(",", ":"))
    return "id: %d\nevent: %s\ndata: %s\n\n" % (event["id"], event["event"], payload)
