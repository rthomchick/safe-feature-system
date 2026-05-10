"""
connectors/base.py

Abstract interface for feature request connectors.

Each connector translates between an external system (PostgreSQL, Notion,
Jira, Asana, etc.) and the standardized FeatureRequest format.
The pipeline doesn't know or care where requests come from.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class FeatureRequest:
    """Standardized feature request — the common format all connectors produce."""
    id: str
    title: str
    description: str
    notes: str
    feature_type: Optional[str] = None   # CAPABILITY, EXPERIENCE, WEBPAGE, or None (auto-detect)
    status: str = "draft"                # draft, ready, processing, complete, failed
    boost_inputs: dict = field(default_factory=dict)  # section_name → boost text

    # Output fields (written back after pipeline completes)
    generated_spec: Optional[str] = None
    score: Optional[int] = None
    run_cost: Optional[float] = None
    run_id: Optional[str] = None
    completed_at: Optional[datetime] = None


class ConnectorInterface(ABC):
    """Base interface for feature request connectors.

    Each connector translates between an external system (PostgreSQL, Notion,
    Jira, Asana, etc.) and the standardized FeatureRequest format.
    The pipeline doesn't know or care where requests come from.
    """

    @abstractmethod
    def list_pending(self) -> list[FeatureRequest]:
        """Return all requests with status 'ready' (ready for pipeline processing)."""
        ...

    @abstractmethod
    def get_request(self, request_id: str) -> Optional[FeatureRequest]:
        """Fetch a single request by ID."""
        ...

    @abstractmethod
    def create_request(self, request: FeatureRequest) -> str:
        """Create a new request. Returns the assigned ID."""
        ...

    @abstractmethod
    def update_status(self, request_id: str, status: str) -> None:
        """Update request status: draft → ready → processing → complete/failed."""
        ...

    @abstractmethod
    def write_result(
        self,
        request_id: str,
        spec: str,
        score: int,
        cost: float,
        run_id: str,
    ) -> None:
        """Write pipeline results back to the request."""
        ...

    @abstractmethod
    def list_completed(self, limit: int = 20) -> list[FeatureRequest]:
        """Return completed requests, newest first."""
        ...
