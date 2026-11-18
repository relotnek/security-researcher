"""Target-class taxonomy used to select a containment profile."""

from __future__ import annotations

from enum import StrEnum


class TargetType(StrEnum):
    """Concrete kind of thing being researched."""

    SOURCE_CODE = "source_code"
    BINARY = "binary"
    WEB_APP = "web_app"
    MOBILE_APP = "mobile_app"
    FIRMWARE = "firmware"
    DEVICE = "device"
    NETWORK = "network"


class TargetClass(StrEnum):
    """The two containment-relevant classes of target."""

    CODE = "code"  # code / software
    DEVICE = "device"  # device / firmware / network


class ContainmentProfile(StrEnum):
    DOCKER_SANDBOX = "docker_sandbox"
    ISOLATED_SEGMENT = "isolated_segment"


_CLASS_BY_TYPE: dict[TargetType, TargetClass] = {
    TargetType.SOURCE_CODE: TargetClass.CODE,
    TargetType.BINARY: TargetClass.CODE,
    TargetType.WEB_APP: TargetClass.CODE,
    TargetType.MOBILE_APP: TargetClass.CODE,
    TargetType.FIRMWARE: TargetClass.DEVICE,
    TargetType.DEVICE: TargetClass.DEVICE,
    TargetType.NETWORK: TargetClass.DEVICE,
}

_PROFILE_BY_CLASS: dict[TargetClass, ContainmentProfile] = {
    TargetClass.CODE: ContainmentProfile.DOCKER_SANDBOX,
    TargetClass.DEVICE: ContainmentProfile.ISOLATED_SEGMENT,
}


def classify(target_type: TargetType | str) -> TargetClass:
    """Map a target type to its class. Unknown types raise ValueError:
    a target that cannot be classified must not be given a containment
    profile by guesswork."""
    return _CLASS_BY_TYPE[TargetType(target_type)]


def profile_for(target_type: TargetType | str) -> ContainmentProfile:
    return _PROFILE_BY_CLASS[classify(target_type)]
