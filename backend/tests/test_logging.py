import os
import subprocess
import sys
import unittest


class LoggingTests(unittest.TestCase):
    def run_logging(self, level):
        return subprocess.run(
            [sys.executable, '-c', '''
import logging
from app.logging_config import configure_logging
configure_logging()
configure_logging()
logger = logging.getLogger("app.test")
for level in ("debug", "info", "warning", "error", "critical"):
    getattr(logger, level)("event-%s", level)
logging.getLogger("uvicorn.access").info("access-event")
logging.getLogger("httpx").info("secret-url")
logging.getLogger("httpcore").debug("secret-header")
'''], env={**os.environ, 'LOG_LEVEL': level}, capture_output=True, text=True,
        )

    def test_thresholds_and_no_duplicate_handlers(self):
        levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        for index, level in enumerate(levels):
            with self.subTest(level=level):
                result = self.run_logging(level.lower())
                self.assertEqual(result.returncode, 0, result.stderr)
                for event_index, event in enumerate(levels):
                    self.assertEqual(result.stdout.count('event-' + event.lower()), int(event_index >= index))
                self.assertEqual('access-event' in result.stdout, index <= 1)
                self.assertNotIn('secret-', result.stdout)

    def test_invalid_level_fails_clearly(self):
        result = self.run_logging('verbose')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('LOG_LEVEL must be', result.stderr)
