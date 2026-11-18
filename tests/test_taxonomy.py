import unittest

from autoresearch.taxonomy import (
    ContainmentProfile,
    TargetClass,
    TargetType,
    classify,
    profile_for,
)


class TaxonomyTest(unittest.TestCase):
    def test_code_and_software_targets(self):
        for t in (TargetType.SOURCE_CODE, TargetType.BINARY, TargetType.WEB_APP, TargetType.MOBILE_APP):
            with self.subTest(t=t):
                self.assertIs(classify(t), TargetClass.CODE)
                self.assertIs(profile_for(t), ContainmentProfile.DOCKER_SANDBOX)

    def test_device_firmware_network_targets(self):
        for t in (TargetType.DEVICE, TargetType.FIRMWARE, TargetType.NETWORK):
            with self.subTest(t=t):
                self.assertIs(classify(t), TargetClass.DEVICE)
                self.assertIs(profile_for(t), ContainmentProfile.ISOLATED_SEGMENT)

    def test_every_type_is_classified(self):
        for t in TargetType:
            self.assertIn(classify(t), TargetClass)

    def test_string_values_accepted_and_unknown_rejected(self):
        self.assertIs(classify("firmware"), TargetClass.DEVICE)
        with self.assertRaises(ValueError):
            classify("toaster")
