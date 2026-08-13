from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from intent_contracts.enums import SCHEMA_VERSION, Action


class ActionCommand(BaseModel):
    """Only the safety gateway may create this object."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    command_id: str
    decision_id: str
    action: Action | str
    target_object_id: str | None = None
    issued_at_ns: int = Field(ge=0)
    expires_at_ns: int = Field(ge=0)
    safety_policy_version: str
    idempotency_key: str

    def model_post_init(self, __context: object) -> None:
        major = self.schema_version.split(".", 1)[0]
        if major != SCHEMA_VERSION.split(".", 1)[0]:
            raise ValueError(f"unsupported schema major version: {self.schema_version}")
