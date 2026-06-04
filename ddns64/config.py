import importlib.resources as res
import re
import ipaddress
import logging
from dynaconf import Dynaconf, Validator

PACKAGE_ROOT = res.files("ddns64")
PROJECT_ROOT = PACKAGE_ROOT.parent
CONFIG_PATH = PROJECT_ROOT / "config"

_DOMAIN_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+"
    r"[a-zA-Z]{2,}$"
)
_URL_RE = re.compile(r"^https?://\S+$")

def _is_valid_domain(value: object) -> bool:
    return isinstance(value, str) and bool(_DOMAIN_RE.match(value))


def _is_valid_url(value: object) -> bool:
    return isinstance(value, str) and bool(_URL_RE.match(value))


def _is_valid_ipv6(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
        return ip.version == 6
    except ValueError:
        return False


def _is_url_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= 1
        and all(_is_valid_url(u) for u in value)
    )


settings = Dynaconf(
    envvar_prefix="DDNS",
    merge_enabled=True,
    load_dotenv=False,
    environments=False,
    settings_files=["settings.toml", ".secrets.toml"],
    validators=[
        # --- api -----------------------------------------------------------
        Validator("api.key", must_exist=True, is_type_of=str, len_min=1),
        Validator(
            "api.domain",
            must_exist=True,
            is_type_of=str,
            condition=_is_valid_domain,
            messages={"condition": "api.domain must be a valid fully-qualified domain name"},
        ),
        Validator(
            "api.baseurl",
            must_exist=True,
            is_type_of=str,
            condition=_is_valid_url,
            messages={"condition": "api.baseurl must be a valid http(s) URL"},
        ),
        Validator("api.prefix", default="", is_type_of=str),

        # --- service -------------------------------------------------------
        Validator(
            "service.update_interval",
            default=15,
            is_type_of=int,
            gte=1,
            lte=1440,
            messages={
                "gte": "service.update_interval must be at least 1 minute",
                "lte": "service.update_interval must not exceed 1440 minutes (24 h)",
            },
        ),
        Validator("service.ipv4_enabled", default=True, is_type_of=bool),
        Validator("service.ipv6_enabled", default=True, is_type_of=bool),
        Validator("service.dry_run", default=False, is_type_of=bool),
        Validator(
            "service.max_updates",
            default=0,
            is_type_of=int,
            gte=0,
            lte=100,
            messages={
                "gte": "service.max_updates must be at least 0",
                "lte": "service.max_updates must not exceed 100",
            },
        ),
        Validator(
            "service.rate_limit_window",
            default=60,
            is_type_of=int,
            gte=1,
            lte=1440,
            messages={
                "gte": "service.rate_limit_window must be at least 1 minute",
                "lte": "service.rate_limit_window must not exceed 1440 minutes (24 h)",
            },
        ),

        # --- network -------------------------------------------------------        
        Validator(
            "network.ipv4_sources",
            must_exist=True,
            condition=_is_url_list,
            messages={
                "condition": (
                    "network.ipv4_sources must be a non-empty list of valid http(s) URLs"
                )
            },
        ),
        Validator(
            "network.ipv6_sources",
            must_exist=True,
            condition=_is_url_list,
            messages={
                "condition": (
                    "network.ipv6_sources must be a non-empty list of valid http(s) URLs"
                )
            },
        ),
        Validator(
            "network.ipv6_probe_server",
            default="2606:4700:4700::1111",
            is_type_of=str,
            condition=_is_valid_ipv6,
            messages={
                "condition": "network.ipv6_probe_server must be a valid IPv6 address"
            },
        ),
        Validator(
            "network.nameserver",
            default="",
            is_type_of=str,
        ),

        # --- logging -------------------------------------------------------
        Validator(
            "logging.level",
            default="INFO",
            is_type_of=str,
            condition=lambda v: getattr(logging, v.upper(), None),
            messages={
                "condition": (
                    "logging.level must be a valid logging level"
                )
            },
        ),
    ],
)
settings.validators.validate()
