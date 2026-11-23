"""Shared test setup: build small databases and hand out connections."""

import atexit
import os
import tempfile
import unittest

from tuning import db, seed

# Keep the temporary folders alive until the program ends, then delete them.
_folders = []
_shared = {}


# Build a new database with `rows` fact rows and return its file path.
def make_db(rows):
    folder = tempfile.TemporaryDirectory()
    _folders.append(folder)
    atexit.register(folder.cleanup)
    path = os.path.join(folder.name, "test.db")
    conn = db.connect(path)
    seed.build(conn, rows)
    conn.close()
    return path


# The 100,000-row database that the case tests share. Built once per test run.
def shared_db_path():
    if "path" not in _shared:
        _shared["path"] = make_db(seed.SMALL_ROWS)
    return _shared["path"]


# Base class for tests that need the shared 100,000-row database.
# Every test starts and ends with no lab indexes, so tests cannot affect each other.
class SharedDbTestCase(unittest.TestCase):
    rows = seed.SMALL_ROWS

    # Open a connection and remove any lab indexes.
    def setUp(self):
        self.conn = db.connect(shared_db_path())
        db.drop_lab_indexes(self.conn)

    # Remove the indexes again and close the connection (Windows needs this
    # before it can delete the file).
    def tearDown(self):
        db.drop_lab_indexes(self.conn)
        self.conn.close()
