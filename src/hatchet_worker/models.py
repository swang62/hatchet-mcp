"""Pydantic input models for Hatchet workflows."""

from pydantic import BaseModel


class K8sDevOpsInput(BaseModel):
    task: str = "diagnose and fix cluster issues"
    source: str = ""


class K8sToolInput(BaseModel):
    tool: str
    params: dict = {}


class K8sDevOpsResumeInput(BaseModel):
    thread_id: str
    approved: bool = False
    command_override: str = ""
