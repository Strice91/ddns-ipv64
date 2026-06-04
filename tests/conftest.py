import os

# Set environment variables for Dynaconf validation before any other import
os.environ["DDNS_API__KEY"] = "mock_api_key_12345"
os.environ["DDNS_API__DOMAIN"] = "test.ipv64.net"
os.environ["DDNS_API__BASEURL"] = "https://ipv64.net/nic/update"
os.environ["DDNS_NETWORK__IPV4_SOURCES"] = '["https://ipv4.ipv64.net"]'
os.environ["DDNS_NETWORK__IPV6_SOURCES"] = '["https://ipv6.ipv64.net"]'
os.environ["DDNS_SERVICE__DRY_RUN"] = "false"
os.environ["DDNS_SERVICE__MAX_UPDATES"] = "10"

import pytest
from ddns64.config import settings

@pytest.fixture(autouse=True)
def reset_settings():
    """Fixture to restore settings to a clean state after each test."""
    # Dynaconf settings can be modified in-place using settings.set() or settings.update()
    # Save current values
    original_data = {
        "api": {
            "key": settings.api.key,
            "domain": settings.api.domain,
            "baseurl": settings.api.baseurl,
            "prefix": settings.api.prefix,
        },
        "service": {
            "update_interval": settings.service.update_interval,
            "ipv4_enabled": settings.service.ipv4_enabled,
            "ipv6_enabled": settings.service.ipv6_enabled,
            "dry_run": settings.service.dry_run,
            "max_updates": settings.service.max_updates,
            "rate_limit_window": settings.service.rate_limit_window,
            "user_agent": settings.service.user_agent,
        },
        "network": {
            "ipv4_sources": list(settings.network.ipv4_sources),
            "ipv6_sources": list(settings.network.ipv6_sources),
            "ipv6_probe_server": settings.network.ipv6_probe_server,
            "nameserver": settings.network.nameserver,
        }
    }
    yield settings
    # Restore values
    for section, keys in original_data.items():
        for key, val in keys.items():
            settings.set(f"{section}.{key}", val)
