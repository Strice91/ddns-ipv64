import importlib.resources as res

from dynaconf import Dynaconf, Validator

PACKAGE_ROOT = res.files("ddns64")
PROJECT_ROOT = PACKAGE_ROOT.parent

settings = Dynaconf(
    envvar_prefix="DDNS",
    merge_enabled=True,
    load_dotenv=True,
    validators=[
        Validator("key", must_exist=True),
        Validator("domain", must_exist=True),
        Validator("logging.level", default="INFO"),
    ],
)
settings.validators.validate()
