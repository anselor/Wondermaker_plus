from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import pytest

@pytest.fixture(scope="session", autouse=True)
def native_build_output_directory():
    (Path(__file__).resolve().parents[1] / "build").mkdir(exist_ok=True)


@pytest.fixture
def native_client_elf():
    path=Path(__file__).resolve().parents[4]/'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'
    if not path.is_file():pytest.skip('local vendor1.1.13 client payload not present; native ABI proof requires that optional fixture')
    return path
