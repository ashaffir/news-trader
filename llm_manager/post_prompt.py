import json


def analysis_json_schema() -> dict:
    """JSON schema matching the reference analysis output."""
    return {
        "type": "object",
        "properties": {
            "industry": {"type": "string"},
            "company": {"type": "string"},
            "symbol": {"type": "string"},
            "direction": {"type": "string", "enum": ["buy", "sell", "hold"]},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "reason": {"type": "string"},
            "scores": {
                "type": "object",
                "properties": {
                    "impact_size": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "time_proximity": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "clarity": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "volatility_sensitivity": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "duration": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "required": [
                    "impact_size",
                    "time_proximity",
                    "clarity",
                    "volatility_sensitivity",
                    "duration",
                ],
                "additionalProperties": False,
            },
        },
        "required": [
            "industry",
            "company",
            "symbol",
            "direction",
            "confidence",
            "reason",
            "scores",
        ],
        "additionalProperties": False,
    }


__all__ = [
    "analysis_json_schema",
]


