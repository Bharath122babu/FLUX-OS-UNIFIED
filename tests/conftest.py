"""Platform capabilities required by filesystem security tests."""
import os

import pytest


@pytest.fixture
def create_symlink():
    def create(link, target):
        try:
            link.symlink_to(target, target_is_directory=target.is_dir())
        except OSError as exc:
            # Skip only the specific Windows privilege failure. Other errors
            # remain failures so this cannot hide a broken symlink test.
            if os.name == 'nt' and exc.winerror == 1314:
                pytest.skip('Windows symlink privilege unavailable; enable Developer Mode or use a privileged test session')
            raise
    return create
