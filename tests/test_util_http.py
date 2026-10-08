from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from version_info import util_http
from version_info.util_http import get_text


def test_github_token_not_set_by_default() -> None:
    """Test that requests work without GITHUB_TOKEN."""
    # Ensure GITHUB_TOKEN is not set
    token = os.environ.pop("GITHUB_TOKEN", None)
    try:
        # This will fail with a connection error, but we can verify the token header is not added
        # by mocking the request
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.read.return_value = b"{}"
            mock_response.__enter__ = lambda self: self
            mock_response.__exit__ = lambda self, *args: None
            mock_urlopen.return_value = mock_response

            get_text("https://api.github.com/repos/test/repo")

            # Verify the request was made
            mock_urlopen.assert_called_once()
            call_args = mock_urlopen.call_args
            request = call_args[0][0]

            # Verify Authorization header is NOT present
            assert request.get_header("Authorization") is None
    finally:
        # Restore GITHUB_TOKEN if it was set
        if token:
            os.environ["GITHUB_TOKEN"] = token


def test_github_token_added_when_set() -> None:
    """Test that GITHUB_TOKEN is added to requests when set."""
    with (
        patch.dict(os.environ, {"GITHUB_TOKEN": "test-token-12345"}),
        patch("urllib.request.urlopen") as mock_urlopen,
    ):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b"{}"
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None
        mock_urlopen.return_value = mock_response

        get_text("https://api.github.com/repos/test/repo", cache=False)

        mock_urlopen.assert_called_once()
        request = mock_urlopen.call_args[0][0]
        assert request.get_header("Authorization") == "Bearer test-token-12345"


def test_github_token_with_custom_headers() -> None:
    """Test that GITHUB_TOKEN works with custom headers."""
    with (
        patch.dict(os.environ, {"GITHUB_TOKEN": "custom-token-67890"}),
        patch("urllib.request.urlopen") as mock_urlopen,
    ):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b"{}"
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None
        mock_urlopen.return_value = mock_response

        get_text(
            "https://api.github.com/repos/test/repo",
            headers={"Accept": "application/vnd.github.v3+json"},
            cache=False,
        )

        mock_urlopen.assert_called_once()
        request = mock_urlopen.call_args[0][0]
        assert request.get_header("Authorization") == "Bearer custom-token-67890"
        assert request.get_header("Accept") == "application/vnd.github.v3+json"


def test_response_headers_preserve_duplicate_values() -> None:
    """Test that repeated response headers are preserved as lists."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b"{}"
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None
        mock_response.headers.items.return_value = [
            ("Set-Cookie", "a=1"),
            ("Set-Cookie", "b=2"),
            ("Link", '<https://example.com/page2>; rel="next"'),
        ]
        mock_urlopen.return_value = mock_response

        result = get_text("https://example.com", cache=False)

        assert result.headers is not None
        assert result.headers["set-cookie"] == ["a=1", "b=2"]
        assert result.headers["link"] == ['<https://example.com/page2>; rel="next"']


def test_github_token_not_sent_to_non_github_hosts() -> None:
    """Test that GITHUB_TOKEN is not sent to non-GitHub hosts."""
    with (
        patch.dict(os.environ, {"GITHUB_TOKEN": "test-token-12345"}),
        patch("urllib.request.urlopen") as mock_urlopen,
    ):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b"{}"
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None
        mock_urlopen.return_value = mock_response

        get_text("https://pypi.org/pypi/requests/json", cache=False)

        mock_urlopen.assert_called_once()
        request = mock_urlopen.call_args[0][0]
        assert request.get_header("Authorization") is None


def test_cache_key_varies_with_github_auth_state() -> None:
    """Test that cached responses do not leak across auth/no-auth request modes."""
    orig_cache = util_http._cache
    try:
        util_http._cache = util_http.SimpleTtlCache(ttl_s=300.0)

        with patch("urllib.request.urlopen") as mock_urlopen:
            first_response = MagicMock()
            first_response.status = 200
            first_response.read.return_value = b'{"mode":"anon"}'
            first_response.__enter__ = lambda self: self
            first_response.__exit__ = lambda self, *args: None

            second_response = MagicMock()
            second_response.status = 200
            second_response.read.return_value = b'{"mode":"auth"}'
            second_response.__enter__ = lambda self: self
            second_response.__exit__ = lambda self, *args: None

            mock_urlopen.side_effect = [first_response, second_response]

            with patch.dict(os.environ, {}, clear=True):
                anon = get_text("https://api.github.com/repos/test/repo", cache=True)

            with patch.dict(os.environ, {"GITHUB_TOKEN": "token-123"}, clear=False):
                auth = get_text("https://api.github.com/repos/test/repo", cache=True)

            assert anon.text == '{"mode":"anon"}'
            assert auth.text == '{"mode":"auth"}'
            assert mock_urlopen.call_count == 2
    finally:
        util_http._cache = orig_cache
