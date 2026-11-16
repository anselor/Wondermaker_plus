"""Compatibility boundaries must preserve state ownership and injected failures."""
from wmp_component import component_accessor, component_method, component_state


class Feature:
    def __init__(self, owner):
        self.material = owner
        self.record = {}

    def action(self):
        return 'original'

    @staticmethod
    def decode(value):
        return value + 1


class Facade:
    feature = component_accessor(Feature, '_feature')
    record = component_state('feature', 'record')
    action = component_method('feature', 'action')
    decode = component_method('feature', 'decode', Feature.decode)


def test_state_has_one_owner_and_is_not_shared_between_printers():
    first, second = Facade(), Facade()
    first.record['state'] = 'running'
    assert first.record is first.feature().record
    assert second.record == {}
    del first.record
    assert not hasattr(first, 'record')
    first.record = {'state': 'complete'}
    assert first.feature().record == {'state': 'complete'}
    assert second.record == {}


def test_saved_bound_method_survives_later_fault_injection():
    owner = Facade()
    original = owner.action
    owner.feature().action = lambda: 'injected failure'
    assert owner.action() == 'injected failure'
    assert original() == 'original'


def test_static_calls_remain_compatible_on_class_and_instance():
    owner = Facade()
    assert Facade.decode(1) == owner.decode(1) == 2
    owner.feature().decode = lambda value: value - 1
    assert owner.decode(1) == 0
    assert Facade.decode(1) == 2


def test_class_call_can_reach_original_implementation_after_injection():
    owner = Facade()
    owner.feature().action = lambda: 'injected failure'
    assert owner.action() == 'injected failure'
    assert Facade.action(owner) == 'original'
