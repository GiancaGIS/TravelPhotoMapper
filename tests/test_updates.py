from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QObject, QSettings, Qt, pyqtSignal
from PyQt6.QtNetwork import QNetworkReply
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QMessageBox

from travel_photo_mapper.app_info import APP_VERSION
from travel_photo_mapper.i18n import set_language, tr
from travel_photo_mapper.services.update_service import (
    API_VERSION, LATEST_RELEASE_API, REQUEST_TIMEOUT_MS, UpdateChecker,
    UpdateResult, release_result, retry_delay, version_key,
)
from travel_photo_mapper.ui.main_window import MainWindow
from tests.test_usability import APP, DummyMapWidget


class VersionTests(unittest.TestCase):
    def test_versions_compare_numerically_and_ignore_prefix_and_build_metadata(self):
        self.assertGreater(version_key("v1.10.0"), version_key("1.9.9"))
        self.assertGreater(version_key("2.0.0"), version_key("1.99.99"))
        self.assertEqual(version_key("v1.2.3+build.42"), version_key("1.2.3"))
        self.assertGreater(version_key("1.2.0"), version_key("1.2.0-rc.1"))
        self.assertGreater(version_key("1.2.0-rc.10"), version_key("1.2.0-rc.2"))
        self.assertGreater(version_key("1.2.0-rc.a"), version_key("1.2.0-rc.10"))

    def test_rejects_unrecognized_versions(self):
        for value in ("latest", "release-1.2.0", "1.2", "1.02.0", "1.2.0-rc.01", "1.2.0\n"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                version_key(value)

    def test_release_comparison_does_not_offer_downgrades(self):
        for tag, expected in (("v1.10.0", "available"), ("v1.1.0", "up_to_date"), ("1.0.0", "up_to_date")):
            with self.subTest(tag=tag):
                result = release_result({"tag_name": tag}, "1.1.0")
                self.assertEqual(result.status, expected)
        self.assertEqual(release_result({"tag_name": "1.2.0"}, "1.2.0-rc.1").status, "available")

    def test_excludes_drafts_and_prereleases_and_reports_invalid_payloads(self):
        for payload in ({"tag_name": "2.0.0", "draft": True},
                        {"tag_name": "2.0.0", "prerelease": True},
                        {"tag_name": "2.0.0-beta.1"}):
            with self.subTest(payload=payload):
                self.assertEqual(release_result(payload).status, "no_release")
        for payload in (None, [], {}, {"tag_name": 42}):
            with self.subTest(payload=payload):
                self.assertEqual(release_result(payload).status, "invalid_response")
        self.assertEqual(release_result({"tag_name": "latest"}).status, "unsupported_tag")

    def test_response_cannot_override_the_release_destination(self):
        result = release_result({"tag_name": "v2.0.0+build.1", "html_url": "https://untrusted.example/",
                                 "body": "Release notes"})
        self.assertEqual(result.release_url,
                         "https://github.com/GiancaGIS/TravelPhotoMapper/releases/tag/v2.0.0%2Bbuild.1")
        self.assertEqual(result.notes, "Release notes")


class FakeReply(QObject):
    finished = pyqtSignal()

    def __init__(self, payload=None, *, status=200, headers=None, error=QNetworkReply.NetworkError.NoError):
        super().__init__()
        self.status = status
        self.headers = headers or {}
        self.error_code = error
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.aborted = False

    def attribute(self, _attribute):
        return self.status

    def rawHeaderPairs(self):
        return [(key.encode(), value.encode()) for key, value in self.headers.items()]

    def rawHeader(self, name):
        return next((value.encode() for key, value in self.headers.items() if key.lower().encode() == name.lower()), b"")

    def error(self):
        return self.error_code

    def readAll(self):
        return self.payload

    def abort(self):
        self.aborted = True
        self.finished.emit()


class FakeManager:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def get(self, request):
        self.requests.append(request)
        return self.replies.pop(0)


class UpdateCheckerTests(unittest.TestCase):
    def test_request_uses_official_endpoint_headers_timeout_and_no_authentication(self):
        reply = FakeReply({"tag_name": "v2.0.0"})
        manager = FakeManager(reply)
        checker = UpdateChecker(manager=manager)
        results = []
        checker.finished.connect(results.append)
        self.assertEqual(manager.requests, [])
        self.assertTrue(checker.check())
        self.assertFalse(checker.check())
        self.assertEqual(len(manager.requests), 1)
        request = manager.requests[0]
        self.assertEqual(request.url().toString(), LATEST_RELEASE_API)
        self.assertEqual(bytes(request.rawHeader(b"Accept")), b"application/vnd.github+json")
        self.assertEqual(bytes(request.rawHeader(b"X-GitHub-Api-Version")), API_VERSION.encode())
        self.assertIn(APP_VERSION.encode(), bytes(request.rawHeader(b"User-Agent")))
        self.assertFalse(request.hasRawHeader(b"Authorization"))
        self.assertEqual(request.transferTimeout(), REQUEST_TIMEOUT_MS)
        reply.finished.emit()
        self.assertFalse(checker.busy)
        self.assertEqual(results[0].status, "available")

    def test_conditional_requests_reuse_release_on_not_modified(self):
        first = FakeReply({"tag_name": "v2.0.0"}, headers={"ETag": '"release-1"'})
        unchanged = FakeReply(status=304)
        manager = FakeManager(first, unchanged)
        checker = UpdateChecker(manager=manager)
        results = []
        checker.finished.connect(results.append)
        checker.check()
        first.finished.emit()
        checker.check()
        self.assertEqual(bytes(manager.requests[1].rawHeader(b"If-None-Match")), b'"release-1"')
        unchanged.finished.emit()
        self.assertEqual(results[0], results[1])

    def test_rate_limit_blocks_further_requests_until_retry_time(self):
        for status, headers in ((403, {"X-RateLimit-Remaining": "0", "Retry-After": "120"}), (429, {}), (403, {})):
            with self.subTest(status=status, headers=headers):
                reply = FakeReply(status=status, headers=headers)
                manager = FakeManager(reply)
                checker = UpdateChecker(manager=manager)
                results = []
                checker.finished.connect(results.append)
                checker.check()
                reply.finished.emit()
                self.assertEqual(results[0].status, "rate_limited")
                self.assertFalse(checker.check())
                self.assertEqual(len(manager.requests), 1)
                self.assertGreater(results[-1].retry_after, 0)

    def test_retry_delay_respects_headers_and_falls_back_safely(self):
        self.assertEqual(retry_delay({"retry-after": "120"}, now=100), 120)
        self.assertEqual(retry_delay({"x-ratelimit-remaining": "0", "x-ratelimit-reset": "220"}, now=100), 120)
        self.assertEqual(retry_delay({"retry-after": "Thu, 01 Jan 1970 00:03:40 GMT"}, now=100), 120)
        self.assertEqual(retry_delay({"retry-after": "nan", "x-ratelimit-reset": "garbage"}, now=100), 60)

    def test_failures_are_reported_without_claiming_app_is_up_to_date(self):
        for reply, expected in (
            (FakeReply(status=404), "no_release"),
            (FakeReply(status=500), "http_error"),
            (FakeReply(status=0, error=QNetworkReply.NetworkError.HostNotFoundError), "network_error"),
            (FakeReply(status=0, error=QNetworkReply.NetworkError.TimeoutError), "timeout"),
            (FakeReply(status=0, error=QNetworkReply.NetworkError.OperationCanceledError), "timeout"),
            (FakeReply(b"not JSON"), "invalid_response"),
        ):
            with self.subTest(expected=expected):
                checker = UpdateChecker(manager=FakeManager(reply))
                results = []
                checker.finished.connect(results.append)
                checker.check()
                reply.finished.emit()
                self.assertEqual(results[0].status, expected)

    def test_closing_cancels_request_without_emitting_a_result(self):
        reply = FakeReply()
        checker = UpdateChecker(manager=FakeManager(reply))
        results = []
        checker.finished.connect(results.append)
        checker.check()
        checker.cancel()
        self.assertTrue(reply.aborted)
        self.assertFalse(checker.busy)
        self.assertEqual(results, [])


class UpdateUiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.settings = QSettings(str(Path(self.temporary.name) / "settings.ini"), QSettings.Format.IniFormat)
        self.settings.setValue("language", "en")
        self.reply = FakeReply({"tag_name": "v2.0.0", "body": "<b>Release notes</b>"})
        self.manager = FakeManager(self.reply)
        self.patches = [
            patch("travel_photo_mapper.ui.main_window.MapWidget", DummyMapWidget),
            patch("travel_photo_mapper.ui.main_window.QSettings", return_value=self.settings),
            patch("travel_photo_mapper.ui.main_window.UpdateChecker", side_effect=lambda parent: UpdateChecker(parent, manager=self.manager)),
        ]
        for item in self.patches:
            item.start()
        self.window = MainWindow()
        self.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)

    def tearDown(self):
        self.window.close()
        APP.processEvents()
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()
        set_language("it")

    def start_window(self):
        self.window.show()
        for _ in range(100):
            if self.manager.requests:
                break
            QTest.qWait(10)
        self.assertEqual(len(self.manager.requests), 1)

    def test_startup_checks_once_without_help_menu_or_manual_action(self):
        self.assertEqual(self.manager.requests, [])
        self.assertIsNone(self.window.menuWidget())
        self.start_window()
        self.reply.payload = json.dumps({"tag_name": APP_VERSION}).encode()
        self.reply.finished.emit()
        self.window.hide()
        self.window.show()
        APP.processEvents()
        self.assertEqual(len(self.manager.requests), 1)
        self.assertTrue(self.window.update_toast.isHidden())

    def test_new_release_shows_nonmodal_toast_without_opening_browser_or_stealing_focus(self):
        self.start_window()
        self.window.open_btn.setFocus()
        before = self.window.focusWidget()
        with patch.object(QMessageBox, "exec", return_value=0), \
             patch("travel_photo_mapper.ui.main_window.QDesktopServices.openUrl") as open_url:
            self.reply.finished.emit()
            open_url.assert_not_called()
        self.assertEqual(self.window.findChildren(QMessageBox), [])
        toast = self.window.update_toast
        self.assertTrue(toast.isVisible())
        self.assertEqual(toast.message_label.textFormat(), Qt.TextFormat.PlainText)
        self.assertIn("v2.0.0", toast.message_label.text())
        self.assertEqual(self.window.focusWidget(), before)

    def test_release_opens_only_after_the_release_button_is_clicked(self):
        self.start_window()
        with patch("travel_photo_mapper.ui.main_window.QDesktopServices.openUrl") as open_url:
            self.reply.finished.emit()
            open_url.assert_not_called()
            self.window.update_toast.open_button.click()
        self.assertEqual(open_url.call_args.args[0].toString(),
                         "https://github.com/GiancaGIS/TravelPhotoMapper/releases/tag/v2.0.0")
        self.assertTrue(self.window.update_toast.isHidden())

    def test_window_close_aborts_pending_check(self):
        self.start_window()
        self.window.close()
        self.assertTrue(self.reply.aborted)
        self.assertTrue(self.window.update_toast.isHidden())

    def test_close_before_startup_callback_prevents_request(self):
        self.window.show()
        self.window.close()
        APP.processEvents()
        self.assertEqual(self.manager.requests, [])

    def test_up_to_date_and_failure_results_are_silent(self):
        self.start_window()
        with patch.object(QMessageBox, "exec", return_value=0) as dialog_exec:
            for status in ("up_to_date", "no_release", "network_error", "timeout", "http_error",
                           "invalid_response", "unsupported_tag", "rate_limited"):
                with self.subTest(status=status):
                    self.window._on_update_result(UpdateResult(status))
                    self.assertTrue(self.window.update_toast.isHidden())
            dialog_exec.assert_not_called()

    def test_dismissed_version_is_announced_again_at_next_launch(self):
        self.start_window()
        self.reply.finished.emit()
        self.window.update_toast.close_button.click()
        self.assertTrue(self.window.update_toast.isHidden())
        next_reply = FakeReply({"tag_name": "v2.0.0"})
        self.manager.replies.append(next_reply)
        second_window = MainWindow()
        second_window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        try:
            second_window.show()
            for _ in range(100):
                if len(self.manager.requests) == 2:
                    break
                QTest.qWait(10)
            self.assertEqual(len(self.manager.requests), 2)
            next_reply.finished.emit()
            self.assertTrue(second_window.update_toast.isVisible())
        finally:
            second_window.close()

    def test_toast_auto_dismisses_after_display_interval(self):
        self.start_window()
        self.window.open_btn.setFocus()
        self.reply.finished.emit()
        self.window.update_toast._dismiss_timer.start(1)
        for _ in range(100):
            if self.window.update_toast.isHidden():
                break
            QTest.qWait(10)
        self.assertTrue(self.window.update_toast.isHidden())

    def test_toast_follows_window_size_and_interface_language(self):
        self.start_window()
        self.reply.finished.emit()
        self.window.resize(1024, 720)
        APP.processEvents()
        toast = self.window.update_toast
        self.assertLess(toast.geometry().right(), self.window.centralWidget().width())
        self.assertLess(toast.geometry().bottom(), self.window.centralWidget().height())
        set_language("it")
        self.window._retranslate_ui()
        self.assertEqual(toast.title_label.text(), "Nuova versione disponibile")
        self.assertEqual(toast.open_button.text(), tr("updates.open_release"))
        self.assertIn("È disponibile la versione v2.0.0", toast.message_label.text())
