from typing import Any, Dict, Optional

from infergrade.request import request_from_dict
from infergrade.utils import dump_simple_yaml, stable_hash, utcnow_iso


def build_run_config_document(
    request_payload: Dict[str, Any],
    name: str,
    description: Optional[str] = None,
    created_by: Optional[str] = None,
    tags=None,
) -> Dict[str, Any]:
    return {
        "run_config_spec_version": "0.1-draft",
        "run_config_id": "rcfg_%s" % stable_hash(
            {"name": name, "description": description, "request": request_payload}
        ),
        "name": name,
        "description": description,
        "created_at": utcnow_iso(),
        "created_by": created_by,
        "tags": list(tags or []),
        "request": request_payload,
    }


def render_run_config_document(payload: Dict[str, Any], output_format: str = "json") -> str:
    if output_format == "yaml":
        return dump_simple_yaml(payload) + "\n"
    import json

    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def request_from_run_config_document(payload: Dict[str, Any], simulate: bool = True):
    return request_from_dict(payload, simulate=simulate, run_config_source=payload.get("run_config_id"))
