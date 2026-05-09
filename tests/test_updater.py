"""Tests for zig.updater pure-Python helpers.

All functions tested here are platform-independent — no Win32 calls, no
network. Safe to run on Linux/macOS CI runners.
"""
import time

from zig.updater import (
    _is_newer,
    _is_safe_release_url,
    _parse_tuple,
    is_offerable,
    should_check_now,
)


class TestParseTuple:
    def test_basic(self):
        assert _parse_tuple("1.2.3") == (1, 2, 3)

    def test_two_parts(self):
        assert _parse_tuple("0.3.7") == (0, 3, 7)

    def test_stops_at_non_digit(self):
        assert _parse_tuple("1.2.3-beta.1") == (1, 2, 3)

    def test_prerelease_less_than_release(self):
        # 0.4.0-rc.1 should parse as (0, 4, 0) — no numeric prerelease suffix
        assert _parse_tuple("0.4.0-rc.1") == (0, 4, 0)

    def test_empty_string(self):
        assert _parse_tuple("") == ()


class TestIsNewer:
    def test_newer_patch(self):
        assert _is_newer("0.3.8", "0.3.7") is True

    def test_older_patch(self):
        assert _is_newer("0.3.6", "0.3.7") is False

    def test_same_version(self):
        assert _is_newer("0.3.7", "0.3.7") is False

    def test_newer_minor(self):
        assert _is_newer("0.4.0", "0.3.7") is True

    def test_prerelease_not_newer_than_release(self):
        # RC should NOT be considered newer than the released version
        assert _is_newer("0.4.0-rc.1", "0.4.0") is False


class TestIsSafeReleaseUrl:
    def test_valid_github_url(self):
        assert _is_safe_release_url("https://github.com/calebohara/noidle.app/releases/tag/v0.3.7") is True

    def test_www_github(self):
        assert _is_safe_release_url("https://www.github.com/x/y/releases/tag/v1") is True

    def test_javascript_scheme(self):
        assert _is_safe_release_url("javascript:alert(1)") is False

    def test_file_scheme(self):
        assert _is_safe_release_url("file:///etc/passwd") is False

    def test_http_not_https(self):
        assert _is_safe_release_url("http://github.com/x/y") is False

    def test_non_github_host(self):
        assert _is_safe_release_url("https://evil.com/releases/tag/v1") is False

    def test_unc_path(self):
        assert _is_safe_release_url("\\\\attacker\\share\\x.exe") is False

    def test_ms_msdt(self):
        assert _is_safe_release_url("ms-msdt:something") is False

    def test_empty_string(self):
        assert _is_safe_release_url("") is False


class TestIsOfferable:
    def test_no_skip(self):
        assert is_offerable("0.4.0", "") is True

    def test_same_version_skipped(self):
        assert is_offerable("0.4.0", "0.4.0") is False

    def test_newer_than_skip(self):
        assert is_offerable("0.4.1", "0.4.0") is True

    def test_older_than_skip(self):
        assert is_offerable("0.3.9", "0.4.0") is False


class TestShouldCheckNow:
    def test_never_checked(self):
        assert should_check_now(0, False) is True

    def test_negative_timestamp(self):
        assert should_check_now(-1, False) is True

    def test_just_checked_success(self):
        assert should_check_now(time.time(), False) is False

    def test_just_checked_failure(self):
        assert should_check_now(time.time(), True) is False

    def test_success_interval_elapsed(self):
        # 7 hours ago — past the 6h success interval
        past = time.time() - (7 * 3600)
        assert should_check_now(past, False) is True

    def test_failure_interval_elapsed(self):
        # 25 hours ago — past the 24h failure interval
        past = time.time() - (25 * 3600)
        assert should_check_now(past, True) is True

    def test_explicit_now(self):
        base = 1_000_000.0
        assert should_check_now(base, False, now=base) is False
        assert should_check_now(base, False, now=base + 7 * 3600) is True
