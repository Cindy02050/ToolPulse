"""ToolPulse: host-agnostic trajectory-aware middleware.

Public API surface (design §5.3). Deliberately NOT re-exported here:
``OpenAIChatClient`` — importing ``toolpulse`` must not require ``openai``
installed; the import lives only in ``toolpulse.llm.openai_client`` (D17).
"""
from toolpulse.core.types import (
    Action,
    ActionInspection,
    ActionError,
    ActionRecord,
    BlindActionEvent,
    DuplicateActionEvent,
    FailedActionEvent,
    FailureCluster,
    FailureSignature,
    Hint,
    HintContext,
    LabelInfo,
    LabelKind,
    LoopActionEvent,
    PulseEvent,
    StalledActionEvent,
    StepObservation,
)
from toolpulse.detectors.multi_granularity import MultiGranularityDetector
from toolpulse.hints.assembly import assemble_observation
from toolpulse.hints.llm import LLMHintRenderer
from toolpulse.hints.sinks import CallbackSink, ListSink, LoggingSink
from toolpulse.hints.template import TemplateHintRenderer
from toolpulse.llm.stub import StubChatClient
from toolpulse.middleware import ToolPulse
from toolpulse.parsing.sweagent import SweAgentParser
from toolpulse.parsing.minimal_react import MinimalReactParser
from toolpulse.semantics.generic.labeler import GenericLabeler
from toolpulse.semantics.repo.labeler import RepoLabeler
from toolpulse.semantics.minimal_react import MinimalReactLabeler

__version__ = "0.1.0"

__all__ = [
    "Action",
    "ActionInspection",
    "ActionError",
    "ActionRecord",
    "BlindActionEvent",
    "CallbackSink",
    "DuplicateActionEvent",
    "FailedActionEvent",
    "FailureCluster",
    "FailureSignature",
    "GenericLabeler",
    "Hint",
    "HintContext",
    "LabelInfo",
    "LabelKind",
    "ListSink",
    "LLMHintRenderer",
    "LoggingSink",
    "LoopActionEvent",
    "MultiGranularityDetector",
    "MinimalReactParser",
    "MinimalReactLabeler",
    "PulseEvent",
    "RepoLabeler",
    "StalledActionEvent",
    "StepObservation",
    "StubChatClient",
    "SweAgentParser",
    "TemplateHintRenderer",
    "ToolPulse",
    "assemble_observation",
    "__version__",
]
