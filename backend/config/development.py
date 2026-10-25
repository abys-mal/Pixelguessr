"""Explicit development-only network additions; production keeps its configured lists."""

import ipaddress

from django.core.exceptions import ImproperlyConfigured


def development_network(*, debug, hosts, origins, proxies, lan_ip="", frontend_port=5173):
    if not debug:
        if lan_ip:
            raise ImproperlyConfigured("DEV_LAN_IP requires DEBUG=True; unset it in production.")
        return hosts, origins, proxies
    # Vite binds its outgoing connections to this exact loopback alias. Keeping it
    # separate from browser peers (127.0.0.1 / ::1) preserves the strict IP resolver.
    proxies = [*proxies, "127.0.0.2/32"]
    if not 1 <= frontend_port <= 65535:
        raise ImproperlyConfigured("DEV_FRONTEND_PORT must be between 1 and 65535.")
    hosts = [*hosts, "localhost", "127.0.0.1"]
    origins = [
        *origins,
        f"http://localhost:{frontend_port}",
        f"http://127.0.0.1:{frontend_port}",
    ]
    if lan_ip:
        try:
            address = ipaddress.ip_address(lan_ip)
            if (
                address.version != 4
                or not address.is_private
                or address.is_loopback
                or address.is_unspecified
            ):
                raise ValueError
        except ValueError as exc:
            raise ImproperlyConfigured("Use an exact private IPv4 address for DEV_LAN_IP.") from exc
        host = str(address)
        hosts.append(host)
        origins.append(f"http://{host}:{frontend_port}")
    return list(dict.fromkeys(hosts)), list(dict.fromkeys(origins)), list(dict.fromkeys(proxies))
