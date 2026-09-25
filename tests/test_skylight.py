import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

import skylight


def client(**overrides):
    config = {
        "SKYLIGHT_FRAME_ID": "example-frame",
        "SKYLIGHT_ACCESS_TOKEN": "test-access",
        "SKYLIGHT_REFRESH_TOKEN": "test-refresh",
    }
    config.update(overrides)
    return skylight.Skylight(config)


class TokenPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / ".env"
        self.env_patch = patch.object(skylight, "ENV_PATH", str(self.path))
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def test_environment_only_configuration_creates_no_file(self):
        self.assertFalse(skylight.save_tokens("new-access", "new-refresh"))
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_atomic_replacement_preserves_settings_and_uses_private_mode(self):
        original = "# example\nSKYLIGHT_FRAME_ID=example-frame\nSKYLIGHT_ACCESS_TOKEN=old\n"
        self.path.write_text(original)
        self.path.chmod(0o644)
        replace = os.replace

        def inspect_then_replace(source, destination):
            self.assertEqual(self.path.read_text(), original)
            self.assertEqual(stat.S_IMODE(os.stat(source).st_mode), 0o600)
            self.assertEqual(Path(source).parent, self.path.parent)
            replace(source, destination)

        with patch.object(skylight.os, "replace", side_effect=inspect_then_replace) as mocked:
            self.assertTrue(skylight.save_tokens("new-access", "new-refresh"))
        mocked.assert_called_once()
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(
            self.path.read_text(),
            "# example\nSKYLIGHT_FRAME_ID=example-frame\n"
            "SKYLIGHT_ACCESS_TOKEN=new-access\nSKYLIGHT_REFRESH_TOKEN=new-refresh\n",
        )
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_failed_replace_preserves_original_and_removes_temporary_file(self):
        self.path.write_text("SKYLIGHT_FRAME_ID=example-frame\n")
        original = self.path.read_text()
        with patch.object(skylight.os, "replace", side_effect=OSError("test failure")):
            with self.assertRaises(OSError):
                skylight.save_tokens("new-access", "new-refresh")
        self.assertEqual(self.path.read_text(), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])


class RequestTests(unittest.TestCase):
    def test_list_create_routes_payload_with_honest_user_agent(self):
        response = Mock(status=200)
        response.read.return_value = b'{"data": {"id": "example-item"}}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(skylight.urllib.request, "urlopen", return_value=response) as urlopen:
            result = client().add_item("example-list", "Example task")
        self.assertEqual(result["data"]["id"], "example-item")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url,
                         "https://app.ourskylight.com/api/frames/example-frame/"
                         "lists/example-list/list_items")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data),
                         {"label": "Example task", "category_id": None, "section": None})
        self.assertEqual(request.get_header("Authorization"), "Bearer test-access")
        self.assertEqual(request.get_header("User-agent"),
                         "skylight-calendar-client/0.1 (unofficial educational client)")

    def test_http_failure_does_not_expose_response_body_or_request_path(self):
        error = urllib.error.HTTPError(
            "https://example.invalid/private-path", 403, "Denied", {},
            io.BytesIO(b'{"private": "response must not be printed"}'),
        )
        with patch.object(skylight.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(SystemExit) as caught:
                client()._req("GET", "private-path")
        self.assertEqual(str(caught.exception), "API request failed (HTTP 403).")

    def test_network_failure_has_safe_message(self):
        error = urllib.error.URLError("sensitive server detail")
        with patch.object(skylight.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(SystemExit) as caught:
                client().frames()
        self.assertEqual(str(caught.exception), "Network request failed.")

    def test_refresh_retries_original_request_once_and_updates_memory(self):
        sky = client()
        body = {"label": "Example task"}
        results = [(401, None), (200, {"access_token": "next-access",
                                      "refresh_token": "next-refresh"}), (200, {"ok": True})]
        with patch.object(sky, "_raw", side_effect=results) as raw, \
                patch.object(skylight, "save_tokens") as save, patch("sys.stderr", io.StringIO()):
            self.assertEqual(sky._req("POST", "example-path", body), {"ok": True})
        self.assertEqual(raw.call_count, 3)
        self.assertEqual(raw.call_args_list[0], raw.call_args_list[2])
        self.assertEqual(raw.call_args_list[1].args,
                         ("POST", skylight.OAUTH_URL,
                          {"grant_type": "refresh_token", "refresh_token": "test-refresh",
                           "client_id": "skylight-mobile"}))
        self.assertEqual(raw.call_args_list[1].kwargs, {"absolute": True})
        self.assertEqual((sky.access, sky.refresh), ("next-access", "next-refresh"))
        save.assert_not_called()  # Manually supplied configuration never opts into persistence.

    def test_second_unauthorized_response_never_refreshes_again(self):
        sky = client()
        results = [(401, None), (200, {"access_token": "next-access"}), (401, None)]
        with patch.object(sky, "_raw", side_effect=results) as raw, \
                patch.object(skylight, "save_tokens"), patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                sky.frames()
        self.assertEqual(str(caught.exception), "API request failed (HTTP 401).")
        self.assertEqual(raw.call_count, 3)

    def test_failed_refresh_does_not_retry_original_write(self):
        sky = client()
        with patch.object(sky, "_raw", side_effect=[(401, None), (403, None)]) as raw:
            with self.assertRaises(SystemExit):
                sky.add_item("example-list", "Example task")
        self.assertEqual(raw.call_count, 2)


class ConfigProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / ".env"
        self.original = (
            "SKYLIGHT_FRAME_ID=account-a-frame\n"
            "SKYLIGHT_ACCESS_TOKEN=account-a-access\n"
            "SKYLIGHT_REFRESH_TOKEN=account-a-refresh\n"
        )
        self.path.write_text(self.original)
        self.env_patch = patch.object(skylight, "ENV_PATH", str(self.path))
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def loaded_client(self, environment=None):
        with patch.dict(os.environ, environment or {}, clear=True):
            return skylight.Skylight(skylight.load_env())

    def refresh(self, sky):
        response = (200, {"access_token": "rotated-access", "refresh_token": "rotated-refresh"})
        with patch.object(sky, "_raw", return_value=response), patch("sys.stderr", io.StringIO()):
            self.assertTrue(sky._do_refresh())
        self.assertEqual((sky.access, sky.refresh), ("rotated-access", "rotated-refresh"))

    def test_file_credentials_are_rotated_in_the_source_file(self):
        self.refresh(self.loaded_client())
        self.assertEqual(self.path.read_text(),
                         "SKYLIGHT_FRAME_ID=account-a-frame\n"
                         "SKYLIGHT_ACCESS_TOKEN=rotated-access\n"
                         "SKYLIGHT_REFRESH_TOKEN=rotated-refresh\n")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_environment_account_cannot_overwrite_another_accounts_file(self):
        environment = {"SKYLIGHT_FRAME_ID": "account-b-frame",
                       "SKYLIGHT_ACCESS_TOKEN": "account-b-access",
                       "SKYLIGHT_REFRESH_TOKEN": "account-b-refresh"}
        self.refresh(self.loaded_client(environment))
        self.assertEqual(self.path.read_text(), self.original)

    def test_each_account_or_credential_override_disables_persistence(self):
        for key in ["SKYLIGHT_FRAME_ID", "SKYLIGHT_ACCESS_TOKEN", "SKYLIGHT_REFRESH_TOKEN"]:
            with self.subTest(key=key):
                self.refresh(self.loaded_client({key: "environment-override"}))
                self.assertEqual(self.path.read_text(), self.original)

    def test_timezone_only_file_does_not_capture_environment_credentials(self):
        original = "SKYLIGHT_TIMEZONE=Europe/London\n"
        self.path.write_text(original)
        self.refresh(self.loaded_client({"SKYLIGHT_FRAME_ID": "environment-frame",
                                         "SKYLIGHT_ACCESS_TOKEN": "environment-access",
                                         "SKYLIGHT_REFRESH_TOKEN": "environment-refresh"}))
        self.assertEqual(self.path.read_text(), original)

    def test_manual_configuration_does_not_write_an_existing_file(self):
        self.refresh(client())
        self.assertEqual(self.path.read_text(), self.original)

    def test_modified_loaded_credentials_lose_persistence_permission(self):
        with patch.dict(os.environ, {}, clear=True):
            config = skylight.load_env()
        config["SKYLIGHT_ACCESS_TOKEN"] = "manually-supplied-access"
        self.refresh(skylight.Skylight(config))
        self.assertEqual(self.path.read_text(), self.original)

    def test_timezone_override_does_not_change_credential_provenance(self):
        sky = self.loaded_client({"SKYLIGHT_TIMEZONE": "Asia/Tokyo"})
        self.assertEqual(sky.timezone, "Asia/Tokyo")
        self.refresh(sky)
        self.assertIn("SKYLIGHT_ACCESS_TOKEN=rotated-access\n", self.path.read_text())


class CategoryTests(unittest.TestCase):
    def setUp(self):
        self.sky = Mock()
        self.sky.categories.return_value = {"data": [
            {"id": "category-one", "attributes": {"label": "Example"}},
            {"id": "category-two", "attributes": {"label": "Example extended"}},
        ]}

    def test_exact_match_takes_precedence_and_deduplicates(self):
        self.assertEqual(skylight._labels_to_ids(self.sky, ["EXAMPLE", "Example"]),
                         ["category-one"])

    def test_ambiguous_partial_match_is_rejected(self):
        with self.assertRaisesRegex(SystemExit, "Ambiguous"):
            skylight._labels_to_ids(self.sky, ["Exam"])

    def test_missing_or_empty_match_is_rejected(self):
        for label in ["Missing", " "]:
            with self.subTest(label=label), self.assertRaisesRegex(SystemExit, "No category"):
                skylight._labels_to_ids(self.sky, [label])

    def test_duplicate_full_labels_are_rejected(self):
        self.sky.categories.return_value["data"][1]["attributes"]["label"] = "Example"
        with self.assertRaisesRegex(SystemExit, "Ambiguous"):
            skylight._labels_to_ids(self.sky, ["Example"])


class TimezoneTests(unittest.TestCase):
    def test_environment_timezone_overrides_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("SKYLIGHT_TIMEZONE=Europe/London\n")
            with patch.object(skylight, "ENV_PATH", str(path)), \
                    patch.dict(os.environ, {"SKYLIGHT_TIMEZONE": "Asia/Tokyo"}, clear=True):
                self.assertEqual(skylight.load_env()["SKYLIGHT_TIMEZONE"], "Asia/Tokyo")

    def test_default_configured_and_explicit_event_timezone(self):
        for config, override, expected in [({}, None, "UTC"),
                ({"SKYLIGHT_TIMEZONE": "Europe/London"}, None, "Europe/London"),
                ({"SKYLIGHT_TIMEZONE": "Europe/London"}, "Asia/Tokyo", "Asia/Tokyo")]:
            with self.subTest(expected=expected):
                sky = client(**config)
                with patch.object(sky, "_req", return_value={}) as request:
                    sky.create_event("Example event", timezone_name=override)
                self.assertEqual(request.call_args.args[2]["timezone"], expected)


if __name__ == "__main__":
    unittest.main()
