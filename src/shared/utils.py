"""General shared utilities."""

import os

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from src.shared.constants import (
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    LLM_TEMPERATURE,
)

MAX_LENGTH_OUTPUT = 500

MUTATING_VERBS = {
    "apply",
    "attach",
    "create",
    "delete",
    "drain",
    "edit",
    "exec",
    "expose",
    "patch",
    "port-forward",
    "replace",
    "rollout",
    "run",
    "scale",
    "set",
    "taint",
}


def trunc(text: str) -> str:
    return text if len(text) <= MAX_LENGTH_OUTPUT else text[:MAX_LENGTH_OUTPUT] + "..."


def is_fix_command(command: str) -> bool:
    return any(verb in command for verb in MUTATING_VERBS)


def call_llm(messages: list[tuple[str, str]]) -> BaseMessage:
    llm = ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", DEFAULT_LLM_MODEL),
        api_key=SecretStr(os.environ["OPENAI_API_KEY"]) if "OPENAI_API_KEY" in os.environ else None,
        base_url=os.getenv("OPENAI_BASE_URL", DEFAULT_LLM_BASE_URL),
        temperature=LLM_TEMPERATURE,
        timeout=5,
        max_retries=3,
    )
    return llm.invoke(messages)
