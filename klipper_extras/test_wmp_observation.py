"""Status copies preserve data and isolate edits without reconstructing scalars."""
from wmp_observation import copy_status


def test_status_tree_copy_is_independent_and_retains_tuples():
    original = ({'heads': [{'identity': {'material': 'PLA'}, 'loaded': True}], 'value': None}, 'revision')
    result = copy_status(original)
    assert result == original and isinstance(result, tuple)
    result[0]['heads'][0]['identity']['material'] = 'PETG'
    assert original[0]['heads'][0]['identity']['material'] == 'PLA'


def test_unfamiliar_value_retains_its_copy_protocol():
    class Record:
        def __deepcopy__(self, memo): return 'copied'
    assert copy_status({'record': Record()}) == {'record': 'copied'}
