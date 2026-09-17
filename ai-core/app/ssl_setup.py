"""Windows TLS 인증서 문제를 줄인다.

Python은 Windows 인증서 저장소를 기본으로 안 쓴다. 백신·회사 프록시가 HTTPS를
가로채면 `CERTIFICATE_VERIFY_FAILED`가 난다. 키 문제가 아니다.
"""

from __future__ import annotations

import os


def configure_ssl() -> None:
    try:
        import pip_system_certs.cacert  # noqa: F401
    except ImportError:
        pass

    import certifi

    ca = certifi.where()
    os.environ.setdefault("SSL_CERT_FILE", ca)
    os.environ.setdefault("CURL_CA_BUNDLE", ca)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", ca)
