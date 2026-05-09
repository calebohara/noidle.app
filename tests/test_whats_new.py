"""Tests for zig.whats_new.parse_release_notes — pure Python, no GUI."""
from zig.whats_new import parse_release_notes


STANDARD_BODY = (
    "## What's Changed\n"
    "* feat: nice popup window by @calebohara in #5\n"
    "* fix: typo in tray tooltip by @calebohara in #6\n"
    "* feat!: breaking change by @z in #7\n"
    "\n"
    "**Full Changelog**: https://github.com/x/y/compare/v0.3.0...v0.3.1\n"
)


class TestParseReleaseNotes:
    def test_feat_goes_to_added(self):
        result = parse_release_notes(STANDARD_BODY)
        assert "nice popup window" in result.sections["Added"]

    def test_breaking_feat_goes_to_added(self):
        result = parse_release_notes(STANDARD_BODY)
        assert "breaking change" in result.sections["Added"]

    def test_fix_goes_to_fixed(self):
        result = parse_release_notes(STANDARD_BODY)
        assert "typo in tray tooltip" in result.sections["Fixed"]

    def test_full_changelog_trailer_stripped(self):
        result = parse_release_notes(STANDARD_BODY)
        for items in result.sections.values():
            for item in items:
                assert "Full Changelog" not in item
        assert not any("Full Changelog" in o for o in result.other)

    def test_empty_body_no_throw(self):
        result = parse_release_notes("")
        assert all(not v for v in result.sections.values())
        assert not result.other

    def test_only_changelog_trailer(self):
        body = "**Full Changelog**: https://github.com/x/y/compare/v0.3.3...v0.3.4\n"
        result = parse_release_notes(body)
        assert all(not v for v in result.sections.values())
        assert not result.other

    def test_attribution_stripped(self):
        result = parse_release_notes(STANDARD_BODY)
        for items in result.sections.values():
            for item in items:
                assert "by @" not in item
                assert "in #" not in item

    def test_sections_keys_present(self):
        result = parse_release_notes(STANDARD_BODY)
        expected_keys = {"Added", "Fixed", "Changed", "Removed", "Docs"}
        assert expected_keys.issubset(result.sections.keys())
