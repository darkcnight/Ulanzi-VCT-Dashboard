import ha


class FakeResp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_get_state_ok(monkeypatch):
    monkeypatch.setenv("HA_TOKEN", "tok")
    monkeypatch.setenv("HA_URL", "http://ha.test:8123/")
    seen = {}

    def fake_get(url, headers, timeout):
        seen["url"] = url
        seen["auth"] = headers["Authorization"]
        return FakeResp(200, {"state": "on", "attributes": {}})

    monkeypatch.setattr(ha.httpx, "get", fake_get)
    assert ha.get_state("light.x") == {"state": "on", "attributes": {}}
    assert seen == {"url": "http://ha.test:8123/api/states/light.x", "auth": "Bearer tok"}


def test_get_state_without_token_does_not_call_ha(monkeypatch):
    monkeypatch.delenv("HA_TOKEN", raising=False)

    def boom(*a, **k):
        raise AssertionError("must not be called")

    monkeypatch.setattr(ha.httpx, "get", boom)
    assert ha.get_state("light.x") is None


def test_get_state_401_404_500_and_exception_return_none(monkeypatch):
    monkeypatch.setenv("HA_TOKEN", "tok")
    for status in (401, 404, 500):
        monkeypatch.setattr(ha.httpx, "get", lambda *a, _s=status, **k: FakeResp(_s))
        assert ha.get_state("light.x") is None

    def raises(*a, **k):
        raise ha.httpx.ConnectError("down")

    monkeypatch.setattr(ha.httpx, "get", raises)
    assert ha.get_state("light.x") is None


def test_usable_and_numeric():
    assert ha.usable({"state": "on", "attributes": {}})
    assert not ha.usable({"state": "unavailable", "attributes": {}})
    assert not ha.usable({"state": "unknown", "attributes": {}})
    assert not ha.usable(None)
    assert ha.numeric({"state": "0.4", "attributes": {}}) == 0.4
    assert ha.numeric({"state": "unavailable", "attributes": {}}) is None
    assert ha.numeric({"state": "abc", "attributes": {}}) is None
    assert ha.numeric(None) is None


def test_get_state_rejects_malformed_entity_id(monkeypatch):
    monkeypatch.setenv("HA_TOKEN", "tok")

    def boom(*a, **k):
        raise AssertionError("must not be called")

    monkeypatch.setattr(ha.httpx, "get", boom)
    for bad in ("../config", "light.x/../../config", "light", "", None, 123, "light.x?y=1", "light.x\n"):
        assert ha.get_state(bad) is None
