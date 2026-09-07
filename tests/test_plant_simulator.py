import unittest

from simulator.plant_simulator import PlantState, classify, generate_readings


class PlantSimulatorTests(unittest.TestCase):
    def test_comfortable_plant(self):
        self.assertEqual(classify(PlantState()), ["comfortable"])

    def test_conditions_are_deterministic(self):
        state = PlantState(
            soil_moisture=10,
            temperature_f=90,
            humidity=20,
            battery_percent=14,
        )
        self.assertEqual(
            classify(state),
            ["needs_water", "too_hot", "air_too_dry", "battery_critical"],
        )

    def test_dry_out_scenario_lowers_soil_moisture(self):
        readings = generate_readings("plant-test", "dry-out", seed=42)
        first = next(readings)
        last = first
        for _ in range(10):
            last = next(readings)
        self.assertLess(
            last["readings"]["soil_moisture"],
            first["readings"]["soil_moisture"],
        )

    def test_payload_matches_contract_shape(self):
        payload = next(generate_readings("plant-test", "normal", seed=42))
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["device_id"], "plant-test")
        self.assertEqual(payload["source"], "simulator")
        self.assertIn("battery_percent", payload["readings"])


if __name__ == "__main__":
    unittest.main()
