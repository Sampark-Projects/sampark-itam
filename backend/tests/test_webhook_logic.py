"""Pure tests for webhook rules (no network: names are not resolved)."""
import uuid
from datetime import datetime, timedelta

import pytest

from app.services import webhook_logic as wl


def test_events_are_validated():
    assert wl.clean_events(["purchase.approved", "purchase.approved", "ping"]) == ["purchase.approved", "ping"]
    for bad in (None, [], "ping", ["nope"], ["ping", "nope"]):
        with pytest.raises(wl.WebhookInputError):
            wl.clean_events(bad)


@pytest.mark.parametrize("url", [
    "https://cmdb.example.com/hook", "http://10.1.2.3:8080/in", "http://192.168.0.5/x", "https://[2001:db8::1]/x",
])
def test_good_urls(url):
    assert wl.check_url(url, resolve=False) == url


@pytest.mark.parametrize("url", [
    "", "ftp://x.example.com", "javascript:alert(1)", "https://", "http://127.0.0.1/x", "http://localhost/x",
    "http://app.localhost/x", "http://169.254.169.254/latest/meta-data", "http://0.0.0.0/x", "http://[::1]/x",
    "http://[::ffff:127.0.0.1]/x", "http://224.0.0.1/x", "https://user:pw@example.com/x", "https://" + "a" * 600 + ".com",
])
def test_blocked_urls(url):
    with pytest.raises(wl.WebhookInputError):
        wl.check_url(url, resolve=False)


def test_body_is_stable_and_signed():
    when = datetime(2026, 3, 1, 12, 0, 5, 999)
    a = wl.build_body("purchase.approved", "d1", "t1", when, {"b": 2, "a": 1})
    b = wl.build_body("purchase.approved", "d1", "t1", when, {"a": 1, "b": 2})
    assert a == b and '"occurred_at":"2026-03-01T12:00:05Z"' in a
    sig = wl.sign("secret", 1700000000, a)
    assert len(sig) == 64
    assert wl.verify("secret", 1700000000, a, sig)
    assert not wl.verify("other", 1700000000, a, sig)
    assert not wl.verify("secret", 1700000001, a, sig)         # timestamp is part of the signature
    assert not wl.verify("secret", 1700000000, a + " ", sig)   # body is part of the signature
    assert not wl.verify("secret", 1700000000, a, "")


def test_headers():
    h = wl.headers("ping", uuid.UUID(int=1), 5, "abc")
    assert h["X-Sampark-Signature"] == "sha256=abc" and h["X-Sampark-Event"] == "ping"
    assert h["X-Sampark-Timestamp"] == "5"


def test_retry_schedule():
    now = datetime(2026, 1, 1)
    assert wl.next_attempt(1, now) == now + timedelta(minutes=1)
    assert wl.next_attempt(2, now) == now + timedelta(minutes=5)
    assert wl.next_attempt(4, now) == now + timedelta(hours=2)
    assert wl.next_attempt(5, now) is None            # gives up after the fifth attempt
    assert len(wl.RETRY_DELAYS) == wl.MAX_ATTEMPTS - 1


def test_subscription():
    assert wl.subscribed(["a", "b"], "a") and not wl.subscribed(["a"], "b") and not wl.subscribed(None, "a")


# --- resolving once and pinning the address (DNS rebinding) ---------------------------------

def _resolver(*addresses):
    def resolve(host, port, proto=None):
        return [(None, None, None, "", (a, port)) for a in addresses]
    return resolve


def test_resolve_target_returns_the_checked_address():
    assert wl.resolve_target("https://cmdb.plant.local/hook", resolver=_resolver("10.20.1.5")) == "10.20.1.5"


@pytest.mark.parametrize("addresses", [("127.0.0.1",), ("10.20.1.5", "169.254.169.254"), ("::ffff:127.0.0.1",)])
def test_resolve_target_refuses_any_bad_address(addresses):
    # one good and one internal answer is refused too: the client could pick either
    with pytest.raises(wl.WebhookInputError):
        wl.resolve_target("https://cmdb.plant.local/hook", resolver=_resolver(*addresses))


def test_allowlist_and_denied_hosts():
    allowed = wl.parse_networks("10.20.0.0/16, 192.0.2.7")
    assert wl.resolve_target("http://a.local/", allowed, resolver=_resolver("10.20.9.9")) == "10.20.9.9"
    assert wl.resolve_target("http://192.0.2.7/", allowed) == "192.0.2.7"
    with pytest.raises(wl.WebhookInputError):
        wl.resolve_target("http://a.local/", allowed, resolver=_resolver("10.30.0.1"))
    with pytest.raises(wl.WebhookInputError):
        wl.resolve_target("http://10.20.0.9:5432/", allowed, denied={"10.20.0.9"})  # the database host
    with pytest.raises(wl.WebhookInputError):
        wl.parse_networks("10.0.0.0/8, not-a-network")
    assert wl.parse_networks("") == []


@pytest.mark.parametrize("url,ip,target,host", [
    ("https://cmdb.example.com/api/hook?x=1", "203.0.113.9", "https://203.0.113.9/api/hook?x=1", "cmdb.example.com"),
    ("http://cmdb.example.com:8080/in", "10.1.2.3", "http://10.1.2.3:8080/in", "cmdb.example.com:8080"),
    ("https://cmdb.example.com:443/in", "10.1.2.3", "https://10.1.2.3/in", "cmdb.example.com"),
    ("https://cmdb.example.com/in", "2001:db8::5", "https://[2001:db8::5]/in", "cmdb.example.com"),
])
def test_pin_url_connects_to_the_ip_but_keeps_the_name(url, ip, target, host):
    pinned, host_header, server_name = wl.pin_url(url, ip)
    assert pinned == target
    assert host_header == host
    assert server_name == "cmdb.example.com"  # TLS still verifies the certificate for the real name


def test_bad_port_is_refused():
    with pytest.raises(wl.WebhookInputError):
        wl.check_url("http://cmdb.example.com:99999/", resolve=False)
