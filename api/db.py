from contextlib import contextmanager
import pymysql
from pymysql.cursors import DictCursor
from pymongo import MongoClient
from . import config

_mongo_client = None


@contextmanager
def mysql_conn():
    conn = pymysql.connect(cursorclass=DictCursor, autocommit=False, **config.MYSQL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def mongo_db():
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=5000, tz_aware=False)
    return _mongo_client[config.MONGO_DB]
