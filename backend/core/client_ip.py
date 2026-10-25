"""One HTTP/WebSocket peer policy; forwarding is opt-in for known proxy networks."""

import ipaddress
from functools import lru_cache

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class ClientIPError(ValueError):
    pass


def normalize_ip(value):
    if not isinstance(value, str) or not value.strip() or "%" in value or "/" in value:
        raise ClientIPError("Use an exact IPv4 or IPv6 address, without a scope or CIDR range.")
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError as exc:
        raise ClientIPError("Enter a valid IPv4 or IPv6 address.") from exc
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return str(address)


@lru_cache(maxsize=32)
def proxy_networks(values):
    try:
        networks = tuple(ipaddress.ip_network(value, strict=True) for value in values)
        if any(network.prefixlen == 0 for network in networks):
            raise ValueError("Trusting the entire Internet is not allowed.")
        return networks
    except ValueError as exc:
        raise ImproperlyConfigured(
            "IP_TRUSTED_PROXIES must contain exact proxy IPs or CIDR networks."
        ) from exc


def is_trusted_proxy(address):
    ip = ipaddress.ip_address(normalize_ip(address))
    return any(ip in network for network in proxy_networks(tuple(settings.IP_TRUSTED_PROXIES)))


def resolve_client_ip(peer, forwarded=None):
    address = normalize_ip(peer)
    if not is_trusted_proxy(address):
        return address  # Even a malformed forwarding header is irrelevant from an untrusted peer.
    if not isinstance(forwarded, str) or not forwarded or len(forwarded) > 2048:
        raise ClientIPError("A trusted proxy must supply a valid forwarding chain.")
    parts = forwarded.split(",")
    if len(parts) > 20:
        raise ClientIPError("Forwarding chain is too long.")
    chain = [normalize_ip(part) for part in parts]
    for candidate in reversed(chain):
        if not is_trusted_proxy(candidate):
            return candidate
    raise ClientIPError("No trustworthy end-client address was identified.")


def request_ip(request):
    return resolve_client_ip(
        request.META.get("REMOTE_ADDR"), request.META.get("HTTP_X_FORWARDED_FOR")
    )


def scope_ip(scope):
    client = scope.get("client")
    peer = client[0] if client else None
    # Preserve repeated header values, just as HTTP's comma-separated representation does.
    values = [
        value for name, value in scope.get("headers", []) if name.lower() == b"x-forwarded-for"
    ]
    try:
        forwarded = b",".join(values).decode("ascii") if values else None
    except UnicodeError as exc:
        if peer and not is_trusted_proxy(peer):
            return normalize_ip(peer)
        raise ClientIPError("Invalid forwarding header.") from exc
    return resolve_client_ip(peer, forwarded)
