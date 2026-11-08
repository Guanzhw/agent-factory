"""Read-only presentation of execution versus durable resource finalization."""


def finalized_status(status, terminal):
    # Native stop is observable before the lifecycle owner commits its proof.
    # Do not advertise completion while follow-up admission/material reads still
    # correctly retain the original task's resources. Never turn this display
    # state into stop evidence or override UNKNOWN/protected failure.
    if not terminal:
        if status == "completed":
            return "finalizing"
        if status in {"canceled", "cancelled"}:
            return "canceling"
    return status


def native_status(queue_status, run_status):
    """A finished stream can contain RunError; an active queue retry still wins."""
    queued = str(queue_status or '').lower().removeprefix('runstatus.')
    persisted = str(run_status or '').lower().removeprefix('runstatus.')
    if queued == 'completed' and persisted in {'error', 'cancelled', 'canceled'}:
        return persisted
    return queued or persisted or 'queued'
