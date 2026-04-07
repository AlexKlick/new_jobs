import sys

from search import search_store as _impl

sys.modules[__name__] = _impl
