class AppError(Exception):
    """An expected error that is shown to the admin as a plain message."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message
