"""Cross-platform bytes, manifest identities, and accepted-revision reuse."""
import hashlib
import stat

import pytest

from fluxos.agent import Workspace


def test_written_bytes_match_reported_hash(tmp_path):
    work=Workspace(tmp_path/'work')
    text='print("hello")\n# Unicode: café\n'
    result=work.write_file('src/main.py',text)
    data=(work.path/'src'/'main.py').read_bytes()
    assert data==text.encode('utf8')
    digest=hashlib.sha256(data).hexdigest()
    assert result['sha256']==digest[:16]
    assert work.file_manifest()=={'src/main.py':digest}


def test_nested_snapshot_keeps_portable_manifest_and_exact_bytes(tmp_path):
    source=Workspace(tmp_path/'source')
    source.write_file('src/package/main.py','print(42)\n')
    target=Workspace(tmp_path/'target')
    manifest=source.snapshot_to(target)
    assert list(manifest)==['src/package/main.py']
    assert manifest==source.file_manifest()==target.file_manifest()
    assert (source.path/'src/package/main.py').read_bytes()==(target.path/'src/package/main.py').read_bytes()


def test_private_copy_of_readonly_revision_is_editable(tmp_path):
    source=Workspace(tmp_path/'accepted')
    source.write_file('main.py','print(1)\n')
    original=source.file_manifest()
    path=source.path/'main.py'
    path.chmod(0o444)
    try:
        private=Workspace(tmp_path/'candidate')
        source.snapshot_to(private)
        private.write_file('main.py','print(2)\n')
        assert private.read_file('main.py')=='print(2)\n'
        assert source.file_manifest()==original
        assert not path.stat().st_mode & stat.S_IWUSR
    finally:
        path.chmod(0o644)


@pytest.mark.parametrize('name',['../outside.py','/outside.py','sub\\main.py'])
def test_portable_manifest_does_not_relax_unsafe_input_rejection(tmp_path,name):
    with pytest.raises(ValueError):
        Workspace(tmp_path/'work').write_file(name,'pass\n')
