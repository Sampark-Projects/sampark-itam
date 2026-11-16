"""Pure rules for outbound webhooks (no database, no network)."""
import hashlib
import hmac
import ipaddress
import json
import socket
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse

EVENTS = (
    "change.submitted", "change.approved", "change.rejected", "change.implemented", "change.closed",
    "change.cancelled", "workflow.started", "workflow.completed", "workflow.rejected",
    "config.drift", "lifecycle.expiry", "maintenance.completed", "maintenance.overdue",
    "purchase.approved", "purchase.rejected", "purchase.ordered", "ping",
)
MAX_ATTEMPTS = 5
# wait before attempt 2, 3, 4, 5
RETRY_DELAYS = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30), timedelta(hours=2))
MAX_URL_LENGTH = 500


class WebhookInputError(ValueError):
    pass


def clean_events(values) -> List[str]:
    if not isinstance(values, (list, tuple)) or not values:
        raise WebhookInputError("choose at least one event")
    bad = [v for v in values if v not in EVENTS]
    if bad:
        raise WebhookInputError("unknown event(s): " + ", ".join(map(str, bad)))
    return list(dict.fromkeys(values))


def _blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    """Addresses a webhook must never call: this host, link-local (cloud metadata), unspecified, multicast.
    Private LAN ranges stay allowed: a plant CMDB usually lives there."""
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved)


def parse_networks(text: Optional[str]) -> List[ipaddress._BaseNetwork]:
    """'10.20.0.0/16, 192.0.2.7' -> networks. An empty text means no allowlist."""
    out = []
    for item in (text or "").replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            out.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            raise WebhookInputError(f"not a network: {item}")
    return out


def _normal(ip: ipaddress._BaseAddress) -> ipaddress._BaseAddress:
    return ip.ipv4_mapped if ip.version == 6 and ip.ipv4_mapped is not None else ip


def _check_ip(ip, allowed: Iterable = (), denied: Iterable = ()) -> None:
    ip = _normal(ip)
    if _blocked_ip(ip) or any(ip == _normal(ipaddress.ip_address(d)) for d in denied):
        raise WebhookInputError("that address is not allowed")
    allowed = list(allowed)
    if allowed and not any(ip in net for net in allowed):
        raise WebhookInputError("that address is outside the networks allowed for webhooks")


def _parts(url: str):
    url = (url or "").strip()
    if not url or len(url) > MAX_URL_LENGTH:
        raise WebhookInputError("the URL is empty or too long")
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise WebhookInputError("the URL must start with http:// or https://")
    if parts.username or parts.password:
        raise WebhookInputError("do not put credentials in the URL")
    try:
        parts.port  # an invalid port raises here
    except ValueError:
        raise WebhookInputError("the port is not valid")
    host = parts.hostname.lower()
    if host in ("localhost", "localhost.localdomain") or host.endswith(".localhost"):
        raise WebhookInputError("that address is not allowed")
    return url, parts


def resolve_target(url: str, allowed: Iterable = (), denied: Iterable = (), resolver=None) -> str:
    """Look the host up once and return the single IP to connect to. Every address the name resolves
    to must pass, so a name with one good and one internal address is refused."""
    url, parts = _parts(url)
    host = parts.hostname
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        _check_ip(literal, allowed, denied)
        return str(literal)
    resolver = resolver or socket.getaddrinfo
    try:
        infos = resolver(host, parts.port or (443 if parts.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise WebhookInputError("the host name cannot be resolved")
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    if not addresses:
        raise WebhookInputError("the host name cannot be resolved")
    for address in addresses:
        _check_ip(ipaddress.ip_address(address), allowed, denied)
    return addresses[0]


def pin_url(url: str, ip: str):
    """The URL with the host replaced by the checked IP, plus the Host header and the TLS server
    name to use. Connecting to the IP itself means a second DNS answer (DNS rebinding) cannot
    redirect the request after the check."""
    url, parts = _parts(url)
    literal = ipaddress.ip_address(ip)
    netloc_ip = f"[{literal}]" if literal.version == 6 else str(literal)
    default_port = 443 if parts.scheme == "https" else 80
    port = parts.port
    netloc = netloc_ip + (f":{port}" if port and port != default_port else "")
    host_header = parts.hostname + (f":{port}" if port and port != default_port else "")
    if ":" in parts.hostname:  # IPv6 literal in the original URL
        host_header = f"[{parts.hostname}]" + (f":{port}" if port and port != default_port else "")
    target = parts._replace(netloc=netloc).geturl()
    return target, host_header, parts.hostname


def check_url(url: str, resolve: bool = True, allowed: Iterable = (), denied: Iterable = ()) -> str:
    """Return the cleaned URL or raise WebhookInputError. With resolve=True the host name is looked
    up too, so a name that points at a blocked address is refused."""
    url, parts = _parts(url)
    try:
        literal = ipaddress.ip_address(parts.hostname)
    except ValueError:
        literal = None
    if literal is not None:
        _check_ip(literal, allowed, denied)
    elif resolve:
        resolve_target(url, allowed, denied)
    return url


def build_body(event: str, delivery_id, tenant_id, occurred_at: datetime, data: Dict) -> str:
    """The JSON that is signed and sent. Keys are sorted so the same event always serialises the same way."""
    return json.dumps(
        {"event": event, "delivery_id": str(delivery_id), "tenant_id": str(tenant_id),
         "occurred_at": occurred_at.replace(microsecond=0).isoformat() + "Z", "data": data},
        sort_keys=True, default=str, separators=(",", ":"),
    )


def sign(secret: str, timestamp: int, body: str) -> str:
    """Hex HMAC-SHA256 over "<timestamp>.<body>"; the receiver recomputes it to check the sender."""
    return hmac.new(secret.encode("utf-8"), f"{timestamp}.{body}".encode("utf-8"), hashlib.sha256).hexdigest()


def verify(secret: str, timestamp: int, body: str, signature: str) -> bool:
    return hmac.compare_digest(sign(secret, timestamp, body), signature or "")


def headers(event: str, delivery_id, timestamp: int, signature: str) -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "User-Agent": "Sampark-Webhook/1",
        "X-Sampark-Event": event,
        "X-Sampark-Delivery": str(delivery_id),
        "X-Sampark-Timestamp": str(timestamp),
        "X-Sampark-Signature": f"sha256={signature}",
    }


def next_attempt(attempts_done: int, now: Optional[datetime] = None) -> Optional[datetime]:
    """When to try again after `attempts_done` failed attempts, or None when the delivery gives up."""
    if attempts_done >= MAX_ATTEMPTS:
        return None
    return (now or datetime.utcnow()) + RETRY_DELAYS[attempts_done - 1]


def subscribed(events: Iterable[str], event: str) -> bool:
    return event in (events or [])
