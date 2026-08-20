"""Tests for channel slot safety: CAS, idempotent create, idx=0, range validation."""

import pytest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# We need to import from meshcorium_web without triggering its top-level code.
# Use a subprocess approach or mock imports.
# Actually, let's test the helper functions directly by importing them.
# Since meshcorium_web has side effects at import, we'll extract helpers.

import importlib.util
import types

def _load_helper_functions():
    """Load helper functions from meshcorium_web.py without side effects."""
    path = os.path.join(os.path.dirname(__file__), '..', 'meshcorium', 'meshcorium_web.py')
    spec = importlib.util.spec_from_file_location("meshcorium_web_helpers", path)
    
    # Create a mock module to catch the import
    module = types.ModuleType(spec.name)
    
    # We need to provide enough stubs for the helper functions
    # The helpers we need don't use globals heavily, so we can try compiling just the functions
    
    with open(path, 'r') as f:
        source = f.read()
    
    # Extract the functions we need
    import re
    
    # Find all helper functions
    helpers = {}
    exec_globals = {
        '__builtins__': __builtins__,
        'int': int, 'str': str, 'bool': bool, 'dict': dict, 'list': list,
        'object': object, 'isinstance': isinstance, 'getattr': getattr,
        'len': len, 'sorted': sorted, 'next': next, 'iter': iter,
        'max': max, 'min': min, 'abs': abs, 'TypeError': TypeError,
        'ValueError': ValueError, 'Exception': Exception, 'bytes': bytes,
        'bytearray': bytearray,
        'MESHCORE_PUBLIC_CHANNEL_NAME': '#public',
        'MESHCORE_PUBLIC_CHANNEL_PSK_HEX': '',
        'hashlib': __import__('hashlib'),
        're': re, 'logging': __import__('logging'),
        'format_hex': lambda x: x.hex() if isinstance(x, (bytes, bytearray)) else str(x),
        '_normalize_channel_name': lambda x: str(x or '').strip().lower().lstrip('#'),
        '_normalize_channel_secret_hex': lambda x: str(x or '').strip().lower(),
        '_normalize_meshcore_channel_name': lambda x: str(x or '').strip().lower().lstrip('#'),
        '_resolve_channel_secret_hex_for_save': lambda name, secret: secret or '',
        '_is_meshcore_public_channel_name': lambda x: str(x or '').strip().lower().lstrip('#').startswith('public') or str(x or '').strip().startswith('#'),
        '_is_public_channel_name': lambda x: str(x or '').strip().lower().startswith('#'),
        '_build_channel_identity': lambda name, secret: f"{str(name or '').strip().lower()}:{str(secret or '').strip().lower()}" if secret else str(name or '').strip().lower(),
        '_pick_first_free_channel_idx_from_dicts': lambda channels, max_c: _pick_first_free(channels, max_c),
    }
    
    def _pick_first_free(channels, max_channels):
        used = set()
        for ch in (channels or []):
            idx = ch.get('idx', -1) if isinstance(ch, dict) else getattr(ch, 'channel_idx', -1)
            try:
                used.add(int(idx))
            except (TypeError, ValueError):
                pass
        for i in range(1, max_channels):
            if i not in used:
                return i
        raise ValueError("no free channel slots")
    
    exec_globals['_pick_first_free_channel_idx_from_dicts'] = _pick_first_free
    
    # Extract and exec the helper functions from the source
    func_names = [
        '_channel_idx_value', '_normalize_channel_identity',
        '_find_channel_by_idx', '_find_channel_by_identity',
        '_validate_channel_idx', '_resolve_channel_write_plan',
        '_channel_runtime_identity', '_channel_runtime_name',
        '_channel_runtime_secret_hex', 'ChannelConflictError',
        '_normalize_runtime_channel_fields',
    ]
    
    # Extract raw function source between defs
    extracted = {}
    
    # First find ChannelConflictError class
    match = re.search(r'class ChannelConflictError\(ValueError\):\s*"""Channel slot changed.*?"""', source)
    if match:
        exec(match.group(), exec_globals)
    
    for fname in func_names:
        if fname == 'ChannelConflictError':
            continue
        # Find the function definition
        pattern = rf'def {fname}\('
        m = re.search(pattern, source)
        if not m:
            continue
        start = m.start()
        # Find the matching end (next def at same indent level)
        rest = source[start:]
        lines = rest.split('\n')
        func_lines = []
        in_func = True
        for line in lines:
            func_lines.append(line)
            if in_func and len(func_lines) > 1:
                # Check if next line starts a new def/class at base indent
                if line and not line[0].isspace() and (line.startswith('def ') or line.startswith('class ')):
                    func_lines.pop()
                    break
        func_source = '\n'.join(func_lines)
        try:
            exec(func_source, exec_globals)
            extracted[fname] = exec_globals.get(fname)
        except Exception as e:
            print(f"WARNING: Could not exec {fname}: {e}")
    
    return exec_globals

ctx = _load_helper_functions()
_channel_idx_value = ctx.get('_channel_idx_value')
_normalize_channel_identity = ctx.get('_normalize_channel_identity')
_validate_channel_idx = ctx.get('_validate_channel_idx')
_resolve_channel_write_plan = ctx.get('_resolve_channel_write_plan')
ChannelConflictError = ctx.get('ChannelConflictError')
_build_channel_identity = ctx.get('_build_channel_identity')
_channel_runtime_identity = ctx.get('_channel_runtime_identity')
_channel_runtime_name = ctx.get('_channel_runtime_name')
_channel_runtime_secret_hex = ctx.get('_channel_runtime_secret_hex')
_is_meshcore_public_channel_name = ctx.get('_is_meshcore_public_channel_name')

from dataclasses import dataclass

@dataclass
class FakeChannel:
    channel_idx: int
    channel_name: str
    channel_secret: bytes
    channel_hash: str = ""

class FakeChannelClient:
    def __init__(self, channels=None, max_channels=8):
        self.channels = {}
        if channels:
            for ch in channels:
                self.channels[int(ch.channel_idx)] = ch
        self.max_channels = int(max_channels)
        self.set_calls = []
        self.delete_calls = []

    def get_channel(self, channel_idx):
        idx = int(channel_idx)
        return self.channels.get(idx, FakeChannel(idx, "", b""))

    def set_channel(self, channel_idx, channel_name, secret):
        idx = int(channel_idx)
        resolved = bytes(secret or b"")
        self.set_calls.append((idx, channel_name, resolved))
        self.channels[idx] = FakeChannel(idx, channel_name, resolved)

    def delete_channel(self, channel_idx):
        idx = int(channel_idx)
        self.delete_calls.append(idx)
        self.channels.pop(idx, None)


# === TESTS ===

class TestChannelIdxValue:
    def test_preserves_zero_dict(self):
        assert _channel_idx_value({"idx": 0}) == 0

    def test_preserves_zero_object(self):
        assert _channel_idx_value(FakeChannel(0, "#public", b"")) == 0

    def test_returns_default_for_none(self):
        assert _channel_idx_value({"idx": None}) == -1

    def test_returns_default_for_missing(self):
        assert _channel_idx_value({}) == -1


class TestNewChannelSlot:
    def test_uses_first_free_nonzero_slot(self):
        channels = [
            {"idx": 0, "name": "#public", "secret_hex": ""},
            {"idx": 1, "name": "#one", "secret_hex": "11" * 16},
            {"idx": 3, "name": "#three", "secret_hex": "33" * 16},
        ]
        plan = _resolve_channel_write_plan(
            requested_channel_idx=None,
            expected_channel_identity="",
            channel_name="#two",
            channel_secret_hex=None,
            existing_channels=channels,
            max_channels=8,
        )
        assert plan["target_idx"] == 2
        assert plan["created"] is True
        assert plan["idempotent"] is False


class TestIdempotentCreate:
    def test_duplicate_identity_is_idempotent(self):
        secret_hex = "ab" * 16
        identity = _build_channel_identity("private-room", secret_hex)
        channels = [
            {"idx": 4, "name": "private-room", "secret_hex": secret_hex,
             "channel_identity": identity},
        ]
        plan = _resolve_channel_write_plan(
            requested_channel_idx=None,
            expected_channel_identity="",
            channel_name="private-room",
            channel_secret_hex=secret_hex,
            existing_channels=channels,
            max_channels=8,
        )
        assert plan["target_idx"] == 4
        assert plan["created"] is False
        assert plan["idempotent"] is True


class TestStaleEdit:
    def test_stale_edit_is_rejected(self):
        old_secret = "11" * 16
        actual_secret = "22" * 16
        expected_identity = _build_channel_identity("room", old_secret)
        channels = [
            {"idx": 5, "name": "room", "secret_hex": actual_secret},
        ]
        with pytest.raises(ChannelConflictError, match="changed since"):
            _resolve_channel_write_plan(
                requested_channel_idx=5,
                expected_channel_identity=expected_identity,
                channel_name="renamed-room",
                channel_secret_hex="33" * 16,
                existing_channels=channels,
                max_channels=8,
            )


class TestDuplicateIdentity:
    def test_edit_cannot_duplicate_identity_from_other_slot(self):
        target_old_secret = "11" * 16
        requested_secret = "22" * 16
        channels = [
            {"idx": 2, "name": "target", "secret_hex": target_old_secret},
            {"idx": 6, "name": "existing", "secret_hex": requested_secret},
        ]
        expected_identity = _build_channel_identity("target", target_old_secret)
        with pytest.raises(ChannelConflictError, match="already exists"):
            _resolve_channel_write_plan(
                requested_channel_idx=2,
                expected_channel_identity=expected_identity,
                channel_name="existing",
                channel_secret_hex=requested_secret,
                existing_channels=channels,
                max_channels=8,
            )


class TestRangeValidation:
    @pytest.mark.parametrize("channel_idx", [-1, 8, 100])
    def test_out_of_range_is_rejected(self, channel_idx):
        with pytest.raises(ValueError, match="range"):
            _resolve_channel_write_plan(
                requested_channel_idx=channel_idx,
                expected_channel_identity="",
                channel_name="#test",
                channel_secret_hex=None,
                existing_channels=[],
                max_channels=8,
            )


class TestIdxZero:
    def test_non_public_cannot_use_idx_zero(self):
        with pytest.raises(ValueError, match="reserved"):
            _resolve_channel_write_plan(
                requested_channel_idx=0,
                expected_channel_identity="",
                channel_name="private",
                channel_secret_hex="11" * 16,
                existing_channels=[],
                max_channels=8,
            )
