"""Host configuration must not depend on Windows' locale or editor BOMs."""
import importlib.util
from pathlib import Path


def test_utf8_bom_environment_file(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'tools/local_env.py'
    spec = importlib.util.spec_from_file_location('host_local_env', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.delenv('WMP_TEST_UNICODE', raising=False)
    env = tmp_path / '.env'
    env.write_bytes('\ufeffWMP_TEST_UNICODE=café日本\r\n'.encode('utf-8'))
    module.load_local_env(env)
    assert module.os.environ['WMP_TEST_UNICODE'] == 'café日本'
    monkeypatch.delenv('WMP_TEST_UNICODE')
