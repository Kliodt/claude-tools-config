class AppError(Exception):
    status = 500
    code = "internal"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class BadRequestError(AppError):
    status = 400
    code = "bad_request"


class NotFoundError(AppError):
    status = 404
    code = "not_found"


class InvalidJsonError(AppError):
    status = 422
    code = "invalid_json"
