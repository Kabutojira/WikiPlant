class WikiPlantError(Exception):
    """Base error for deterministic WikiPlant helpers."""


class ValidationError(WikiPlantError):
    """Input violates a versioned WikiPlant contract."""


class ConflictError(WikiPlantError):
    """A safe write cannot prove that its input is still current."""


class CapabilityError(WikiPlantError):
    """The active host/connector lacks an observed required capability."""


class SimulatedLostResponse(WikiPlantError):
    """A fake adapter applied a mutation but hid its response."""
