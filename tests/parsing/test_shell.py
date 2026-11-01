import pytest
from toolpulse.parsing.shell import strip_timeout_wrapper


@pytest.mark.parametrize("raw,expected", [
    ("timeout 10 grep foo bar.txt", "grep foo bar.txt"),
    ("timeout --signal=KILL 5 python x.py", "python x.py"),
    ("timeout -s KILL -k 1 5 make", "make"),
    ("timeout 10 -- grep --name x", "-- grep --name x"),  # Legacy stops at the first non-flag token (duration), leaving -- in the command
    ("grep foo", "grep foo"),                 # passthrough
    ("timeout", "timeout"),                   # nothing after wrapper
    ("timeout 'bad quotes", "timeout 'bad quotes"),  # shlex failure -> original (never raises)
])
def test_strip_timeout_wrapper(raw, expected):
    assert strip_timeout_wrapper(raw) == expected
