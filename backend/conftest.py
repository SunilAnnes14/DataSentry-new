"""Pytest bootstrap: isolate tests from the developer's data directory.

Environment variables must be set before ``config`` is imported anywhere.
"""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="datasentry-test-")
os.environ["DATASENTRY_DATA_DIR"] = _tmp
os.environ["DATASENTRY_EXPERIMENTS_DIR"] = os.path.join(_tmp, "experiments")
os.environ["DATASENTRY_BLOCKCHAIN_ENABLED"] = "false"
