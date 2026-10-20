"""Host checks of the board-verification inputs/contracts; no hardware is accessed."""
from pathlib import Path
from types import SimpleNamespace
import unittest

from inference import IntegerModel
from verify_board import check_result, load_cases


HERE = Path(__file__).resolve().parent


class VerificationContracts(unittest.TestCase):
    def test_packaged_120_cases_match_integer_model(self):
        images, expected = load_cases(HERE / "fpga" / "rtl_reference_cases.npz", IntegerModel())
        self.assertEqual(images.shape, (120, 28, 28))
        self.assertEqual(expected.shape, (120,))

    def test_rejects_ten_samples_as_full_regression(self):
        with self.assertRaises(ValueError):
            load_cases(HERE / "test_images.npz", IntegerModel())

    def test_rejects_wrong_prediction_counter_or_clock(self):
        check_result(SimpleNamespace(digit=7, cycles=110208, clock_hz=100_000_000), 7)
        for result in (SimpleNamespace(digit=1, cycles=110208, clock_hz=100_000_000),
                       SimpleNamespace(digit=7, cycles=110207, clock_hz=100_000_000),
                       SimpleNamespace(digit=7, cycles=110208, clock_hz=50_000_000)):
            with self.assertRaises(RuntimeError):
                check_result(result, 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
