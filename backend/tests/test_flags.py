import io
import json
import urllib.error

import pytest

from anomalyguard.flags import FlagClient, FlagError

FLAGS = {"flags": {"paymentFailure": {"defaultVariant": "off", "state": "ENABLED", "variants": {"off": False, "100%": True, "50%": True}},
                   "adFailure": {"defaultVariant": "off", "variants": {"off": False, "on": True}}}}


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.body).encode()


class FakeDemo:
    def __init__(self):
        self.state = json.loads(json.dumps(FLAGS))
        self.writes = []
        self.fail_with = None
        self.ignore_writes = False

    def __call__(self, request, timeout):
        if self.fail_with:
            raise self.fail_with
        if request.get_method() == "GET":
            return Response(self.state)
        body = json.loads(request.data)
        self.writes.append((request.full_url, body))
        if not self.ignore_writes:
            self.state = body["data"]
        return Response({})


def client(demo):
    return FlagClient("http://flagd-ui:4000/", opener=demo)


def test_a_flag_is_read_by_name():
    assert client(FakeDemo()).get("paymentFailure") == "off"


def test_setting_a_flag_writes_the_whole_file_with_only_that_flag_changed():
    demo = FakeDemo()
    client(demo).set("paymentFailure", "100%")
    url, body = demo.writes[0]
    assert url == "http://flagd-ui:4000/api/write-to-file"
    assert body["data"]["flags"]["paymentFailure"]["defaultVariant"] == "100%"
    assert body["data"]["flags"]["adFailure"] == FLAGS["flags"]["adFailure"]
    assert client(demo).get("paymentFailure") == "100%"


def test_an_unknown_flag_is_rejected_without_writing():
    demo = FakeDemo()
    with pytest.raises(FlagError, match="não existe"):
        client(demo).set("naoExiste", "on")
    assert demo.writes == []


def test_an_unknown_variant_is_rejected_without_writing():
    demo = FakeDemo()
    with pytest.raises(FlagError, match="variante"):
        client(demo).set("paymentFailure", "200%")
    assert demo.writes == []


def test_a_change_the_demo_did_not_keep_is_reported():
    demo = FakeDemo()
    demo.ignore_writes = True
    with pytest.raises(FlagError, match="não confirmou"):
        client(demo).set("paymentFailure", "100%")


def test_an_unreachable_demo_is_reported():
    demo = FakeDemo()
    demo.fail_with = urllib.error.URLError("sem rede")
    with pytest.raises(FlagError, match="inacessível"):
        client(demo).get("paymentFailure")


def test_an_http_error_is_reported_with_its_status():
    demo = FakeDemo()
    demo.fail_with = urllib.error.HTTPError("http://x", 500, "x", {}, io.BytesIO(b""))
    with pytest.raises(FlagError, match="HTTP 500"):
        client(demo).get("paymentFailure")


def test_a_reply_without_flags_is_rejected():
    with pytest.raises(FlagError, match="lista de falhas"):
        client(lambda request, timeout: Response({"x": 1})).read()
