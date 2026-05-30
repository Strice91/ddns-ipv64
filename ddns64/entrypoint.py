#!/usr/bin/env python3
from ddns64.log import get_logger
from ddns64.updater import update_loop

logger = get_logger(__name__)


def main():
    logger.info("Starting DDNS64 service...")
    try:
        update_loop()
    except KeyboardInterrupt, SystemExit:
        logger.info("Service shutting down gracefully.")
    except Exception as e:
        logger.error(f"Unexpected error in main process: {e}", exc_info=True)


if __name__ == "__main__":
    main()
