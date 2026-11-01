"""Label the minimal framework's JSON actions and JSON execution results."""
from __future__ import annotations

import json

from toolpulse.core.protocols import TrajectoryState
from toolpulse.core.types import Action, ActionError, LabelInfo, LabelKind, StepObservation


KIND_OF_LABEL: dict[str, LabelKind] = {
    "read": LabelKind.RETRIEVE,
    "write": LabelKind.OPERATE,
    "check_ok": LabelKind.COMPUTE,
    "check_failed": LabelKind.COMPUTE,
    "empty": LabelKind.OTHER,
}


class MinimalReactLabeler:
    """Pre is read-only; post uses explicit results rather than guessing errors.

    Result protocol: {"ok": true, ...} or {"ok": false, "error": "..."}.
    The error message itself is the stable fingerprint in this toy framework.
    """

    def label(self, action: Action, step: StepObservation, state: TrajectoryState,
              *, record: bool) -> LabelInfo:
        if not action.raw_action.strip():
            return LabelInfo("empty", LabelKind.OTHER)

        error = ActionError("none", None)
        success = False
        if record:
            result = json.loads(step.observation)
            if not isinstance(result, dict) or type(result.get("ok")) is not bool:
                raise ValueError("Tool result must be an object with boolean ok")
            success = result["ok"]
            if not success:
                message = result.get("error")
                if not isinstance(message, str) or not message.strip():
                    raise ValueError("Failed tool result requires a nonempty error string")
                kind = "test_failure" if action.tool == "check" else "runtime"
                error = ActionError(kind, message)

        path = action.args["path"]
        if action.tool == "file":
            label = action.args["mode"]
        else:
            label = "check_failed" if error.kind != "none" else "check_ok"
        if record and success and label == "write":
            state.files.record_edit(path)
        return LabelInfo(
            label=label, kind=KIND_OF_LABEL[label], target_file=path,
            is_patch=label == "write", is_create=False,
            is_read=label == "read" and (not record or success), error=error,
        )
