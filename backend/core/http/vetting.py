"""
Is this address safe to connect to? (JOBS_AND_INTEGRATIONS.md § 18)

Every A and AAAA record must be globally routable. Private, loopback, link-local (the cloud
metadata address 169.254.169.254), CGNAT, multicast, reserved, unspecified and benchmark ranges are
refused, and IPv4 hidden inside IPv6 (IPv4-mapped, NAT64, 6to4, Teredo, IPv4-compatible) is
unwrapped first, or a private address passes as a public-looking IPv6 literal. A hostname with one
public and one private record is refused: the resolver picks which one we would get. A resolution
failure is refused, never "try anyway".

The check runs inside the connection (core.http.transport), against the address actually dialled,
so there is no window for DNS to answer differently between "checked" and "connected".
"""

import ipaddress
import socket

from core.providers.errors import UnsafeDestination

IP = ipaddress.IPv4Address | ipaddress.IPv6Address

NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))


def embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """The IPv4 address an IPv6 address carries, if it is one of the wrapping forms."""
    if ip.ipv4_mapped:
        return ip.ipv4_mapped
    if any(ip in network for network in NAT64):
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    if ip.sixtofour:
        return ip.sixtofour
    if ip.teredo:
        return ip.teredo[1]  # (server, client): the client is where the packets go
    if 1 < int(ip) <= 0xFFFFFFFF:  # IPv4-compatible ::a.b.c.d (deprecated, still routable)
        return ipaddress.IPv4Address(int(ip))
    return None


def is_safe(ip: IP) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        inner = embedded_ipv4(ip)
        if inner is not None:
            return is_safe(inner)
    return ip.is_global and not ip.is_multicast


def resolve(host: str, port: int) -> list[IP]:
    """Every address `host` resolves to. A failure is UnsafeDestination, not an empty answer."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise UnsafeDestination("resolution_failed", host=host) from exc
    seen: list[IP] = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0].split("%", 1)[0])
        if ip not in seen:
            seen.append(ip)
    return seen


def literal(host: str) -> IP | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def vet(host: str, port: int, resolver=None) -> IP:
    """The address to dial for `host`, or UnsafeDestination. `resolver` defaults to resolve()."""
    ip = literal(host)
    addresses = [ip] if ip is not None else (resolver or resolve)(host, port)
    if not addresses:
        raise UnsafeDestination("resolution_failed", host=host)
    unsafe = [str(a) for a in addresses if not is_safe(a)]
    if unsafe:
        raise UnsafeDestination(f"non_public_address:{','.join(unsafe)}", host=host)
    return addresses[0]
