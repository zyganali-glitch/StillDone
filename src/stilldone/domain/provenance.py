"""Domain contracts for evidence provenance and live/recorded/fixture separation.

Defines the exact six-value EvidenceProvenance vocabulary frozen by AGENTS.md,
and immutable EvidenceOrigin / EvidenceProvenanceContract with strict
recorded-live lineage validation.
Does NOT store provider payloads, compute verification/readiness, or create evidence IDs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class EvidenceProvenance(StrEnum):
    """Canonical evidence provenance vocabulary frozen for StillDone.

    Answers WHERE and HOW evidence originated, not whether a predicate passed.
    Exactly 6 canonical values.
    """

    FIXTURE = "FIXTURE"
    LOCAL_EXECUTION = "LOCAL_EXECUTION"
    LIVE_AWS = "LIVE_AWS"
    LIVE_GOOGLE = "LIVE_GOOGLE"
    LIVE_EXTERNAL = "LIVE_EXTERNAL"
    RECORDED_LIVE = "RECORDED_LIVE"

    @property
    def is_fixture(self) -> bool:
        """Return True if synthetic/fixture provenance."""
        return self == EvidenceProvenance.FIXTURE

    @property
    def is_local_execution(self) -> bool:
        """Return True if real local execution, but not external-live."""
        return self == EvidenceProvenance.LOCAL_EXECUTION

    @property
    def is_external_live(self) -> bool:
        """Return True if external live service provenance."""
        return self in {
            EvidenceProvenance.LIVE_AWS,
            EvidenceProvenance.LIVE_GOOGLE,
            EvidenceProvenance.LIVE_EXTERNAL,
        }

    @property
    def is_current_live_provenance(self) -> bool:
        """Return True if fresh current live external call.

        RECORDED_LIVE and LOCAL_EXECUTION are strictly False.
        """
        return self.is_external_live

    @property
    def is_recorded_live(self) -> bool:
        """Return True if historical capture of a previously live observation."""
        return self == EvidenceProvenance.RECORDED_LIVE


VALID_RECORDED_LIVE_ORIGINS: frozenset[EvidenceProvenance] = frozenset(
    {
        EvidenceProvenance.LIVE_AWS,
        EvidenceProvenance.LIVE_GOOGLE,
        EvidenceProvenance.LIVE_EXTERNAL,
    }
)


@dataclass(frozen=True)
class EvidenceOrigin:
    """Immutable evidence provenance contract.

    Binds canonical provenance, UTC observation timestamp, and for RECORDED_LIVE,
    the verified original live family source.
    Does NOT store provider payloads, hash content, or assign verification/result states.
    """

    provenance: EvidenceProvenance
    observed_at: datetime
    recorded_live_origin: EvidenceProvenance | None = None

    def __post_init__(self) -> None:
        if isinstance(self.provenance, str) and not isinstance(self.provenance, EvidenceProvenance):
            try:
                p = EvidenceProvenance(self.provenance)
                object.__setattr__(self, "provenance", p)
            except ValueError as exc:
                raise ValueError(f"Unsupported evidence provenance: {self.provenance!r}") from exc
        elif not isinstance(self.provenance, EvidenceProvenance):
            raise TypeError(
                "provenance must be an EvidenceProvenance instance, "
                f"got {type(self.provenance).__name__}"
            )

        if not isinstance(self.observed_at, datetime):
            raise TypeError(
                f"observed_at must be a datetime instance, got {type(self.observed_at).__name__}"
            )
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware (UTC required)")
        if self.observed_at.tzinfo != UTC:
            object.__setattr__(self, "observed_at", self.observed_at.astimezone(UTC))

        if self.provenance == EvidenceProvenance.RECORDED_LIVE:
            if self.recorded_live_origin is None:
                raise ValueError("RECORDED_LIVE provenance requires recorded_live_origin")

            orig = self.recorded_live_origin
            if isinstance(orig, str) and not isinstance(orig, EvidenceProvenance):
                try:
                    orig = EvidenceProvenance(orig)
                    object.__setattr__(self, "recorded_live_origin", orig)
                except ValueError as exc:
                    raise ValueError(
                        f"Unsupported recorded_live_origin: {self.recorded_live_origin!r}"
                    ) from exc
            elif not isinstance(orig, EvidenceProvenance):
                raise TypeError(
                    "recorded_live_origin must be an EvidenceProvenance instance, "
                    f"got {type(orig).__name__}"
                )

            if orig not in VALID_RECORDED_LIVE_ORIGINS:
                raise ValueError(
                    f"RECORDED_LIVE origin must be drawn only from LIVE_AWS, LIVE_GOOGLE, "
                    f"or LIVE_EXTERNAL; got {orig.value}"
                )
        else:
            if self.recorded_live_origin is not None:
                raise ValueError(
                    f"Non-RECORDED_LIVE provenance ({self.provenance.value}) must not carry "
                    f"recorded_live_origin metadata"
                )

    @property
    def is_fixture(self) -> bool:
        return self.provenance.is_fixture

    @property
    def is_local_execution(self) -> bool:
        return self.provenance.is_local_execution

    @property
    def is_external_live(self) -> bool:
        return self.provenance.is_external_live

    @property
    def is_current_live_provenance(self) -> bool:
        return self.provenance.is_current_live_provenance

    @property
    def is_recorded_live(self) -> bool:
        return self.provenance.is_recorded_live

    @classmethod
    def fixture(cls, observed_at: datetime | None = None) -> EvidenceOrigin:
        """Construct synthetic/fixture provenance."""
        now = observed_at if observed_at is not None else datetime.now(UTC)
        return cls(provenance=EvidenceProvenance.FIXTURE, observed_at=now)

    @classmethod
    def local_execution(cls, observed_at: datetime | None = None) -> EvidenceOrigin:
        """Construct real local execution provenance."""
        now = observed_at if observed_at is not None else datetime.now(UTC)
        return cls(provenance=EvidenceProvenance.LOCAL_EXECUTION, observed_at=now)

    @classmethod
    def live_aws(cls, observed_at: datetime | None = None) -> EvidenceOrigin:
        """Construct fresh external AWS provenance."""
        now = observed_at if observed_at is not None else datetime.now(UTC)
        return cls(provenance=EvidenceProvenance.LIVE_AWS, observed_at=now)

    @classmethod
    def live_google(cls, observed_at: datetime | None = None) -> EvidenceOrigin:
        """Construct fresh external Google provenance."""
        now = observed_at if observed_at is not None else datetime.now(UTC)
        return cls(provenance=EvidenceProvenance.LIVE_GOOGLE, observed_at=now)

    @classmethod
    def live_external(cls, observed_at: datetime | None = None) -> EvidenceOrigin:
        """Construct fresh external non-AWS/non-Google provenance."""
        now = observed_at if observed_at is not None else datetime.now(UTC)
        return cls(provenance=EvidenceProvenance.LIVE_EXTERNAL, observed_at=now)

    @classmethod
    def recorded_live(
        cls,
        *,
        original_provenance: EvidenceProvenance | str,
        observed_at: datetime | None = None,
    ) -> EvidenceOrigin:
        """Construct historical recorded-live provenance with verified live family source."""
        now = observed_at if observed_at is not None else datetime.now(UTC)
        orig = (
            original_provenance
            if isinstance(original_provenance, EvidenceProvenance)
            else EvidenceProvenance(original_provenance)
        )
        return cls(
            provenance=EvidenceProvenance.RECORDED_LIVE,
            observed_at=now,
            recorded_live_origin=orig,
        )

    @classmethod
    def create(
        cls,
        *,
        provenance: EvidenceProvenance | str,
        observed_at: datetime | None = None,
        recorded_live_origin: EvidenceProvenance | str | None = None,
    ) -> EvidenceOrigin:
        """Helper to construct an immutable EvidenceOrigin."""
        now = observed_at if observed_at is not None else datetime.now(UTC)
        try:
            p = (
                provenance
                if isinstance(provenance, EvidenceProvenance)
                else EvidenceProvenance(provenance)
            )
        except ValueError as exc:
            raise ValueError(f"Unsupported evidence provenance: {provenance!r}") from exc

        orig: EvidenceProvenance | None = None
        if recorded_live_origin is not None:
            try:
                orig = (
                    recorded_live_origin
                    if isinstance(recorded_live_origin, EvidenceProvenance)
                    else EvidenceProvenance(recorded_live_origin)
                )
            except ValueError as exc:
                raise ValueError(
                    f"Unsupported recorded_live_origin: {recorded_live_origin!r}"
                ) from exc

        return cls(
            provenance=p,
            observed_at=now,
            recorded_live_origin=orig,
        )


# Canonical alias
EvidenceProvenanceContract = EvidenceOrigin
