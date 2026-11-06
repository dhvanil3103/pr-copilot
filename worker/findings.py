from pydantic import BaseModel, Field

from shared.db import Severity


class Finding(BaseModel):
    file_path: str = Field(description="Path of the changed file, exactly as listed")
    line: int = Field(description="Line number in the new version of the file")
    severity: Severity
    category: str = Field(description="Short label, e.g. bug, security, readability, test")
    message: str = Field(description="What is wrong or what should be tested, and why")
    suggestion: str = Field(default="", description="Concrete fix or test outline")


class AgentOutput(BaseModel):
    """Structured output both agents must return."""

    summary: str = Field(description="Two or three sentence overview of the change")
    findings: list[Finding]
