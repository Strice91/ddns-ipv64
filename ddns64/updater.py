import time

import requests

from ddns64.config import settings
from ddns64.log import get_logger
from ddns64.utils import IPState, RateLimiter

logger = get_logger(__name__)


def perform_update(limiter: RateLimiter, state: IPState) -> None:
    """Sends a DDNS update to ipv64.net for the given IP state."""

    # 1. Check rate limit
    if not limiter.is_allowed():
        logger.warning("Rate limit reached. Skipping update.")
        return

    # 2. Build API call params
    params = {"key": settings.api.key, "domain": settings.api.domain, "output": "min"}
    if state.ipv4:
        params["ip"] = state.ipv4
    if state.ipv6:
        params["ip6"] = state.ipv6
    if settings.api.prefix:
        params["prefix"] = settings.api.prefix

    # 3. Execute API call
    try:
        if settings.service.dry_run:
            logger.info(f"Dry-run: Would update to {params}")
            limiter.record_update()
            return

        headers = {"User-Agent": settings.service.user_agent}
        response = requests.get(settings.api.baseurl, params=params, headers=headers, timeout=10)
        if response.ok and any(res in response.text.lower() for res in ["nochg", "good", "ok"]):
            logger.info(f"Update successful. IPv4: {state.ipv4}, IPv6: {state.ipv6}")
            limiter.record_update()
        else:
            logger.error(f"Update failed. Server response: {response.text!r}")
    except requests.RequestException as e:
        logger.error(f"Network error: {e}")


def update_loop() -> None:
    limiter = RateLimiter()

    while True:
        logger.info(f"Starting DDNS update check for domain: {settings.api.domain}")

        state = IPState.detect()

        if not state.has_any:
            logger.error("No valid IP addresses detected (v4 or v6). Skipping.")
        elif state.dns_is_valid():
            logger.info(
                f"DNS is up-to-date (IPv4: {state.ipv4 or 'disabled'}, "
                f"IPv6: {state.ipv6 or 'disabled'}). No update needed."
            )
        else:
            perform_update(limiter, state)

        logger.info(f"Next check in {settings.service.update_interval}m")
        time.sleep(settings.service.update_interval * 60)
