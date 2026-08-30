from .providers.chase import (
    ChaseTerminalProvider,
)
from .providers.square import (
    SquareTerminalProvider,
)
from .providers.stripe_terminal import (
    StripeTerminalProvider,
)
from .providers.generic import (
    GenericTerminalProvider,
)


_PROVIDER_CLASSES = {
    "chase": ChaseTerminalProvider,
    "square": SquareTerminalProvider,
    "stripe_terminal":
        StripeTerminalProvider,
    "generic": GenericTerminalProvider,
}


def provider_class(name: str):
    try:
        return _PROVIDER_CLASSES[name]
    except KeyError:
        raise ValueError(
            f"Unsupported terminal provider: {name}"
        )


def supported_terminal_providers():
    return sorted(
        _PROVIDER_CLASSES.keys()
    )
