"""Workflows package - Temporal Workflows for spec-12."""

from .requirement_workflow import RequirementWorkflow
from .fast_channel_workflow import FastChannelWorkflow
from .dag_dispatcher import dispatch_parallel

__all__ = ["RequirementWorkflow", "FastChannelWorkflow", "dispatch_parallel"]
