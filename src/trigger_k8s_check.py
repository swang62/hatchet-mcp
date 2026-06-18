"""Trigger a K8s cluster health check by pushing an event to Hatchet.

Usage:
    just k8s-check

This pushes a kb:k8s:monitor event to Hatchet, which triggers the
k8s_devops workflow.
"""

from hatchet_sdk import Hatchet

hatchet = Hatchet()

hatchet.event.push("kb:k8s:monitor", {})
print("Pushed kb:k8s:monitor event")
print("Check Hatchet dashboard for workflow run status.")
