import json


def analysis_json_schema() -> dict:
    """JSON schema matching the reference analysis output."""
    return {
        "type": "object",
        "properties": {
            "industry": {"type": "string"},
            "company": {"type": "string"},
            "symbol": {"type": "string"},
            "reason": {"type": "string"},
            "scores": {
                "type": "object",
                "properties": {
                    "impact_size": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "time_proximity": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "clarity": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "volatility_sensitivity": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "duration": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "polarity_strength": {"type": "number", "minimum": -1.0, "maximum": 1.0},
                },
                "required": [
                    "impact_size",
                    "time_proximity",
                    "clarity",
                    "volatility_sensitivity",
                    "duration",
                    "polarity_strength",
                ],
                "additionalProperties": False,
            },
        },
        "required": [
            "industry",
            "company",
            "symbol",
            "reason",
            "scores",
        ],
        "additionalProperties": False,
    }


__all__ = [
    "analysis_json_schema",
]


