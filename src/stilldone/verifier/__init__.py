"""Independent Verification & Reconciliation Engine for StillDone.

Phase P-09:
Makes external reality, not the executor or model prose, decide completion.

Submodules:
- contracts: VerificationRequest, VerificationObservation, and verifier exceptions.
- dispatch: VerifierDispatcher, read ports, and no-mutation factory.
"""

from __future__ import annotations

from stilldone.verifier.contracts import (
    ExecutionPayloadSubstitutionError,
    MalformedObservationError,
    MissingVerifierRouteError,
    UnsupportedVerificationTargetError,
    VerificationObservation,
    VerificationRequest,
    VerifierError,
    VerifierReadError,
    VerifierTargetMismatchError,
)
from stilldone.verifier.dispatch import (
    CalendarVerificationPort,
    ReadAdapterPort,
    TasksVerificationPort,
    VerifierDispatcher,
    WeatherVerificationPort,
    create_verifier_dispatcher,
)

__all__ = [
    "CalendarVerificationPort",
    "ExecutionPayloadSubstitutionError",
    "MalformedObservationError",
    "MissingVerifierRouteError",
    "ReadAdapterPort",
    "TasksVerificationPort",
    "UnsupportedVerificationTargetError",
    "VerificationObservation",
    "VerificationRequest",
    "VerifierDispatcher",
    "VerifierError",
    "VerifierReadError",
    "VerifierTargetMismatchError",
    "WeatherVerificationPort",
    "create_verifier_dispatcher",
]
