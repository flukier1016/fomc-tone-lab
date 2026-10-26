"""The active submission has one integrated deck, not a separate technical appendix."""

import importlib.util
import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "package_submission", Path(__file__).resolve().parents[1] / "scripts" / "package_submission.py"
)
submission = importlib.util.module_from_spec(spec)
spec.loader.exec_module(submission)
spec = importlib.util.spec_from_file_location(
    "test_inventory", Path(__file__).resolve().parents[1] / "scripts" / "test_inventory.py"
)
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


def _presentation(path, count):
    ns = "http://schemas.openxmlformats.org/presentationml/2006/main"
    document = ET.Element(f"{{{ns}}}presentation")
    ids = ET.SubElement(document, f"{{{ns}}}sldIdLst")
    for i in range(count):
        ET.SubElement(ids, f"{{{ns}}}sldId", id=str(256 + i))
    with zipfile.ZipFile(path, "w") as deck:
        deck.writestr("ppt/presentation.xml", ET.tostring(document))


def test_slide_export_defaults_to_integrated_main_and_keeps_legacy_options():
    from fomc.cli import parser

    assert parser().parse_args(["slides"]).deck == "main"
    assert parser().parse_args(["slides", "--deck", "technical"]).deck == "technical"
    assert parser().parse_args(["slides", "--deck", "all"]).deck == "all"


def test_package_lists_only_four_active_deliverables_and_reads_actual_slide_count(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    source = repo / "docs" / "slides"
    source.mkdir(parents=True)
    _presentation(source / "FOMC-Tone-Lab-editable.pptx", 13)  # deliberately different from the current deck
    out = tmp_path / "submission"
    out.mkdir()
    (out / "FOMC-Tone-Lab.pdf").write_bytes(b"reviewed integrated deck")
    (out / "FOMC-Tone-Lab-writeup.pdf").write_bytes(b"reviewed write-up")
    legacy = out / "FOMC-Tone-Lab-technical.pdf"
    legacy.write_bytes(b"preserve historical export")
    (out / "SHA256SUMS.txt").write_text("stale checksums from an earlier package\n")
    monkeypatch.setattr(submission, "ROOT", repo)
    revision = "a" * 40

    def git_output(args, cwd, text):
        assert cwd == repo and text
        if args[:2] == ["git", "status"]:
            return ""  # a clean tree
        return revision + "\n" if args == ["git", "rev-parse", "HEAD"] else "aaaaaaa\n"

    def git_archive(args, cwd, check):
        assert cwd == repo and check and args[:4] == ["git", "archive", "--format=zip", "-o"]
        assert args[-1] == "HEAD"
        with zipfile.ZipFile(args[4], "w") as archive:
            archive.writestr("deploy/fomc.db.gz", "snapshot")
            archive.writestr("src/fomc/__init__.py", "")

    monkeypatch.setattr(submission.subprocess, "check_output", git_output)
    monkeypatch.setattr(submission.subprocess, "run", git_archive)
    submission.package(out)
    manifest = (out / "SUBMISSION.md").read_text()
    assert "13 slides: introduction, methods, results and implementation" in manifest
    assert "Deadline" not in manifest and "SHA256" not in manifest  # a guide for graders, not a packing note
    assert "Team contributions" not in manifest and "【填写】" not in manifest
    assert legacy.read_bytes() == b"preserve historical export"
    assert "FOMC-Tone-Lab-technical" not in manifest
    assert "https://github.com/flukier1016/fomc-tone-lab" in manifest  # graders can open the code online
    assert not (out / "SHA256SUMS.txt").exists()
    for name in [
        "FOMC-Tone-Lab.pdf",
        "FOMC-Tone-Lab-editable.pptx",
        "FOMC-Tone-Lab-writeup.pdf",
        "fomc-tone-duration-aaaaaaa.zip",
    ]:
        assert f"`{name}`" in manifest and (out / name).is_file()


@pytest.mark.parametrize(
    "status,older,expect,message",
    [
        (" M docs/slides/FOMC-Tone-Lab-editable.pptx\n", False, None, "Commit tracked changes first"),
        ("", True, None, "Archive the previous package first"),
        ("", False, "bbbb", "not the expected revision"),
    ],
)
def test_package_refuses_a_dirty_tree_an_older_zip_and_the_wrong_revision(
    tmp_path, monkeypatch, status, older, expect, message
):
    repo, out = tmp_path / "repo", tmp_path / "submission"
    out.mkdir()
    if older:
        (out / "fomc-tone-duration-1234567.zip").write_bytes(b"previous package")
    monkeypatch.setattr(submission, "ROOT", repo)

    def git_output(args, cwd, text):
        if args[:2] == ["git", "status"]:
            return status
        return "a" * 40 + "\n" if args == ["git", "rev-parse", "HEAD"] else "aaaaaaa\n"

    monkeypatch.setattr(submission.subprocess, "check_output", git_output)
    monkeypatch.setattr(submission.subprocess, "run", lambda *a, **k: pytest.fail("archived despite the guard"))
    with pytest.raises(SystemExit, match=message):
        submission.package(out, expect)


def test_package_rejects_an_empty_deck(tmp_path):
    path = tmp_path / "empty.pptx"
    _presentation(path, 0)
    with pytest.raises(SystemExit, match="no slides"):
        submission.slide_count(path)


def test_the_readme_badge_counts_the_tests_this_revision_collects():
    readme = (inventory.ROOT / "README.md").read_text()
    assert f"tests-{json.loads(inventory.OUT.read_text())['tests']}%20passing" in readme


def test_the_deck_counts_the_tests_this_revision_collects():
    """The test slide reads src/fomc/test_inventory.json; after adding tests, run make inventory."""
    assert json.loads(inventory.OUT.read_text()) == inventory.collect()
