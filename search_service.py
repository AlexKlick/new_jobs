import sys

from search import search_service as _impl

sys.modules[__name__] = _impl
