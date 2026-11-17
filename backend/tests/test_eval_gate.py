"""The regression gate must pass on the recorded run and must catch a worse one or an unmeasured metric."""

import copy
import json

from evals import gate


def load():
    return json.loads(gate.latest().read_text(encoding="utf-8"))["results"], json.loads((gate.HERE / "baseline.json").read_text(encoding="utf-8"))








