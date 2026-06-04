import socket
from unittest.mock import MagicMock, patch
from datetime import datetime, UTC, timedelta
import pytest
import requests

from ddns64.utils import (
    has_ipv6_connectivity,
    detect_ip,
    resolve_nameserver,
    resolve_dns,
    IPState,
    RateLimiter,
)
from ddns64.config import settings


def test_has_ipv6_connectivity_success():
    with patch("socket.socket") as mock_socket_cls:
        mock_socket = MagicMock()
        mock_socket_cls.return_value = mock_socket

        assert has_ipv6_connectivity() is True
        mock_socket_cls.assert_called_once_with(socket.AF_INET6, socket.SOCK_STREAM)
        mock_socket.settimeout.assert_called_once_with(3)
        mock_socket.connect.assert_called_once_with((settings.network.ipv6_probe_server, 80))
        mock_socket.close.assert_called_once()


def test_has_ipv6_connectivity_failure():
    with patch("socket.socket") as mock_socket_cls:
        mock_socket = MagicMock()
        mock_socket.connect.side_effect = Exception("Connection timed out")
        mock_socket_cls.return_value = mock_socket

        assert has_ipv6_connectivity() is False


def test_detect_ip_success():
    with patch("requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.text = " 192.168.1.100\n "
        mock_get.return_value = mock_response

        ip = detect_ip(["https://ipv4.ipv64.net"], "IPv4")
        assert ip == "192.168.1.100"
        mock_get.assert_called_once_with(
            "https://ipv4.ipv64.net",
            headers={"User-Agent": settings.service.user_agent},
            timeout=5,
        )


def test_detect_ip_fallback():
    with patch("requests.get") as mock_get:
        # First call raises an exception, second succeeds
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.text = "192.168.1.200"

        mock_get.side_effect = [requests.RequestException("Error"), mock_response]

        ip = detect_ip(["https://fail.url", "https://success.url"], "IPv4")
        assert ip == "192.168.1.200"
        assert mock_get.call_count == 2


def test_detect_ip_all_fail():
    with patch("requests.get") as mock_get:
        mock_get.side_effect = requests.RequestException("Network down")
        ip = detect_ip(["https://fail.url"], "IPv4")
        assert ip is None


def test_resolve_nameserver_ip_input():
    # If the input is already a valid IP address, it should return [input] immediately
    # IPv4
    assert resolve_nameserver("1.1.1.1") == ["1.1.1.1"]
    # IPv6
    assert resolve_nameserver("2606:4700:4700::1111") == ["2606:4700:4700::1111"]


def test_resolve_nameserver_hostname_resolution():
    with patch("socket.getaddrinfo") as mock_getaddrinfo:
        # Mocking gaierror for checking if input is numeric IP
        def mock_gai_side_effect(host, port, family=0, socktype=0, proto=0, flags=0):
            if flags == socket.AI_NUMERICHOST:
                raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
            if family == socket.AF_INET:
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 0))]
            if family == socket.AF_INET6:
                return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:4700:4700::1111", 0))]
            return []

        mock_getaddrinfo.side_effect = mock_gai_side_effect

        resolved = resolve_nameserver("one.one.one.one")
        assert "1.1.1.1" in resolved
        assert "2606:4700:4700::1111" in resolved
        assert len(resolved) == 2


def test_resolve_nameserver_resolution_failure():
    with patch("socket.getaddrinfo") as mock_getaddrinfo:
        # Fail both checks
        mock_getaddrinfo.side_effect = socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        resolved = resolve_nameserver("invalid.nameserver")
        # Should fallback to the input value
        assert resolved == ["invalid.nameserver"]


def test_resolve_dns_success():
    with patch("dns.resolver.Resolver") as mock_resolver_cls:
        mock_resolver = MagicMock()
        mock_resolver_cls.return_value = mock_resolver
        
        mock_answer1 = MagicMock()
        mock_answer1.__str__.return_value = "1.2.3.4"
        mock_answer2 = MagicMock()
        mock_answer2.__str__.return_value = "5.6.7.8"
        mock_resolver.resolve.return_value = [mock_answer1, mock_answer2]

        results = resolve_dns("test.ipv64.net", "A")
        assert results == {"1.2.3.4", "5.6.7.8"}
        mock_resolver.resolve.assert_called_once_with("test.ipv64.net", "A")


def test_resolve_dns_with_custom_nameserver():
    settings.set("network.nameserver", "dns.google")
    with patch("dns.resolver.Resolver") as mock_resolver_cls, \
         patch("ddns64.utils.resolve_nameserver") as mock_resolve_ns:
        
        mock_resolve_ns.return_value = ["8.8.8.8"]
        mock_resolver = MagicMock()
        mock_resolver_cls.return_value = mock_resolver
        mock_resolver.resolve.return_value = []

        resolve_dns("test.ipv64.net", "A")
        mock_resolve_ns.assert_called_once_with("dns.google")
        assert mock_resolver.nameservers == ["8.8.8.8"]


def test_resolve_dns_failure():
    with patch("dns.resolver.Resolver") as mock_resolver_cls:
        mock_resolver = MagicMock()
        mock_resolver.resolve.side_effect = Exception("DNS error")
        mock_resolver_cls.return_value = mock_resolver

        results = resolve_dns("test.ipv64.net", "A")
        assert results == set()


def test_ip_state_detect():
    with patch("ddns64.utils.detect_ip") as mock_detect_ip, \
         patch("ddns64.utils.has_ipv6_connectivity") as mock_has_ipv6:
        
        # Test 1: both v4 and v6 enabled, v6 has connectivity
        mock_detect_ip.side_effect = ["1.2.3.4", "2001:db8::1"]
        mock_has_ipv6.return_value = True
        
        state = IPState.detect()
        assert state.ipv4 == "1.2.3.4"
        assert state.ipv6 == "2001:db8::1"
        assert state.has_any is True

        # Test 2: both enabled, but no IPv6 connectivity
        mock_detect_ip.reset_mock()
        mock_detect_ip.side_effect = ["1.2.3.4"]
        mock_has_ipv6.return_value = False
        
        state = IPState.detect()
        assert state.ipv4 == "1.2.3.4"
        assert state.ipv6 is None

        # Test 3: IPv4 disabled, IPv6 enabled
        settings.set("service.ipv4_enabled", False)
        mock_detect_ip.reset_mock()
        mock_detect_ip.side_effect = ["2001:db8::2"]
        mock_has_ipv6.return_value = True

        state = IPState.detect()
        assert state.ipv4 is None
        assert state.ipv6 == "2001:db8::2"


def test_ip_state_dns_is_valid():
    state = IPState(ipv4="1.2.3.4", ipv6="2001:db8::1")

    with patch("ddns64.utils.resolve_dns") as mock_resolve:
        # Match case
        mock_resolve.side_effect = [{"1.2.3.4"}, {"2001:db8::1"}]
        assert state.dns_is_valid() is True

        # Mismatch IPv4
        mock_resolve.reset_mock()
        mock_resolve.side_effect = [{"9.9.9.9"}, {"2001:db8::1"}]
        assert state.dns_is_valid() is False

        # Mismatch IPv6
        mock_resolve.reset_mock()
        mock_resolve.side_effect = [{"1.2.3.4"}, {"2001:db8::9999"}]
        assert state.dns_is_valid() is False


def test_rate_limiter():
    settings.set("service.max_updates", 3)
    settings.set("service.rate_limit_window", 10) # 10 minutes

    limiter = RateLimiter()
    assert limiter.is_allowed() is True

    # Record first 3 updates
    limiter.record_update()
    limiter.record_update()
    limiter.record_update()

    # Next update should be rate limited
    assert limiter.is_allowed() is False

    # Simulate shifting window (remove the first two timestamps manually or mock time)
    # Let's shift timestamps to be older than 10 minutes
    now = datetime.now(UTC)
    limiter._timestamps[0] = now - timedelta(minutes=11)
    limiter._timestamps[1] = now - timedelta(minutes=12)

    # Now it should allow updates again
    assert limiter.is_allowed() is True
