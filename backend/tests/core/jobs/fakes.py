"""Job callables the tests register. Real functions, so dbx.jobs.E004 can resolve them."""

CALLS: list[dict] = []


def count_three(ctx) -> int:
    CALLS.append({"run_id": ctx.run_id, "params": dict(ctx.params), "trigger": ctx.trigger})
    return 3


def returns_text(ctx):
    return "done"


def takes_nothing():
    return 0


def takes_two(ctx, extra):
    return 0


def fails_with_a_secret(ctx):
    raise ConnectionError("connect failed: password=hunter2 for postgres://app:s3cretpw@db/app")


def writes_then_fails(ctx):
    from users.models import LoginAttempt

    LoginAttempt.objects.create(identifier="rolled-back@example.com", succeeded=False)
    raise RuntimeError("after the write")
