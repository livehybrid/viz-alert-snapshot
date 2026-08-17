"""
Pytest bootstrap — put the app's importable Python (bin/lib) on sys.path so the
sender/deliver modules can be unit-tested without a running Splunk.

bin/lib is *appended* (not prepended) so it never shadows a stdlib module of the
same name (notably `secrets`); the code under test that needs the app's secrets
module is the render path, which these hermetic tests don't exercise.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(REPO_ROOT, "bin", "lib")
if LIB not in sys.path:
    sys.path.append(LIB)
