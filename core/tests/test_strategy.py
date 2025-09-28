import unittest

from core.utils.strategy import compute_direction_and_confidence


class StrategyComputationTests(unittest.TestCase):
    def test_direction_from_polarity(self):
        scores = {
            "impact_size": 0.5,
            "time_proximity": 0.5,
            "clarity": 0.5,
            "volatility_sensitivity": 0.5,
            "duration": 0.5,
            "polarity_strength": 0.0,
        }
        direction, conf = compute_direction_and_confidence(scores)
        self.assertEqual(direction, "hold")
        self.assertEqual(conf, 0.0)

        scores["polarity_strength"] = 0.7
        direction, _ = compute_direction_and_confidence(scores)
        self.assertEqual(direction, "buy")

        scores["polarity_strength"] = -0.2
        direction, _ = compute_direction_and_confidence(scores)
        self.assertEqual(direction, "sell")

    def test_confidence_formula_and_clamp(self):
        scores = {
            "impact_size": 1.0,
            "time_proximity": 1.0,
            "clarity": 1.0,
            "volatility_sensitivity": 1.0,
            "duration": 1.0,
            "polarity_strength": 0.5,
        }
        direction, conf = compute_direction_and_confidence(scores)
        self.assertEqual(direction, "buy")
        # base = 0.35+0.25+0.15+0.15+0.10 = 1.0, confidence = 0.5 * 1.0 = 0.5
        self.assertAlmostEqual(conf, 0.5, places=6)

        # Strong polarity can push confidence but clamp at 1.0
        scores["polarity_strength"] = 2.0
        _, conf2 = compute_direction_and_confidence(scores)
        self.assertLessEqual(conf2, 1.0)


