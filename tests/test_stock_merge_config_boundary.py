"""Characterize startup's retained vendor merger using disposable files only."""
import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / (
    'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/scripts/merge_config.py')


def test_startup_defaults_merge_overwrites_intervening_saved_state(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('stock_merge_characterization', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path / 'saved_variables.cfg'
    factory = tmp_path / 'factory.cfg'
    target.write_text('[Variables]\ncurrent_extruder=0\n')
    factory.write_text('[Variables]\ncurrent_extruder=0\nnew_factory_option=1\n')
    original_read = module.configparser.ConfigParser.read

    def read_then_backend_save(parser, filename, *args, **kwargs):
        result = original_read(parser, filename, *args, **kwargs)
        if filename == str(factory):
            # SAVE_VARIABLE publishes after the merger captured its old snapshot.
            target.write_text('[Variables]\ncurrent_extruder=3\nwmp_print_context=retained\n')
        return result

    monkeypatch.setattr(module.configparser.ConfigParser, 'read', read_then_backend_save)
    module.merge_configs(str(target), str(factory))
    result = target.read_text()
    assert 'new_factory_option=1' in result
    assert 'current_extruder=0' in result
    assert 'wmp_print_context' not in result
