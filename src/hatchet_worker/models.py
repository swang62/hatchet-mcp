"""Pydantic input models for Hatchet workflows."""

from pydantic import BaseModel

from src.shared.enums import ResumeAction, ToolName


class K8sDevOpsInput(BaseModel):
    task: str = "diagnose and fix cluster issues"
    source: str = ""


class K8sToolInput(BaseModel):
    tool: ToolName
    params: dict = {}


class K8sResumeInput(BaseModel):
    action: ResumeAction = ResumeAction.APPROVE
    thread_id: str = ""
    command_override: str = ""
