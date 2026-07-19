import pytest

from app.services.storage import safe_resolve


def test_jail_allows_inside(settings):
    settings.ensure_dirs()
    path = safe_resolve(settings, "originals/ab/file.jpg")
    assert str(path).startswith(str(settings.data_dir.resolve()))


@pytest.mark.parametrize("evil", [
    "../outside.txt",
    "originals/../../etc/passwd",
    "..\\..\\windows\\system32",
])
def test_jail_blocks_traversal(settings, evil):
    with pytest.raises(PermissionError):
        safe_resolve(settings, evil)
