from types import SimpleNamespace

from decisiongraph.infrastructure import database_bootstrap, graph_bootstrap


class Cursor:
    def __init__(self):
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, statement):
        self.statements.append(statement)


class Connection:
    def __init__(self):
        self.cursor_value = Cursor()
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.committed = True


def test_database_bootstrap_executes_all_migrations(monkeypatch):
    connection = Connection()
    monkeypatch.setattr(
        database_bootstrap, "get_settings", lambda: SimpleNamespace(postgres_url="x")
    )
    monkeypatch.setattr(database_bootstrap.psycopg, "connect", lambda _url: connection)
    database_bootstrap.main()
    assert connection.committed
    assert len(connection.cursor_value.statements) == len(database_bootstrap.MIGRATIONS)


def test_graph_bootstrap_executes_constraints(monkeypatch):
    statements = []

    class Result:
        def consume(self):
            return None

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def run(self, statement):
            statements.append(statement)
            return Result()

    class Driver:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def verify_connectivity(self):
            return None

        def session(self):
            return Session()

    settings = SimpleNamespace(
        neo4j_uri="bolt://x",
        neo4j_username="u",
        neo4j_password="p",  # noqa: S106 - non-secret test fixture
    )
    monkeypatch.setattr(graph_bootstrap, "get_settings", lambda: settings)
    monkeypatch.setattr(graph_bootstrap.GraphDatabase, "driver", lambda *_a, **_k: Driver())
    graph_bootstrap.main()
    assert statements == list(graph_bootstrap.CONSTRAINTS)
