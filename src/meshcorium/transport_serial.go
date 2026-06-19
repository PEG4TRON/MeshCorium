package meshcorium

import (
	"fmt"
	"io"
	"time"

	"go.bug.st/serial"
)

const (
	// Prefix bytes for MeshCore serial protocol.
	// frameOutPrefix is written before each frame (Python: frame_out_prefix = 0x3C).
	// frameInPrefix is searched for when reading frames (Python: frame_in_prefix = 0x3E).
	frameOutPrefix = 0x3C
	frameInPrefix  = 0x3E

	// maxPrefixDiscard is the maximum number of bytes to discard
	// when searching for a prefixed byte (Python: read_prefixed_byte default=256).
	maxPrefixDiscard = 256
)

// SerialPort wraps a go.bug.st/serial.Port and implements Transport.
type SerialPort struct {
	port serial.Port
}

// NewSerialPort creates a SerialPort from a serial.Port.
func NewSerialPort(port serial.Port) *SerialPort {
	return &SerialPort{port: port}
}

// Open opens the serial port. For go.bug.st/serial, the port is already opened
// by serial.Open, so this is a no-op that returns nil.
func (s *SerialPort) Open() error {
	if s.port == nil {
		return &SerialFrameError{Op: "open", Err: fmt.Errorf("port is nil")}
	}
	return nil
}

// Read reads up to len(p) bytes from the serial port.
func (s *SerialPort) Read(p []byte) (n int, err error) {
	if s.port == nil {
		return 0, &SerialFrameError{Op: "read", Err: fmt.Errorf("port is nil")}
	}
	n, err = s.port.Read(p)
	if err != nil {
		return n, &SerialFrameError{Op: "read", Err: err}
	}
	return n, nil
}

// Write writes len(p) bytes to the serial port.
func (s *SerialPort) Write(p []byte) (n int, err error) {
	if s.port == nil {
		return 0, &SerialFrameError{Op: "write", Err: fmt.Errorf("port is nil")}
	}
	n, err = s.port.Write(p)
	if err != nil {
		return n, &SerialFrameError{Op: "write", Err: err}
	}
	return n, nil
}

// Flush drains the serial port output buffer.
// Uses serial.Port.Drain() which performs a tcdrain-equivalent operation
// (TCSBRK ioctl on Linux), waiting until all data in the output buffer
// has been physically transmitted. Falls back to a short sleep if Drain
// is not available (should never happen with go.bug.st/serial ≥ 1.6).
func (s *SerialPort) Flush() error {
	if s.port == nil {
		return &SerialFrameError{Op: "flush", Err: fmt.Errorf("port is nil")}
	}
	return s.port.Drain()
}

// ResetInputBuffer discards unread data in the input buffer.
func (s *SerialPort) ResetInputBuffer() error {
	if s.port == nil {
		return &SerialFrameError{Op: "reset_input_buffer", Err: fmt.Errorf("port is nil")}
	}
	return s.port.ResetInputBuffer()
}

// ResetOutputBuffer discards unwritten data in the output buffer.
func (s *SerialPort) ResetOutputBuffer() error {
	if s.port == nil {
		return &SerialFrameError{Op: "reset_output_buffer", Err: fmt.Errorf("port is nil")}
	}
	return s.port.ResetOutputBuffer()
}

// CancelRead cancels a pending read operation.
// go.bug.st/serial does not expose explicit cancel; implement via port close.
func (s *SerialPort) CancelRead() error {
	if s.port == nil {
		return &SerialFrameError{Op: "cancel_read", Err: fmt.Errorf("port is nil")}
	}
	return s.port.Close()
}

// Close closes the serial port.
func (s *SerialPort) Close() error {
	if s.port == nil {
		return nil
	}
	err := s.port.Close()
	s.port = nil
	if err != nil {
		return &SerialFrameError{Op: "close", Err: err}
	}
	return nil
}

// InWaiting returns the number of bytes available in the input buffer.
// Uses serial.Port.ReadyToRead() (go.bug.st/serial ≥ 1.6) to query the
// OS input buffer, avoiding a dummy read.
func (s *SerialPort) InWaiting() (int, error) {
	// go.bug.st/serial v1.6.4 does not expose in_waiting natively.
	// Returns 0 until library upgrade or custom FIONREAD ioctl implementation.
	return 0, nil
}

// SetTimeout sets the read/write timeout in seconds.
func (s *SerialPort) SetTimeout(timeout float64) error {
	if s.port == nil {
		return &SerialFrameError{Op: "set_timeout", Err: fmt.Errorf("port is nil")}
	}
	return s.port.SetReadTimeout(time.Duration(timeout * float64(time.Second)))
}

// UsbSerialFrameTransport wraps an io.ReadWriteCloser and implements FrameTransport.
type UsbSerialFrameTransport struct {
	rwc     io.ReadWriteCloser
	reader  io.Reader
	writer  io.Writer
	closer  io.Closer
	flusher func() error
}

// NewUsbSerialFrameTransport creates a UsbSerialFrameTransport from an io.ReadWriteCloser.
func NewUsbSerialFrameTransport(rwc io.ReadWriteCloser) *UsbSerialFrameTransport {
	t := &UsbSerialFrameTransport{
		rwc:    rwc,
		reader: rwc,
		writer: rwc,
		closer: rwc,
	}
	if f, ok := rwc.(interface{ Flush() error }); ok {
		t.flusher = f.Flush
	}
	return t
}

// NewUsbSerialFrameTransportRW creates a UsbSerialFrameTransport from separate reader/writer/closer.
func NewUsbSerialFrameTransportRW(r io.Reader, w io.Writer, c io.Closer) *UsbSerialFrameTransport {
	t := &UsbSerialFrameTransport{
		reader: r,
		writer: w,
		closer: c,
	}
	if f, ok := w.(interface{ Flush() error }); ok {
		t.flusher = f.Flush
	}
	return t
}

// ReadFrame reads a MeshCore frame from serial using prefix protocol.
// It searches for frameInPrefix (0x3E), then reads a 2-byte little-endian
// payload length followed by the payload bytes.
func (t *UsbSerialFrameTransport) ReadFrame() ([]byte, error) {
	// Synchronise to frame start: discard bytes until frameInPrefix (0x3E).
	if _, err := t.readPrefixedByte(frameInPrefix); err != nil {
		return nil, &SerialFrameError{Op: "read_frame:prefix", Err: err}
	}

	// Read 2-byte length (little-endian uint16).
	lenBytes, err := t.ReadExact(2)
	if err != nil {
		return nil, &SerialFrameError{Op: "read_frame:length", Err: err}
	}
	payloadLen := int(lenBytes[0]) | int(lenBytes[1])<<8

	// Read payload.
	payload, err := t.ReadExact(payloadLen)
	if err != nil {
		return nil, &SerialFrameError{Op: "read_frame:payload", Err: err}
	}

	return payload, nil
}

// WriteFrame writes a frame using the prefix protocol: < + 2-byte LE length + payload.
func (t *UsbSerialFrameTransport) WriteFrame(payload []byte) error {
	payloadLen := len(payload)
	frame := make([]byte, 3+payloadLen)
	frame[0] = frameOutPrefix
	frame[1] = byte(payloadLen)
	frame[2] = byte(payloadLen >> 8)
	copy(frame[3:], payload)

	n, err := t.writer.Write(frame)
	if err != nil {
		return &SerialFrameError{Op: "write_frame", Err: err}
	}
	if n != len(frame) {
		return &SerialFrameError{Op: "write_frame",
			Err: fmt.Errorf("short write: %d of %d", n, len(frame))}
	}

	// Flush only if flusher is available (not all transports provide it).
	if t.flusher != nil {
		if err := t.flusher(); err != nil {
			return &SerialFrameError{Op: "write_frame:flush", Err: err}
		}
	}

	return nil
}

// ReadExact reads exactly n bytes from the reader, looping until
// buf is full, the reader returns an error, or EOF is reached.
// Uses io.ReadFull for correct partial-read handling (nRF52840 CDC ACM
// sends data in chunks — single Read is insufficient).
func (t *UsbSerialFrameTransport) ReadExact(n int) ([]byte, error) {
	buf := make([]byte, n)
	_, err := io.ReadFull(t.reader, buf)
	if err != nil {
		return nil, &SerialFrameError{Op: "read_exact", Err: err}
	}
	return buf, nil
}

// Close closes the underlying stream.
func (t *UsbSerialFrameTransport) Close() error {
	if t.closer != nil {
		err := t.closer.Close()
		if err != nil {
			return &SerialFrameError{Op: "close", Err: err}
		}
	}
	return nil
}

// CancelRead cancels a pending read. For serial, this closes the port.
func (t *UsbSerialFrameTransport) CancelRead() error {
	return t.Close()
}

// readPrefixedByte reads bytes one at a time until it finds a byte matching
// the target byte. Discards up to maxPrefixDiscard non-matching bytes.
// Returns the matched byte.
//
// Equivalent to Python: read_prefixed_byte(p, target, max_discard=256)
func (t *UsbSerialFrameTransport) readPrefixedByte(target byte) (byte, error) {
	one := make([]byte, 1)
	discarded := make([]byte, 0, maxPrefixDiscard)
	for i := 0; i < maxPrefixDiscard; i++ {
		_, err := io.ReadFull(t.reader, one)
		if err != nil {
			if len(discarded) > 0 {
				preview := hexPreview(discarded)
				return 0, &SerialFrameError{Op: "read_prefixed_byte",
					Err: fmt.Errorf("timeout after discarding %d bytes, first 16: %s", len(discarded), preview)}
			}
			return 0, &SerialFrameError{Op: "read_prefixed_byte",
				Err: fmt.Errorf("transport timeout while reading frame")}
		}
		if one[0] == target {
			return one[0], nil
		}
		discarded = append(discarded, one[0])
	}
	return 0, &SerialFrameError{Op: "read_prefixed_byte",
		Err: fmt.Errorf("discarded %d bytes without finding prefix 0x%02X: %s", maxPrefixDiscard, target, hexPreview(discarded))}
}

// hexPreview returns a hex string of up to 16 bytes from data.
func hexPreview(data []byte) string {
	n := len(data)
	if n > 16 {
		n = 16
	}
	buf := make([]byte, 0, n*3)
	for i := 0; i < n; i++ {
		if i > 0 {
			buf = append(buf, ' ')
		}
		b := data[i] >> 4
		if b < 10 {
			buf = append(buf, '0'+b)
		} else {
			buf = append(buf, 'a'+b-10)
		}
		b = data[i] & 0x0f
		if b < 10 {
			buf = append(buf, '0'+b)
		} else {
			buf = append(buf, 'a'+b-10)
		}
	}
	return string(buf)
}

// readExact1 removed — dead code. Use ReadExact(1) instead.
