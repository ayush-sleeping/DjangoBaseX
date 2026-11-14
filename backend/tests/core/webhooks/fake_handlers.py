"""An inbound handler the tests register. A real function: the registry stores a dotted path."""

CALLS: list[int] = []


def handle(event_id: int) -> None:
    CALLS.append(event_id)


def explode(event_id: int) -> None:
    CALLS.append(event_id)
    raise RuntimeError("handler failed")
