import sys

from generation import generation_orchestrator as _impl

sys.modules[__name__] = _impl
