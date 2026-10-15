import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from auth import (
    AccountExistsError,
    AuthRateLimiter,
    AuthStore,
    AuthenticationError,
)


class TestAuthStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = AuthStore(
            Path(self.temp_dir.name) / "accounts.sqlite3",
            secret_key="a-stable-test-signing-key-with-enough-entropy",
        )
        self.user = self.store.register(
            "Reader@example.com",
            "correct-horse-test-password",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_email_is_normalized_and_password_is_verified(self):
        user = self.store.authenticate(
            "reader@EXAMPLE.com",
            "correct-horse-test-password",
        )

        self.assertEqual(user["id"], self.user["id"])
        self.assertEqual(user["email"], "reader@example.com")

    def test_duplicate_emails_are_rejected_case_insensitively(self):
        with self.assertRaises(AccountExistsError):
            self.store.register(
                "READER@example.com",
                "different-test-password",
            )

    def test_bad_password_is_rejected(self):
        with self.assertRaises(AuthenticationError):
            self.store.authenticate("reader@example.com", "wrong-password")

    def test_sessions_are_signed_and_can_be_revoked(self):
        token = self.store.create_session(self.user["id"])

        self.assertEqual(
            self.store.get_user_from_session(token)["id"],
            self.user["id"],
        )
        self.assertIsNone(
            self.store.get_user_from_session(token[:-1] + ("a" if token[-1] != "a" else "b"))
        )

        self.store.revoke_session(token)

        self.assertIsNone(self.store.get_user_from_session(token))

    def test_session_from_another_signing_key_is_rejected(self):
        token = self.store.create_session(self.user["id"])
        other_store = AuthStore(
            Path(self.temp_dir.name) / "accounts.sqlite3",
            secret_key="a-different-test-signing-key-with-enough-entropy",
        )

        self.assertIsNone(other_store.get_user_from_session(token))


class TestAuthRateLimiter(unittest.TestCase):
    def test_request_limit_is_scoped_by_key(self):
        limiter = AuthRateLimiter(attempts=2, window_seconds=60)

        self.assertTrue(limiter.allow("register:client-a"))
        self.assertTrue(limiter.allow("register:client-a"))
        self.assertFalse(limiter.allow("register:client-a"))
        self.assertTrue(limiter.allow("register:client-b"))

    @patch("auth.time.monotonic")
    def test_expired_clients_are_pruned_when_the_client_limit_is_reached(self, clock):
        limiter = AuthRateLimiter(
            attempts=1,
            window_seconds=10,
            max_clients=1,
        )

        clock.return_value = 0
        self.assertTrue(limiter.allow("register:client-a"))
        clock.return_value = 1
        self.assertFalse(limiter.allow("register:client-b"))
        clock.return_value = 11
        self.assertTrue(limiter.allow("register:client-b"))
