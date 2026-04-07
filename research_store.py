import sys

from research import research_store as _impl

sys.modules[__name__] = _impl
