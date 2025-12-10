"""Tests für projekt_aggregator.py"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

# Import des zu testenden Moduls
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from projekt_aggregator import (
    AggregatorConfig,
    get_language,
    should_ignore,
    generate_tree,
    collect_files,
    read_file_safely,
    merge_files,
    collect_context_files,
    generate_context_prompt,
)


class TestGetLanguage:
    """Tests für die Sprach-Erkennung."""

    def test_python_extension(self):
        assert get_language(".py") == "python"

    def test_javascript_extension(self):
        assert get_language(".js") == "javascript"

    def test_typescript_extension(self):
        assert get_language(".ts") == "typescript"

    def test_markdown_extension(self):
        assert get_language(".md") == "markdown"

    def test_yaml_extension(self):
        assert get_language(".yaml") == "yaml"
        assert get_language(".yml") == "yaml"

    def test_unknown_extension(self):
        assert get_language(".xyz") == "text"

    def test_case_insensitive(self):
        assert get_language(".PY") == "python"
        assert get_language(".Md") == "markdown"


class TestShouldIgnore:
    """Tests für das Ignore-Pattern-Matching."""

    def test_exact_match(self):
        assert should_ignore("node_modules", ["node_modules"]) is True
        assert should_ignore("src", ["node_modules"]) is False

    def test_prefix_wildcard(self):
        # *.pyc sollte test.pyc matchen
        assert should_ignore("test.pyc", ["*.pyc"]) is True
        assert should_ignore("test.py", ["*.pyc"]) is False

    def test_suffix_wildcard(self):
        # tmp* sollte tmpxyz matchen
        assert should_ignore("tmpxyz", ["tmp*"]) is True
        assert should_ignore("mytmp", ["tmp*"]) is False

    def test_egg_info_pattern(self):
        assert should_ignore("mypackage.egg-info", ["*.egg-info"]) is True
        assert should_ignore("mypackage", ["*.egg-info"]) is False

    def test_multiple_patterns(self):
        patterns = ["*.pyc", "node_modules", "tmp*"]
        assert should_ignore("test.pyc", patterns) is True
        assert should_ignore("node_modules", patterns) is True
        assert should_ignore("tmpfile", patterns) is True
        assert should_ignore("src", patterns) is False


class TestGenerateTree:
    """Tests für die Verzeichnisbaum-Generierung."""

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = AggregatorConfig(root_path=tmpdir)
            tree = generate_tree(tmpdir, config)

            assert "# VERZEICHNISSTRUKTUR" in tree
            assert "```text" in tree
            assert "```" in tree

    def test_single_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Erstelle eine Python-Datei
            (Path(tmpdir) / "main.py").write_text("print('hello')")

            config = AggregatorConfig(root_path=tmpdir)
            tree = generate_tree(tmpdir, config)

            assert "main.py" in tree

    def test_nested_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Erstelle verschachtelte Struktur
            src = Path(tmpdir) / "src"
            src.mkdir()
            (src / "main.py").write_text("# main")
            (src / "utils.py").write_text("# utils")

            config = AggregatorConfig(root_path=tmpdir)
            tree = generate_tree(tmpdir, config)

            assert "src/" in tree
            assert "main.py" in tree
            assert "utils.py" in tree

    def test_ignores_folders(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Erstelle node_modules (sollte ignoriert werden)
            nm = Path(tmpdir) / "node_modules"
            nm.mkdir()
            (nm / "package.json").write_text("{}")

            # Erstelle src (sollte nicht ignoriert werden)
            src = Path(tmpdir) / "src"
            src.mkdir()
            (src / "main.py").write_text("# main")

            config = AggregatorConfig(root_path=tmpdir)
            tree = generate_tree(tmpdir, config)

            assert "node_modules" not in tree
            assert "src/" in tree


class TestCollectFiles:
    """Tests für das Sammeln von Dateien."""

    def test_collects_matching_extensions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "main.py").write_text("# python")
            (Path(tmpdir) / "readme.md").write_text("# readme")
            (Path(tmpdir) / "data.json").write_text("{}")

            config = AggregatorConfig(
                root_path=tmpdir,
                extensions=[".py", ".md"]
            )
            files = collect_files(tmpdir, config)

            filenames = [f.name for f in files]
            assert "main.py" in filenames
            assert "readme.md" in filenames
            assert "data.json" not in filenames

    def test_ignores_folders(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Erstelle __pycache__ (sollte ignoriert werden)
            cache = Path(tmpdir) / "__pycache__"
            cache.mkdir()
            (cache / "main.cpython-311.pyc").write_text("")

            # Erstelle src
            (Path(tmpdir) / "main.py").write_text("# main")

            config = AggregatorConfig(root_path=tmpdir)
            files = collect_files(tmpdir, config)

            assert len(files) == 1
            assert files[0].name == "main.py"

    def test_skips_output_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "main.py").write_text("# python")
            (Path(tmpdir) / "projekt_komplett.md").write_text("# output")

            config = AggregatorConfig(
                root_path=tmpdir,
                output_filename="projekt_komplett.md"
            )
            files = collect_files(tmpdir, config)

            filenames = [f.name for f in files]
            assert "main.py" in filenames
            assert "projekt_komplett.md" not in filenames


class TestReadFileSafely:
    """Tests für sicheres Dateilesen."""

    def test_reads_utf8_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.py"
            filepath.write_text("# Ümläüte und Sönderzeichen", encoding="utf-8")

            content, error = read_file_safely(filepath, max_size_kb=1024)

            assert error is None
            assert "Ümläüte" in content

    def test_reads_latin1_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.txt"
            filepath.write_bytes(b"Caf\xe9")  # Latin-1 encoded "Café"

            content, error = read_file_safely(filepath, max_size_kb=1024)

            assert error is None
            assert "Caf" in content

    def test_rejects_large_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "large.txt"
            # Erstelle 2KB Datei
            filepath.write_text("x" * 2048)

            content, error = read_file_safely(filepath, max_size_kb=1)

            assert content is None
            assert "zu groß" in error

    def test_handles_missing_file(self):
        filepath = Path("/nonexistent/file.txt")
        content, error = read_file_safely(filepath, max_size_kb=1024)

        assert content is None
        assert error is not None


class TestMergeFiles:
    """Tests für die Hauptfunktion merge_files."""

    def test_creates_output_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "main.py").write_text("print('hello')")

            config = AggregatorConfig(
                root_path=tmpdir,
                output_filename="output.md",
                projekt_beschreibung="# Test Projekt"
            )
            stats = merge_files(config)

            output_path = Path(tmpdir) / "output.md"
            assert output_path.exists()
            assert stats["files_processed"] == 1

    def test_output_contains_all_sections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "main.py").write_text("print('hello')")

            config = AggregatorConfig(
                root_path=tmpdir,
                output_filename="output.md",
                projekt_beschreibung="# PROJEKTBESCHREIBUNG\nTestprojekt"
            )
            merge_files(config)

            content = (Path(tmpdir) / "output.md").read_text()

            assert "# VERZEICHNISSTRUKTUR" in content
            assert "# PROJEKTBESCHREIBUNG" in content
            assert "# DATEIINHALTE" in content
            assert "## DATEI: ./main.py" in content
            assert "```python" in content
            assert "print('hello')" in content

    def test_handles_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = AggregatorConfig(
                root_path=tmpdir,
                output_filename="output.md"
            )
            stats = merge_files(config)

            assert stats["files_processed"] == 0
            assert (Path(tmpdir) / "output.md").exists()

    def test_multiple_files_sorted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "zebra.py").write_text("# z")
            (Path(tmpdir) / "alpha.py").write_text("# a")
            (Path(tmpdir) / "beta.py").write_text("# b")

            config = AggregatorConfig(
                root_path=tmpdir,
                output_filename="output.md"
            )
            merge_files(config)

            content = (Path(tmpdir) / "output.md").read_text()

            # Prüfe Reihenfolge
            alpha_pos = content.find("alpha.py")
            beta_pos = content.find("beta.py")
            zebra_pos = content.find("zebra.py")

            assert alpha_pos < beta_pos < zebra_pos

    def test_stdout_output(self, capsys):
        """Test output to stdout with '-'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.py").write_text("print('hello')")

            config = AggregatorConfig(
                root_path=tmpdir,
                output_filename="-"  # stdout
            )
            stats = merge_files(config, quiet=True)

            captured = capsys.readouterr()
            assert "# VERZEICHNISSTRUKTUR" in captured.out
            assert "# DATEIINHALTE" in captured.out
            assert "## DATEI: ./test.py" in captured.out
            assert "```python" in captured.out
            assert stats["files_processed"] == 1
            # Keine Datei sollte erstellt werden
            assert not (Path(tmpdir) / "-").exists()


class TestIntegration:
    """Integrationstests für den gesamten Workflow."""

    def test_full_project_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Erstelle realistische Projektstruktur
            root = Path(tmpdir)

            # docs/
            docs = root / "docs"
            docs.mkdir()
            (docs / "README.md").write_text("# Dokumentation")
            (docs / "architecture.md").write_text("# Architektur")

            # src/
            src = root / "src"
            src.mkdir()
            (src / "__init__.py").write_text("")
            (src / "main.py").write_text("def main(): pass")
            (src / "utils.py").write_text("def helper(): pass")

            # tests/
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_main.py").write_text("def test_main(): pass")

            # config
            (root / "config.yaml").write_text("debug: true")

            # Ignorierte Ordner
            cache = root / "__pycache__"
            cache.mkdir()
            (cache / "main.cpython-311.pyc").write_text("")

            config = AggregatorConfig(
                root_path=tmpdir,
                output_filename="projekt.md",
                projekt_beschreibung="# PROJEKTBESCHREIBUNG\nIntegrationstest"
            )
            stats = merge_files(config)

            content = (root / "projekt.md").read_text()

            # Struktur prüfen
            assert "docs/" in content
            assert "src/" in content
            assert "tests/" in content
            assert "__pycache__" not in content

            # Dateien prüfen
            assert "README.md" in content
            assert "main.py" in content
            assert "config.yaml" in content

            # Stats prüfen
            assert stats["files_processed"] == 7
            assert stats["files_skipped"] == 0


class TestGenerateContextPrompt:
    """Tests für die KI-Prompt-Generierung."""

    def test_collects_readme(self):
        """Test dass README.md gesammelt wird."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "README.md").write_text("# Test Project\nDescription here")

            files = collect_context_files(tmpdir)

            assert len(files) >= 1
            assert any("README.md" in f[0] for f in files)

    def test_collects_docs_folder(self):
        """Test dass docs/ Ordner durchsucht wird."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            docs = root / "docs"
            docs.mkdir()
            (docs / "ARCHITECTURE.md").write_text("# Architecture")
            (docs / "design.md").write_text("# Design")

            files = collect_context_files(tmpdir)

            paths = [f[0] for f in files]
            assert any("ARCHITECTURE.md" in p for p in paths)
            assert any("design.md" in p for p in paths)

    def test_collects_config_files(self):
        """Test dass Konfigurationsdateien gesammelt werden."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text('[project]\nname = "test"')
            (root / "package.json").write_text('{"name": "test"}')

            files = collect_context_files(tmpdir)

            paths = [f[0] for f in files]
            assert "pyproject.toml" in paths
            assert "package.json" in paths

    def test_generate_prompt_structure(self):
        """Test dass der generierte Prompt die richtige Struktur hat."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "README.md").write_text("# My Project")
            (root / "main.py").write_text("print('hello')")

            prompt = generate_context_prompt(tmpdir)

            # Prompt-Template Struktur
            assert "Software-Architekt" in prompt
            assert "Projektinformationen" in prompt
            assert "PROJEKTBESCHREIBUNG" in prompt

            # Projektkontext
            assert "Projektverzeichnis:" in prompt
            assert "Verzeichnisstruktur" in prompt
            assert "README.md" in prompt

    def test_respects_max_chars(self):
        """Test dass max_total_chars respektiert wird."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            # Große Datei erstellen
            (root / "README.md").write_text("# Test\n" + "x" * 10000)

            prompt = generate_context_prompt(tmpdir, max_total_chars=5000)

            # Prompt sollte gekürzt sein
            assert len(prompt) < 10000
            assert "gekürzt" in prompt or len(prompt) < 6000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
