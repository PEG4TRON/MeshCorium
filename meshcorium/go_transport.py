from __future__ import annotations

import os
import struct
import subprocess
import time

import pathlib
BINARY_PATH = str(pathlib.Path(__file__).resolve().parent.parent / "bin" / "meshcorium-transport")

TRANSPORT_FRAME_TIMEOUT_ERROR = "transport timeout while reading frame"


class GoSerialFrameError(RuntimeError):
    """Frame-level error from Go serial transport."""


class GoSerialTransport:
    """Byte-level and frame-level transport backed by Go serial binary.

    Spawns the ``meshcorium-transport`` Go binary as a subprocess and
    communicates via a length-prefixed binary protocol over stdin/stdout:

    * stdin:  [4-byte LE uint32 payload-length][payload bytes to send over serial]
    * stdout: [4-byte LE uint32 payload-length][payload bytes received from serial]
    * stderr: diagnostic logs

    Duck-typed compatible with both ``SerialPortTransport`` (byte transport)
    and ``UsbSerialFrameTransport`` (frame transport) — a single instance can
    be passed wherever either interface is expected.
    """

    transport_type = "serial"

    def __init__(
        self,
        device: str,
        baudrate: int = 115200,
        settle: float = 1.25,
        *,
        binary: str | None = None,
        frame_error: type[Exception] = GoSerialFrameError,
    ):
        self._device = str(device)
        self._baudrate = int(baudrate)
        self._settle = float(settle)
        self._timeout: float = 1.0
        self._frame_error = frame_error
        self._binary = binary or BINARY_PATH
        self._proc: subprocess.Popen | None = None

        if not os.path.isfile(self._binary):
            raise FileNotFoundError(
                f"Go transport binary not found: {self._binary}"
            )

        self._start_process()

    # ── identity ──────────────────────────────────────────────────────

    @property
    def port(self) -> str:
        return self._device

    # ── byte transport interface (SerialPortTransport duck-type) ──────

    @property
    def timeout(self) -> float | None:
        return self._timeout

    @timeout.setter
    def timeout(self, value: float | None) -> None:
        self._timeout = float(value) if value is not None else 1.0

    @property
    def in_waiting(self) -> int:
        return 0

    def read(self, size: int) -> bytes:
        """Read *size* raw bytes from stdout (blocking).

        For frame-oriented reads prefer :meth:`read_frame`.
        """
        if self._proc is None or self._proc.stdout is None:
            return b""
        try:
            data = self._proc.stdout.read(size)
        except Exception:
            return b""
        return data if data is not None else b""

    def write(self, data: bytes) -> int:
        """Write raw bytes to stdin.

        For frame-oriented writes prefer :meth:`write_frame` — the Go
        binary expects length-prefixed frames on stdin, so raw writes
        will break the protocol.
        """
        if self._proc is None or self._proc.stdin is None:
            return 0
        try:
            self._proc.stdin.write(data)
            self._proc.stdin.flush()
            return len(data)
        except Exception:
            return 0

    def flush(self) -> None:
        if self._proc is None or self._proc.stdin is None:
            return
        try:
            self._proc.stdin.flush()
        except Exception:
            pass

    def reset_input_buffer(self) -> None:
        pass

    def reset_output_buffer(self) -> None:
        pass

    def cancel_read(self) -> None:
        pass

    # ── frame transport interface (UsbSerialFrameTransport duck-type) ─

    def _error(self, message: str) -> Exception:
        return self._frame_error(message)

    def _start_process(self, dtr_toggle: bool = True) -> None:
        """Spawn the Go transport binary subprocess.

        Extracted from ``__init__`` so it can be reused for reconnection
        inside ``write_frame`` when the subprocess dies unexpectedly.
        """
        args = [
            self._binary,
            "--device", self._device,
            "--baudrate", str(self._baudrate),
            "--settle", f"{self._settle}s",
        ]
        if not dtr_toggle:
            args.append("--no-dtr")
        self._proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Give the binary a moment to open the serial port.
        time.sleep(0.15)
        returncode = self._proc.poll()
        if returncode is not None:
            stderr_data = b""
            try:
                stderr_data = self._proc.stderr.read()
            except Exception:
                pass
            try:
                self._proc.wait(timeout=1)
            except Exception:
                pass
            self._proc = None
            raise RuntimeError(
                f"Go transport binary exited with code {returncode}: "
                f"{stderr_data.decode(errors='replace')}"
            )

    def _read_exact_stdout(self, size: int) -> bytes:
        """Read exactly *size* bytes from subprocess stdout.

        If the subprocess dies mid-read (BrokenPipeError, ProcessLookupError,
        or EOFError), the old process is closed and a new one is spawned via
        :meth:`_start_process` before retrying the read once.
        """
        if self._proc is None or self._proc.stdout is None:
            raise self._error("transport closed")
        try:
            data = b""
            while len(data) < size:
                chunk = self._proc.stdout.read(size - len(data))
                if not chunk:
                    raise self._error(TRANSPORT_FRAME_TIMEOUT_ERROR)
                data += chunk
            return data
        except (BrokenPipeError, ProcessLookupError, EOFError):
            # Subprocess died — close it and reconnect.
            self.close()
            try:
                self._start_process(dtr_toggle=False)
            except Exception as exc:
                raise RuntimeError(
                    f"Go transport process died and reconnection failed: {exc}"
                ) from exc
            # Retry the read once against the fresh subprocess.
            try:
                data = b""
                while len(data) < size:
                    chunk = self._proc.stdout.read(size - len(data))
                    if not chunk:
                        raise self._error(TRANSPORT_FRAME_TIMEOUT_ERROR)
                    data += chunk
                return data
            except (BrokenPipeError, ProcessLookupError, EOFError) as exc:
                raise RuntimeError(
                    f"Go transport read failed again after reconnection: {exc}"
                ) from exc

    def read_exact(self, size: int) -> bytes:
        return self._read_exact_stdout(size)

    def read_frame(self) -> bytes:
        """Read a length-prefixed frame from the Go binary's stdout.

        Protocol: 4-byte little-endian uint32 payload length, then payload.

        If the subprocess dies mid-frame (BrokenPipeError, ProcessLookupError,
        or EOFError), the old process is closed and a new one is spawned via
        :meth:`_start_process` before retrying the entire frame read once.
        """
        try:
            length_bytes = self._read_exact_stdout(4)
            length = struct.unpack("<I", length_bytes)[0]
            if length == 0:
                return b""
            return self._read_exact_stdout(length)
        except (BrokenPipeError, ProcessLookupError, EOFError):
            # Subprocess died — close it and reconnect.
            self.close()
            try:
                self._start_process(dtr_toggle=False)
            except Exception as exc:
                raise RuntimeError(
                    f"Go transport process died and reconnection failed: {exc}"
                ) from exc
            # Retry the entire frame read once against the fresh subprocess.
            try:
                length_bytes = self._read_exact_stdout(4)
                length = struct.unpack("<I", length_bytes)[0]
                if length == 0:
                    return b""
                return self._read_exact_stdout(length)
            except (BrokenPipeError, ProcessLookupError, EOFError) as exc:
                raise RuntimeError(
                    f"Go transport read_frame failed again after reconnection: {exc}"
                ) from exc

    def write_frame(self, payload: bytes) -> None:
        """Write a length-prefixed frame to the Go binary's stdin.

        Protocol: 4-byte little-endian uint32 payload length, then payload.
        The Go binary forwards the payload to the serial device using its
        native framing (START1/START2 + 2-byte LE length).

        If the Go subprocess has died (BrokenPipeError / ProcessLookupError),
        the old process is closed and a new one is spawned via
        :meth:`_start_process` before retrying the write once.
        """
        if self._proc is None or self._proc.stdin is None:
            raise self._error("transport closed")
        header = struct.pack("<I", len(payload))
        frame = header + payload
        try:
            self._proc.stdin.write(frame)
            self._proc.stdin.flush()
        except (BrokenPipeError, ProcessLookupError):
            # Subprocess died — close it and reconnect.
            self.close()
            try:
                self._start_process(dtr_toggle=False)
            except Exception as exc:
                raise RuntimeError(
                    f"Go transport process died and reconnection failed: {exc}"
                ) from exc
            # Retry the write once against the fresh subprocess.
            try:
                self._proc.stdin.write(frame)
                self._proc.stdin.flush()
            except (BrokenPipeError, ProcessLookupError) as exc:
                raise RuntimeError(
                    f"Go transport write failed again after reconnection: {exc}"
                ) from exc

    # ── lifecycle ─────────────────────────────────────────────────────

    def close(self) -> None:
        """Terminate the Go binary subprocess."""
        if self._proc is None:
            return
        proc = self._proc
        self._proc = None

        # Close stdin to signal EOF.
        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except Exception:
            pass

        # Graceful SIGTERM.
        try:
            proc.terminate()
        except Exception:
            pass

        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass
        except Exception:
            pass

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


# ── factory ───────────────────────────────────────────────────────────

def open_go_transport(
    device: str,
    baudrate: int = 115200,
    *,
    settle: float = 1.25,
    frame_error: type[Exception] = GoSerialFrameError,
) -> tuple[GoSerialTransport, GoSerialTransport]:
    """Create a Go-backed serial transport pair.

    Returns ``(byte_transport, frame_transport)`` — a single
    :class:`GoSerialTransport` instance that satisfies both the
    ``SerialPortTransport`` byte-level interface and the
    ``UsbSerialFrameTransport`` frame-level interface.
    """
    transport = GoSerialTransport(
        device=device,
        baudrate=baudrate,
        settle=settle,
        frame_error=frame_error,
    )
    return transport, transport


class GoTransportAdapter:
    """Adapter that plugs Go-backed serial transport into the
    :class:`ConnectionRouter` / ``SerialTransportAdapter`` ecosystem.

    Drop-in replacement for ``SerialTransportAdapter`` — same
    ``transport_type``, ``discover()``, and ``open_client()`` signatures.
    """

    transport_type = "serial"

    def discover(self) -> list[dict[str, object]]:
        # Discovery uses pyserial (no Go binary needed for port enumeration).
        from meshcorium_serial_transport import discover_serial_ports

        ports: list[dict[str, object]] = []
        for item in discover_serial_ports():
            next_item: dict[str, object] = dict(item)
            device = str(next_item.get("device") or "").strip()
            next_item["transport_type"] = self.transport_type
            next_item["transport_id"] = device
            ports.append(next_item)
        return ports

    def open_client(self, descriptor) -> object:
        """Open a :class:`MeshCoreClient` over Go serial transport.

        *descriptor* must be a :class:`ConnectionDescriptor` with
        ``transport_type == \"serial\"``.
        """
        from meshcorium_client import MeshCoreClient, MeshCoreError

        if descriptor.transport_type != self.transport_type:
            raise ValueError(
                f"Go transport adapter cannot open {descriptor.transport_type}"
            )
        transport, frame_transport = open_go_transport(
            descriptor.port,
            descriptor.baudrate,
            frame_error=MeshCoreError,
        )
        return MeshCoreClient(
            port=descriptor.port,
            baudrate=descriptor.baudrate,
            timeout=descriptor.timeout,
            transport=transport,
            frame_transport=frame_transport,
        )
