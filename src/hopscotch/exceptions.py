class HopscotchError(Exception):
    def __init__(self, message: str, error_code: str):
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)


class EmptyEventstreamError(HopscotchError):
    def __init__(self, context: str | None = None):
        message = "Eventstream is empty"
        if context:
            message += f": {context}"
        super().__init__(message, "EMPTY_EVENTSTREAM")


class DiffConfigError(HopscotchError):
    def __init__(self, message: str):
        super().__init__(message, "DIFF_CONFIG_ERROR")


class InvalidParameterError(HopscotchError):
    def __init__(self, param_name: str, value: str, allowed_values: list | None = None):
        message = f"Invalid value '{value}' for parameter '{param_name}'"
        if allowed_values:
            message += f". Allowed values: {allowed_values}"
        super().__init__(message, "INVALID_PARAMETER")
