import unittest
from unittest import mock

from backend.registration import engine
from backend.registration import signup_flow


class SignupFlowTests(unittest.TestCase):
    class NativeInput:
        def __init__(self, current_value=""):
            self.current_value = current_value
            self.states = mock.Mock(is_alive=True, is_displayed=True, is_enabled=True)

        def click(self, **kwargs):
            return None

        def input(self, value, **kwargs):
            return None

        def property(self, name):
            return self.current_value

    def test_native_input_does_not_treat_empty_value_as_success(self):
        element = self.NativeInput(current_value="")
        self.assertFalse(signup_flow._native_type_element(element, "Neo"))

    def test_native_input_accepts_confirmed_value(self):
        element = self.NativeInput(current_value="Neo")
        self.assertTrue(signup_flow._native_type_element(element, "Neo"))

    def test_duplicate_account_has_own_failure_type(self):
        exc = signup_flow.AccountAlreadyRegistered("fixture")
        self.assertEqual(engine.classify_failure(exc), engine.FAIL_ALREADY_REGISTERED)


if __name__ == "__main__":
    unittest.main()
