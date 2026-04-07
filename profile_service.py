"""Compatibility shim for the canonical ``research.profile_service`` module."""

import sys

from research import profile_service as _impl

sys.modules[__name__] = _impl
