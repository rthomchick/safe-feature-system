"""
Stub: Notion connector (not implemented).

This shows the pattern for adding a new connector.
To implement:
1. pip install notion-client
2. Create a Notion integration and get the token
3. Create a Notion database with matching properties
4. Implement each method using the Notion SDK

The pipeline code doesn't change — just swap PostgresConnector for NotionConnector.
"""

from typing import Optional

from connectors.base import ConnectorInterface, FeatureRequest


class NotionConnector(ConnectorInterface):
    """Future: Read/write feature requests from a Notion database."""

    def __init__(self, database_id: str, token: str):
        self.database_id = database_id
        self.token = token
        raise NotImplementedError(
            "NotionConnector is a stub. See connectors/example_notion.py for the pattern."
        )

    def list_pending(self) -> list[FeatureRequest]: ...
    def get_request(self, request_id: str) -> Optional[FeatureRequest]: ...
    def create_request(self, request: FeatureRequest) -> str: ...
    def update_status(self, request_id: str, status: str) -> None: ...
    def write_result(self, request_id: str, spec: str, score: int, cost: float, run_id: str) -> None: ...
    def list_completed(self, limit: int = 20) -> list[FeatureRequest]: ...
