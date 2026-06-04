from unittest.mock import MagicMock, patch
import pytest
import requests

from ddns64.updater import perform_update
from ddns64.utils import IPState, RateLimiter
from ddns64.config import settings


def test_perform_update_success():
    limiter = RateLimiter()
    state = IPState(ipv4="1.2.3.4", ipv6="2001:db8::1")

    with patch("requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.text = '{"status": "success", "info": "good"}'
        mock_get.return_value = mock_response

        perform_update(limiter, state)

        # Assert requests.get was called with the expected params & headers
        mock_get.assert_called_once_with(
            settings.api.baseurl,
            params={
                "key": settings.api.key,
                "domain": settings.api.domain,
                "output": "min",
                "ip": "1.2.3.4",
                "ip6": "2001:db8::1",
            },
            headers={"User-Agent": settings.service.user_agent},
            timeout=10,
        )
        assert len(limiter._timestamps) == 1


def test_perform_update_prefix_parameter():
    limiter = RateLimiter()
    state = IPState(ipv4="1.2.3.4", ipv6="2001:db8::1")
    settings.set("api.prefix", "2a01:5a32:12aa:6234::/64")

    with patch("requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.text = "good"
        mock_get.return_value = mock_response

        perform_update(limiter, state)

        # Assert prefix is included in the query params
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["prefix"] == "2a01:5a32:12aa:6234::/64"


def test_perform_update_rate_limited():
    limiter = MagicMock(spec=RateLimiter)
    limiter.is_allowed.return_value = False
    state = IPState(ipv4="1.2.3.4")

    with patch("requests.get") as mock_get:
        perform_update(limiter, state)
        mock_get.assert_not_called()
        limiter.record_update.assert_not_called()


def test_perform_update_dry_run():
    limiter = RateLimiter()
    state = IPState(ipv4="1.2.3.4")
    settings.set("service.dry_run", True)

    with patch("requests.get") as mock_get:
        perform_update(limiter, state)
        mock_get.assert_not_called()
        # In updater.py, a dry run still records the update in the rate limiter
        assert len(limiter._timestamps) == 1


def test_perform_update_response_failure():
    limiter = RateLimiter()
    state = IPState(ipv4="1.2.3.4")

    with patch("requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.text = "unauthorized"  # does not contain nochg, good, or ok
        mock_get.return_value = mock_response

        perform_update(limiter, state)
        assert len(limiter._timestamps) == 0


def test_perform_update_network_exception():
    limiter = RateLimiter()
    state = IPState(ipv4="1.2.3.4")

    with patch("requests.get") as mock_get:
        mock_get.side_effect = requests.RequestException("Timeout")

        # Should not raise exception
        perform_update(limiter, state)
        assert len(limiter._timestamps) == 0
