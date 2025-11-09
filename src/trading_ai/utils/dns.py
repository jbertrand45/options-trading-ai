"""Utilities to work around DNS quirks on certain development machines."""

from __future__ import annotations

import socket
from threading import Lock

_dns_lock = Lock()


def apply_dns_override(hostname: str, override_ip: str) -> None:
    """
    Force socket.getaddrinfo to return a specific IP for a hostname.

    Useful when the system resolver cannot look up api.polygon.io but we can
    still reach it via a known IP (e.g., from nslookup or dig).
    """

    normalized_host = hostname.strip()
    normalized_ip = override_ip.strip()
    if not normalized_host or not normalized_ip:
        raise ValueError("Hostname and override IP must be non-empty strings")

    with _dns_lock:
        original = getattr(socket, "_original_getaddrinfo", socket.getaddrinfo)
        overrides = getattr(socket, "_dns_overrides", {})

        if not overrides:
            # First time we install the patch.
            socket._original_getaddrinfo = original  # type: ignore[attr-defined]
            socket._dns_overrides = overrides  # type: ignore[attr-defined]

            def _patched_getaddrinfo(
                host: str | None,
                port: int | str | None,
                family: int = 0,
                socktype: int = 0,
                proto: int = 0,
                flags: int = 0,
            ):
                if host in socket._dns_overrides:  # type: ignore[attr-defined]
                    ip = socket._dns_overrides[host]  # type: ignore[attr-defined]
                    resolved_port = _normalize_port(port)
                    return [
                        (
                            socket.AF_INET,
                            socktype or socket.SOCK_STREAM,
                            proto or 0,
                            "",
                            (ip, resolved_port),
                        )
                    ]
                return socket._original_getaddrinfo(host, port, family, socktype, proto, flags)  # type: ignore[attr-defined]

            socket.getaddrinfo = _patched_getaddrinfo  # type: ignore[assignment]

        overrides[normalized_host] = normalized_ip


def _normalize_port(port: int | str | None) -> int:
    if port is None:
        return 0
    if isinstance(port, int):
        return port
    if isinstance(port, str):
        try:
            return int(port)
        except ValueError:
            raise ValueError(f"Unable to parse port value '{port}' as int") from None
    raise TypeError(f"Unsupported port type: {type(port)}")
