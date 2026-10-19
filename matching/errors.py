"""Machine-readable errors shared by desktop and CLI."""


class InputError(ValueError):
    def __init__(self, code, message, invalid=()):
        super().__init__(message)
        self.code = code
        self.invalid = tuple(invalid)
