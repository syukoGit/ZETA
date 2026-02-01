from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

DB_URL = "sqlite+pysqlite:///zeta.sqlite"

engine = create_engine(
    DB_URL,
    future=True,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@event.listens_for(Engine, "connect")
def set_sqlite_pragmas(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("PRAGMA journal_mode = WAL;")     # meilleure concurrence lecture/écriture
    cursor.execute("PRAGMA synchronous = NORMAL;")   # compromis perf/sécurité
    cursor.execute("PRAGMA busy_timeout = 5000;")    # évite certains 'database is locked'
    cursor.close()