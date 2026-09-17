"""Paridad entre la documentación, el `.env.example` y el CLI.

Estas pruebas evitan el fallo más repetido del repositorio: documentar una
variable o un comando que ya no existe, u olvidar documentar uno nuevo. No
comprueban la redacción, sino la existencia cruzada.
"""

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = PROJECT_ROOT / "fortnite_research"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class EnvironmentParityTests(unittest.TestCase):
    def test_every_documented_variable_is_read_by_config(self):
        documented = {
            match.group(1)
            for match in re.finditer(
                r"^([A-Z][A-Z0-9_]+)=",
                _read(PROJECT_ROOT / ".env.example"),
                re.MULTILINE,
            )
        }
        config_source = _read(PACKAGE / "config.py")
        read_by_code = set(re.findall(r'_env\(\s*"([A-Z][A-Z0-9_]+)"', config_source))

        self.assertTrue(documented)
        self.assertEqual(
            documented - read_by_code,
            set(),
            "Hay variables en .env.example que config.py no lee",
        )

    def test_every_variable_read_by_config_is_documented(self):
        config_source = _read(PACKAGE / "config.py")
        read_by_code = set(re.findall(r'_env\(\s*"([A-Z][A-Z0-9_]+)"', config_source))
        documented = {
            match.group(1)
            for match in re.finditer(
                r"^([A-Z][A-Z0-9_]+)=",
                _read(PROJECT_ROOT / ".env.example"),
                re.MULTILINE,
            )
        }

        self.assertEqual(
            read_by_code - documented,
            set(),
            "Hay variables que lee config.py y no están en .env.example",
        )


class CliDocumentationParityTests(unittest.TestCase):
    def test_every_subcommand_is_documented_in_readme(self):
        cli_source = _read(PACKAGE / "cli.py")
        commands = set(
            re.findall(r'sub\.add_parser\(\s*"([a-z0-9-]+)"', cli_source)
        )
        readme = _read(PROJECT_ROOT / "README.md")
        documented = set(re.findall(r"fortnite_research\s+([a-z0-9-]+)", readme))

        self.assertTrue(commands)
        self.assertEqual(
            commands - documented,
            set(),
            "Hay subcomandos que no aparecen en el README",
        )

    def test_every_bot_flag_is_documented(self):
        readme = _read(PROJECT_ROOT / "README.md")

        for flag in ("--once", "--dry-run", "--send", "--image", "--caption"):
            with self.subTest(flag=flag):
                self.assertIn(flag, readme)


class RepositoryHygieneTests(unittest.TestCase):
    def test_readme_code_fences_are_balanced(self):
        fences = [
            line
            for line in _read(PROJECT_ROOT / "README.md").splitlines()
            if line.strip().startswith("```")
        ]

        self.assertEqual(
            len(fences) % 2,
            0,
            "El README tiene un bloque de código sin cerrar",
        )

    def test_license_and_metadata_exist(self):
        pyproject = _read(PROJECT_ROOT / "pyproject.toml")

        self.assertTrue((PROJECT_ROOT / "LICENSE").is_file())
        for field in ('readme = "README.md"', "license", "classifiers", "authors"):
            with self.subTest(field=field):
                self.assertIn(field, pyproject)

    def test_gitignore_protects_credentials_and_heavy_documents(self):
        gitignore = _read(PROJECT_ROOT / ".gitignore")

        for pattern in (".env", "*.pem", "*.key", "*.pptx", "*.docx"):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, gitignore)

    def test_ci_runs_lint_and_does_not_hide_matrix_failures(self):
        workflow = _read(PROJECT_ROOT / ".github" / "workflows" / "tests.yml")

        self.assertIn("fail-fast: false", workflow)
        self.assertIn("ruff check .", workflow)
        self.assertIn("windows-latest", workflow)


if __name__ == "__main__":
    unittest.main()
