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
from stilldone.verifier.freshness import (
    DEFAULT_CURRENT_FRESHNESS_WINDOW_SECONDS,
    FreshnessError,
    FreshnessResult,
    FreshnessStatus,
    FutureDatedObservationError,
    NaiveDatetimeError,
    evaluate_freshness,
    evaluate_observation_freshness,
)
from stilldone.verifier.predicates import (
    PredicateEvaluationResult,
    PredicateTruth,
    evaluate_predicate,
    evaluate_predicates,
)
from stilldone.verifier.readiness import (
    MissionReadinessDetermination,
    PlannerReadinessAuthorityError,
    ReadinessContractTypeError,
    ReadinessContractValueError,
    ReadinessError,
    assert_not_planner_or_execution_payload,
    compute_mission_readiness,
)

__all__ = [
    "CalendarVerificationPort",
    "DEFAULT_CURRENT_FRESHNESS_WINDOW_SECONDS",
    "ExecutionPayloadSubstitutionError",
    "FreshnessError",
    "FreshnessResult",
    "FreshnessStatus",
    "FutureDatedObservationError",
    "MalformedObservationError",
    "MissingVerifierRouteError",
    "MissionReadinessDetermination",
    "NaiveDatetimeError",
    "PlannerReadinessAuthorityError",
    "PredicateEvaluationResult",
    "PredicateTruth",
    "ReadAdapterPort",
    "ReadinessContractTypeError",
    "ReadinessContractValueError",
    "ReadinessError",
    "TasksVerificationPort",
    "UnsupportedVerificationTargetError",
    "VerificationObservation",
    "VerificationRequest",
    "VerifierDispatcher",
    "VerifierError",
    "VerifierReadError",
    "VerifierTargetMismatchError",
    "WeatherVerificationPort",
    "assert_not_planner_or_execution_payload",
    "compute_mission_readiness",
    "create_verifier_dispatcher",
    "evaluate_freshness",
    "evaluate_observation_freshness",
    "evaluate_predicate",
    "evaluate_predicates",
]
