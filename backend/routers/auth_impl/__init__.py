"""Auth route registration.

Importing this package registers every auth endpoint onto the shared
`deps.api` FastAPI router. The public entry point remains
`routers.auth` — this package is an internal split, not a rename.

Order matters slightly: `_common` establishes the module-level helpers and
imports; the topical submodules use them via `from ._common import *`.
Importing the topical modules is what actually attaches routes to `api`.
"""
from . import _common  # noqa: F401  (imports must run before topical modules)
from . import registration  # noqa: F401
from . import refresh  # noqa: F401
from . import sessions  # noqa: F401
from . import mfa  # noqa: F401
from . import profile  # noqa: F401
from . import password_reset  # noqa: F401
from . import bootstrap  # noqa: F401
