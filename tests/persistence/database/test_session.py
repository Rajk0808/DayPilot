import ast
from pathlib import Path

from daypilot.persistence.database.engine import create_database_engine
from daypilot.persistence.database.config import DatabaseSettings
from daypilot.persistence.database.session import create_session_factory


def test_session_factory_creates_a_fresh_session_each_time(tmp_path):
    database_path = tmp_path / "sessions.sqlite"
    engine = create_database_engine(
        DatabaseSettings(database_url=f"sqlite:///{database_path.as_posix()}")
    )
    factory = create_session_factory(engine)
    first = factory()
    second = factory()
    try:
        assert first is not second
        assert first.bind is engine
        assert second.bind is engine
    finally:
        first.close()
        second.close()
        engine.dispose()


def test_database_infrastructure_does_not_import_domain_or_application():
    source_root = Path(__file__).parents[3] / "src" / "daypilot" / "persistence" / "database"
    for source_file in source_root.glob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        imported_modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)
        assert not any(
            module.startswith(("daypilot.domain", "daypilot.application"))
            for module in imported_modules
        ), source_file
