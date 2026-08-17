from __future__ import annotations


class KmoeError(Exception):
    code = "kmoe_error"


class AuthenticationExpired(KmoeError):
    code = "auth_expired"


class InvalidCredentials(KmoeError):
    code = "invalid_credentials"


class AccountDisabled(KmoeError):
    code = "account_disabled"


class AuthenticationChallenge(KmoeError):
    code = "auth_challenge"


class QuotaExhausted(KmoeError):
    code = "quota_exhausted"


class SiteChanged(KmoeError):
    code = "site_changed"


class NetworkError(KmoeError):
    code = "network_error"


class NotFound(KmoeError):
    code = "not_found"


class RateLimited(KmoeError):
    code = "rate_limited"


class DownloadUrlInvalid(KmoeError):
    code = "download_url_invalid"


class DownloadTransferError(KmoeError):
    retryable = False


class DownloadUrlExpired(DownloadTransferError):
    code = "download_url_expired"
    retryable = True


class DownloadForbidden(DownloadTransferError):
    code = "download_forbidden"


class DownloadConnectTimeout(DownloadTransferError):
    code = "connect_timeout"
    retryable = True


class DownloadServerError(DownloadTransferError):
    code = "download_server_error"
    retryable = True


class NonFileResponse(DownloadTransferError):
    code = "non_file_response"


class DownloadRangeInvalid(DownloadTransferError):
    code = "download_range_invalid"
    retryable = True


class MirrorExhausted(NetworkError):
    code = "mirror_unavailable"

    def __init__(self, mirrors: tuple[str, ...]) -> None:
        self.mirrors = mirrors
        super().__init__(f"All Kmoe mirrors failed: {', '.join(mirrors)}")
