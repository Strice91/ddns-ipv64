import socket
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import dns.resolver
import requests

from ddns64.config import settings
from ddns64.log import get_logger

logger = get_logger(__name__)


def has_ipv6_connectivity() -> bool:
    """Checks whether the system can actually reach the IPv6 internet."""
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((settings.network.ipv6_probe_server, 80))  # Cloudflare public IPv6
        s.close()
        return True
    except Exception:
        return False


def detect_ip(sources: list[str], label: str) -> str | None:
    """Tries each source URL in order and returns the first valid IP string."""
    headers = {"User-Agent": settings.service.user_agent}
    for url in sources:
        try:
            response = requests.get(url, headers=headers, timeout=5)
            if response.ok:
                ip = response.text.strip()
                logger.debug(f"Detected {label}: {ip} (source: {url})")
                return ip
        except requests.RequestException:
            continue
    logger.warning(f"Failed to detect {label} from any source.")
    return None


def resolve_nameserver(ns: str) -> list[str]:
    """Resolves name server hostname into raw IP addresses, returning raw IPs."""
    # Check if already a valid IP address
    try:
        socket.getaddrinfo(ns, None, socket.AF_UNSPEC, socket.SOCK_STREAM, 0, socket.AI_NUMERICHOST)
        return [ns]
    except socket.gaierror:
        pass

    # Try to resolve hostname to IPv4/IPv6 IPs using system resolver
    resolved_ips = []
    try:
        for family in (socket.AF_INET, socket.AF_INET6):
            try:
                infos = socket.getaddrinfo(ns, None, family, socket.SOCK_STREAM)
                for info in infos:
                    ip = info[4][0]
                    if ip not in resolved_ips:
                        resolved_ips.append(ip)
            except socket.gaierror:
                continue
    except Exception as e:
        logger.debug(f"Failed to resolve name server '{ns}' to IPs: {e}")

    # Fall back to original nameserver if nothing resolved
    return resolved_ips if resolved_ips else [ns]


def resolve_dns(domain: str, record_type: str) -> set[str]:
    """Returns the set of IPs the domain currently resolves to for the given record type."""
    try:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = 5
        if settings.network.nameserver:
            resolver.nameservers = resolve_nameserver(settings.network.nameserver)
        logger.debug(f"Using DNS nameservers: {resolver.nameservers} {settings.network.nameserver}")
        answers = resolver.resolve(domain, record_type)
        return {str(r) for r in answers}
    except Exception as e:
        logger.debug(f"DNS resolution failed for {domain} ({record_type}): {e}")
        return set()


@dataclass
class IPState:
    """
    Represents the current IP state of the application.

    Holds the detected public IPv4/IPv6 addresses and can check whether
    the configured DNS domain already points to them — without any file I/O.
    """

    ipv4: str | None = field(default=None)
    ipv6: str | None = field(default=None)

    @classmethod
    def detect(cls) -> "IPState":
        """Fetches the current public IPs based on the enabled address families."""
        ipv4 = None
        if settings.service.ipv4_enabled:
            ipv4 = detect_ip(settings.network.ipv4_sources, "IPv4")
        else:
            logger.info("IPv4 detection is disabled.")

        ipv6 = None
        if settings.service.ipv6_enabled:
            if has_ipv6_connectivity():
                ipv6 = detect_ip(settings.network.ipv6_sources, "IPv6")
            else:
                logger.warning("IPv6 is enabled in config but the system has no IPv6 connectivity — skipping IPv6.")
        else:
            logger.info("IPv6 detection is disabled.")

        return cls(ipv4=ipv4, ipv6=ipv6)

    @property
    def has_any(self) -> bool:
        """True if at least one address was successfully detected."""
        return bool(self.ipv4 or self.ipv6)

    def dns_is_valid(self) -> bool:
        """
        Resolves the configured domain and compares the result against the
        detected IPs.  Returns True if DNS already reflects the current state
        (i.e. no update is needed).
        """
        valid = True

        if self.ipv4:
            dns_a = resolve_dns(settings.api.domain, "A")
            if self.ipv4 not in dns_a:
                logger.info(f"DNS A record mismatch: current={self.ipv4}, dns={dns_a or 'none'}")
                valid = False
            else:
                logger.debug(f"DNS A record OK: {self.ipv4}")

        if self.ipv6:
            dns_aaaa = resolve_dns(settings.api.domain, "AAAA")
            if self.ipv6 not in dns_aaaa:
                logger.info(f"DNS AAAA record mismatch: current={self.ipv6}, dns={dns_aaaa or 'none'}")
                valid = False
            else:
                logger.debug(f"DNS AAAA record OK: {self.ipv6}")

        return valid


class RateLimiter:
    def __init__(self) -> None:
        self._timestamps: list[datetime] = []
        self.max_updates: int = settings.service.max_updates
        self.window = timedelta(minutes=settings.service.rate_limit_window)

    def _filter_old(self) -> None:
        """Removes timestamps outside the rolling window."""
        now = datetime.now(UTC)
        self._timestamps = [ts for ts in self._timestamps if now - ts < self.window]

    def is_allowed(self) -> bool:
        if self.max_updates <= 0:
            logger.debug("Rate limiting is disabled (max_updates <= 0).")
            return True
        self._filter_old()
        count = len(self._timestamps)
        allowed = count < self.max_updates
        if not allowed:
            logger.warning(
                f"Rate limit reached: {count}/{self.max_updates} updates "
                f"in the last {settings.service.rate_limit_window} minutes. Skipping update."
            )
            # TODO: send notification
        else:
            logger.debug(
                f"Rate limiter check: {count}/{self.max_updates} updates "
                f"in the last {settings.service.rate_limit_window} minutes. Update allowed."
            )
        return allowed

    def record_update(self) -> None:
        if self.max_updates <= 0:
            return
        self._timestamps.append(datetime.now(UTC))
        logger.info(
            f"Recorded update in rate limiter. "
            f"Current updates in window: {len(self._timestamps)}/{self.max_updates}."
        )

