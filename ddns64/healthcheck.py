#!/usr/bin/env python3
import sys
from ddns64.config import settings
from ddns64.log import get_logger
from ddns64.utils import detect_ip, has_ipv6_connectivity, resolve_dns

logger = get_logger("healthcheck")


def main() -> None:
    ipv4_ok = None  # None: disabled, True: healthy, False: failed
    ipv6_ok = None  # None: disabled/no connectivity, True: healthy, False: failed
    dns_ok = False

    # 1. Check IPv4 Connectivity
    if settings.service.ipv4_enabled:
        ipv4 = detect_ip(settings.network.ipv4_sources, "IPv4")
        ipv4_ok = bool(ipv4)
        if ipv4_ok:
            logger.info("IPv4 check: OK")
        else:
            logger.warning("IPv4 check: FAILED")
    else:
        logger.debug("IPv4 check: DISABLED")

    # 2. Check IPv6 Connectivity
    if settings.service.ipv6_enabled:
        if not has_ipv6_connectivity():
            logger.warning("IPv6 check: NO CONNECTIVITY (System has no IPv6 connectivity)")
        else:
            ipv6 = detect_ip(settings.network.ipv6_sources, "IPv6")
            ipv6_ok = bool(ipv6)
            if ipv6_ok:
                logger.info("IPv6 check: OK")
            else:
                logger.warning("IPv6 check: FAILED")
    else:
        logger.debug("IPv6 check: DISABLED")

    # 3. Check DNS Resolution
    dns_records = resolve_dns("ipv64.net", "A")
    dns_ok = bool(dns_records)
    if dns_ok:
        logger.info("DNS check: OK")
    else:
        logger.error("DNS check: FAILED")

    # 4. Final Status Evaluation
    # Gather statuses of all enabled IP check runs
    enabled_ips = [status for status in (ipv4_ok, ipv6_ok) if status is not None]

    # DNS check is critical, and at least one enabled IP family check must succeed (if any are enabled)
    if not dns_ok or (enabled_ips and not any(enabled_ips)):
        logger.error(
            f"HEALTH CHECK - Critical failure: "
            f"IPv4={'OK' if ipv4_ok else 'FAILED' if ipv4_ok is False else 'DISABLED'}, "
            f"IPv6={'OK' if ipv6_ok else 'FAILED' if ipv6_ok is False else 'DISABLED/NO_CONN'}, "
            f"DNS={'OK' if dns_ok else 'FAILED'}."
        )
        sys.exit(1)

    # If any enabled IP checks failed (but not all)
    if any(status is False for status in enabled_ips):
        logger.warning(
            f"HEALTH CHECK - Warning: Partial connectivity: "
            f"IPv4={'OK' if ipv4_ok else 'FAILED' if ipv4_ok is False else 'DISABLED'}, "
            f"IPv6={'OK' if ipv6_ok else 'FAILED' if ipv6_ok is False else 'DISABLED/NO_CONN'}, "
            f"DNS={'OK' if dns_ok else 'FAILED'}."
        )
        sys.exit(0)

    # Everything is perfectly fine
    logger.info("HEALTH CHECK - All checks passed successfully.")
    sys.exit(0)


if __name__ == "__main__":
    main()
