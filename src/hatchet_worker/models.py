"""Pydantic input models for Hatchet workflows."""

from pydantic import BaseModel


class KnowledgeIngestionInput(BaseModel):
    file_path: str
    document_id: str = ""
    source: str = "unknown"


class K8sDevOpsInput(BaseModel):
    task: str = "diagnose and fix cluster issues"


class K8sToolInput(BaseModel):
    tool: str
    params: dict = {}


class K8sDevOpsResumeInput(BaseModel):
    thread_id: str
    approved: bool = False
    command_override: str = ""
