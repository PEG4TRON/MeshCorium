// Package meshcorium provides transport abstractions for MeshCore companion radio.
package meshcorium

import "fmt"

// Transport defines the low-level stream transport interface.
// Accept interfaces, return structs (golang-pro idiom).
type Transport interface {
	Open() error
	Read(p []byte) (n int, err error)
	Write(p []byte) (n int, err error)
	Flush() error
	ResetInputBuffer() error
	ResetOutputBuffer() error
	CancelRead() error
	Close() error
	InWaiting() (int, error)
	SetTimeout(timeout float64) error
}

// FrameTransport defines frame-level read/write operations over a stream.
type FrameTransport interface {
	ReadFrame() ([]byte, error)
	WriteFrame(payload []byte) error
	ReadExact(n int) ([]byte, error)
	Close() error
	CancelRead() error
}

// ConnectionDescriptor describes a discovered serial port.
type ConnectionDescriptor struct {
	Device       string
	Name         string
	VID          string
	PID          string
	SerialNumber string
}

// SerialFrameError wraps frame-level errors with an operation name.
type SerialFrameError struct {
	Op  string
	Err error
}

// Error implements the error interface.
func (e *SerialFrameError) Error() string {
	if e.Err != nil {
		return fmt.Sprintf("meshcorium: %s: %v", e.Op, e.Err)
	}
	return fmt.Sprintf("meshcorium: %s", e.Op)
}

// Unwrap returns the wrapped error for errors.Is/As support.
func (e *SerialFrameError) Unwrap() error {
	return e.Err
}
