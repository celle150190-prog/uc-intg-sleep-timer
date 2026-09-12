"""Regression tests for Integration-API event handlers."""

from __future__ import annotations

import asyncio
import logging
import unittest

import driver


class DriverEventTest(unittest.TestCase):
    """Verify SDK-dispatched keyword arguments remain compatible."""

    def test_subscribe_handler_accepts_sdk_keyword(self) -> None:
        asyncio.run(driver.on_subscribe(entity_ids=[]))

    def test_ucapi_setup_payloads_are_not_debug_logged(self) -> None:
        driver._configure_logging()  # noqa: SLF001
        self.assertGreaterEqual(logging.getLogger("ucapi.api").level, logging.INFO)
