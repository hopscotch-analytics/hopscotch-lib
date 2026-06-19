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


class PreprocessingConfigError(HopscotchError):
    def __init__(self, processor: str, message: str):
        super().__init__(f"[{processor}] {message}", "PREPROCESSING_CONFIG_ERROR")


class PreprocessingColumnNotFoundError(HopscotchError):
    def __init__(self, processor: str, column: str, available: list):
        super().__init__(
            f"[{processor}] Column '{column}' not found. Available: {available}",
            "PREPROCESSING_COLUMN_NOT_FOUND"
        )


class PatternNoMatchError(HopscotchError):
    def __init__(self, pattern: str, group: str | None = None):
        msg = f"Pattern '{pattern}' doesn't match any paths"
        if group:
            msg += f" in {group}"
        super().__init__(msg, "PATTERN_NO_MATCH")


class InvalidMetricConfigError(HopscotchError):
    def __init__(self, message: str):
        super().__init__(message, "INVALID_METRIC_CONFIG")
