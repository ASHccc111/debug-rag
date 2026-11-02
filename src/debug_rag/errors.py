"""Public errors contain maintained messages, never raw SDK or provider response text."""


class RagError(Exception):
    def __init__(self, code: str, message: str, status: int = 503):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)

    def public(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}
