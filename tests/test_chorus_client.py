"""Chorus Encore API client -- search_by_artist_title().

Built against the REAL request/response schema, sourced by reading Bridge's
(github.com/Geomitron/Bridge) actual TypeScript source directly (Task 0),
not guessed. Real endpoint: POST https://api.enchor.us/search/advanced with
a structured body -- NOT a GET .../search?query= as the dead
chorus.fightthe.pw README implied. Must never raise: network/lookup
failures degrade to None so a single song's lookup failure can never abort
a library-wide run (shared contract with both SPEC-chorus-metadata.md and
SPEC-duplicate-detection.md).
"""

from unittest.mock import MagicMock, patch

import chorus_client as module


def _fake_response(status_code=200, json_data=None, raise_for_status_error=None):
	response = MagicMock()
	response.status_code = status_code
	response.json.return_value = json_data or {}
	if raise_for_status_error:
		response.raise_for_status.side_effect = raise_for_status_error
	else:
		response.raise_for_status.return_value = None
	return response


KRYPTONITE_RESULT = {
	"found": 1, "out_of": 1, "page": 1, "search_time_ms": 4,
	"data": [{
		"name": "Kryptonite", "artist": "3 Doors Down", "album": "The Better Life",
		"genre": "Post Grunge", "year": "2000", "charter": "Neversoft",
		"chartId": 12345, "songId": 6789, "md5": "abc123", "chartHash": "def456",
		"song_length": 240389,
	}],
}

EMPTY_RESULT = {"found": 0, "out_of": 0, "page": 1, "search_time_ms": 2, "data": []}


def test_returns_top_result_on_successful_match():
	with patch.object(module.requests, "post", return_value=_fake_response(json_data=KRYPTONITE_RESULT)):
		result = module.search_by_artist_title("3 Doors Down", "Kryptonite")

	assert result["name"] == "Kryptonite"
	assert result["artist"] == "3 Doors Down"
	assert result["year"] == "2000"


def test_sends_post_to_the_real_advanced_search_endpoint():
	with patch.object(module.requests, "post", return_value=_fake_response(json_data=KRYPTONITE_RESULT)) as mock_post:
		module.search_by_artist_title("3 Doors Down", "Kryptonite")

	args, kwargs = mock_post.call_args
	assert args[0] == "https://api.enchor.us/search/advanced"
	body = kwargs["json"]
	assert body["name"] == {"value": "Kryptonite", "exact": False, "exclude": False}
	assert body["artist"] == {"value": "3 Doors Down", "exact": False, "exclude": False}
	# every AdvancedSearchSchema field must be present (nullable, not optional)
	assert "instrument" in body and body["instrument"] is None
	assert "sort" in body and body["sort"] is None
	assert body["source"] == "bridge"


def test_returns_none_when_no_match_found():
	with patch.object(module.requests, "post", return_value=_fake_response(json_data=EMPTY_RESULT)):
		result = module.search_by_artist_title("Nobody", "Nothing")

	assert result is None


def test_returns_none_on_network_failure_never_raises():
	with patch.object(module.requests, "post", side_effect=module.requests.exceptions.ConnectionError("no network")):
		result = module.search_by_artist_title("3 Doors Down", "Kryptonite")

	assert result is None


def test_returns_none_on_http_error_status_never_raises():
	error_response = _fake_response(status_code=500)
	error_response.raise_for_status.side_effect = module.requests.exceptions.HTTPError("500 server error")
	with patch.object(module.requests, "post", return_value=error_response):
		result = module.search_by_artist_title("3 Doors Down", "Kryptonite")

	assert result is None


def test_returns_none_on_malformed_json_response_never_raises():
	response = MagicMock()
	response.raise_for_status.return_value = None
	response.json.side_effect = ValueError("not JSON")
	with patch.object(module.requests, "post", return_value=response):
		result = module.search_by_artist_title("3 Doors Down", "Kryptonite")

	assert result is None


def test_returns_none_on_unexpected_response_shape_never_raises():
	with patch.object(module.requests, "post", return_value=_fake_response(json_data={"unexpected": "shape"})):
		result = module.search_by_artist_title("3 Doors Down", "Kryptonite")

	assert result is None
