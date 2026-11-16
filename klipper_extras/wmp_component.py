# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit state compatibility for the wm_material Klipper facade."""


def component_state(accessor, name):
    """Expose one named component field without duplicating its mutable state."""
    def read(owner):
        return getattr(getattr(owner, accessor)(), name)

    def write(owner, value):
        setattr(getattr(owner, accessor)(), name, value)

    def remove(owner):
        delattr(getattr(owner, accessor)(), name)

    return property(read, write, remove)


class component_method:
    """Expose a named feature method, retaining its bound identity and signature."""
    def __init__(self, accessor, name, class_method=None):
        self.accessor, self.name = accessor, name
        self.class_method = class_method

    def __get__(self, owner, owner_type=None):
        if owner is None:
            if self.class_method is not None:
                return self.class_method
            implementation = getattr(getattr(owner_type, self.accessor).component_type, self.name)
            def dispatch(instance, *args, **kwargs):
                feature = getattr(instance, self.accessor)()
                return implementation(feature, *args, **kwargs)
            return dispatch
        return getattr(getattr(owner, self.accessor)(), self.name)


def component_accessor(component_type, storage):
    """Build one lazy, per-printer component accessor with explicit ownership."""
    def get(owner):
        feature = getattr(owner, storage, None)
        if feature is None:
            feature = component_type(owner)
            setattr(owner, storage, feature)
        return feature

    get.component_type = component_type
    return get
