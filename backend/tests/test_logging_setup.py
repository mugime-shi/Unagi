"""INFO logs from the scheduler must survive a Lambda-style pre-installed root handler (root stays WARNING)."""

import logging


def test_app_logger_emits_info_when_root_is_warning():
    import app.tasks.fetch_prices  # noqa: F401  (import applies the logging setup)

    root = logging.getLogger()
    original = root.level
    root.setLevel(logging.WARNING)
    try:
        assert logging.getLogger("app.tasks.fetch_prices").isEnabledFor(logging.INFO)
        assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
    finally:
        root.setLevel(original)
