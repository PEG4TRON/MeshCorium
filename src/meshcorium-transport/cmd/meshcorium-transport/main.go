// Command meshcorium-transport is a pipe-mode CLI for MeshCore serial frame
// transport. It bridges stdin/stdout (length-prefixed pipe protocol) with a
// MeshCore serial device via UsbSerialFrameTransport.
//
// Protocol (stdin/stdout):
//
//	[4 bytes LE uint32 length][frame payload — MeshCore frame bytes]
//
// Architecture:
//   - read goroutine: ReadFrame() from serial → write length-prefixed to stdout
//   - write goroutine: read length-prefixed from stdin → WriteFrame() to serial
//   - context with cancel propagates shutdown across goroutines
//   - SIGINT triggers graceful close (CancelRead unblocks serial I/O)
//   - structured logging to stderr (stdout is reserved for the pipe protocol)
//
// Flags:
//
//	--device   Serial device path (required, e.g. /dev/ttyACM0)
//	--baudrate Baud rate (default 115200)
//	--settle   Settle delay after opening port (default 1.25s)
package main

import (
	"context"
	"encoding/binary"
	"flag"
	"io"
	"log"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/PEG4TRON/MeshCorium/src/meshcorium"
	"go.bug.st/serial"
)

func main() {
	device := flag.String("device", "", "Serial device path (required, e.g. /dev/ttyACM0)")
	baudrate := flag.Int("baudrate", 115200, "Baud rate")
	settle := flag.Duration("settle", 1250*time.Millisecond, "Settle delay after opening port")
	noDTR := flag.Bool("no-dtr", false, "Skip DTR toggle (nRF52840 bootloader exit)")
	flag.Parse()

	if *device == "" {
		log.Fatal("meshcorium-transport: --device is required")
	}

	// Configure serial mode.
	mode := &serial.Mode{
		BaudRate: *baudrate,
	}

	// Open serial port.
	port, err := serial.Open(*device, mode)
	if err != nil {
		log.Fatalf("meshcorium-transport: open %s: %v", *device, err)
	}

	// DTR toggle: nRF52840 requires DTR low→high transition to exit
	// bootloader and start sending data. Without this, the device stays silent.
	// Skip when --no-dtr is set (e.g. device already out of bootloader).
	if !*noDTR {
		port.SetDTR(false)
		time.Sleep(200 * time.Millisecond)
		port.SetDTR(true)
	} else {
		log.Println("meshcorium-transport: DTR toggle skipped (--no-dtr)")
	}

	// Set read timeout so readPrefixedByte doesn't block forever.
	// 30s timeout to accommodate slow booting nRF52840 devices (5-10s boot after power-on).
	if err := port.SetReadTimeout(30 * time.Second); err != nil {
		log.Fatalf("meshcorium-transport: set read timeout: %v", err)
	}
	defer func() {
		if cerr := port.Close(); cerr != nil {
			log.Printf("meshcorium-transport: close %s: %v", *device, cerr)
		}
	}()

	log.Printf("meshcorium-transport: opened %s @ %d baud", *device, *baudrate)

	// Settle delay.
	if *settle > 0 {
		time.Sleep(*settle)
	}

	// Flush bootloader garbage from serial buffer after DTR toggle.
	port.ResetInputBuffer()

	// Build frame transport over serial port.
	frameTransport := meshcorium.NewUsbSerialFrameTransport(port)

	// Context propagates cancellation to both goroutines.
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	var wg sync.WaitGroup

	// --- Read goroutine: serial → stdout (length-prefixed) ---
	// Owner: main. Stop condition: ctx.Done() or I/O error.
	wg.Add(1)
	go func() {
		defer wg.Done()
		defer cancel() // propagate error to writer
		defer os.Stdin.Close() // unblock writer's io.ReadFull on stdin
		runReader(ctx, frameTransport, os.Stdout)
	}()

	// --- Write goroutine: stdin (length-prefixed) → serial ---
	// Owner: main. Stop condition: ctx.Done() or I/O error.
	wg.Add(1)
	go func() {
		defer wg.Done()
		defer cancel() // propagate error to reader
		runWriter(ctx, frameTransport, os.Stdin)
	}()

	// --- Signal handling ---
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	// Block until signal or context cancellation.
	select {
	case sig := <-sigCh:
		log.Printf("meshcorium-transport: received %v, initiating graceful shutdown", sig)
		cancel()
	case <-ctx.Done():
		// context cancelled by a goroutine (I/O error or EOF)
		log.Println("meshcorium-transport: context cancelled, shutting down")
	}

	// CancelRead unblocks any pending serial reads so goroutines can exit.
	// This is safe to call even if already closed.
	_ = frameTransport.CancelRead()

	// Wait for both goroutines to finish.
	wg.Wait()

	// Graceful close of the serial port.
	if err := frameTransport.Close(); err != nil {
		log.Printf("meshcorium-transport: close transport: %v", err)
	}

	log.Println("meshcorium-transport: shutdown complete")
}

// runReader reads MeshCore frames from serial and writes them to w
// as length-prefixed messages: [4 bytes LE uint32 length][frame payload].
//
// Exits on: context cancellation, read error, or write error.
func runReader(ctx context.Context, ft meshcorium.FrameTransport, w io.Writer) {
	for {
		// Check context before blocking read.
		if ctx.Err() != nil {
			return
		}

		frame, err := ft.ReadFrame()
		if err != nil {
			if ctx.Err() != nil {
				return // normal shutdown
			}
			log.Printf("meshcorium-transport: read frame: %v", err)
			return
		}

		// Write length prefix: 4 bytes little-endian uint32.
		lenBuf := make([]byte, 4)
		binary.LittleEndian.PutUint32(lenBuf, uint32(len(frame)))

		if _, err := w.Write(lenBuf); err != nil {
			log.Printf("meshcorium-transport: write stdout prefix: %v", err)
			return
		}

		// Write frame payload.
		if _, err := w.Write(frame); err != nil {
			log.Printf("meshcorium-transport: write stdout payload: %v", err)
			return
		}
	}
}

// readFullContext reads exactly len(buf) bytes from r into buf, or returns
// ctx.Err() when the context is cancelled. This prevents deadlocks: when the
// reader goroutine dies and cancels ctx, a writer stuck in io.ReadFull on
// os.Stdin will unblock immediately via the select on ctx.Done().
func readFullContext(ctx context.Context, r io.Reader, buf []byte) (int, error) {
	type result struct {
		n   int
		err error
	}
	ch := make(chan result, 1)
	go func() {
		n, err := io.ReadFull(r, buf)
		ch <- result{n, err}
	}()
	select {
	case <-ctx.Done():
		return 0, ctx.Err()
	case res := <-ch:
		return res.n, res.err
	}
}

// runWriter reads length-prefixed messages from r and writes them as MeshCore
// frames to the serial transport via WriteFrame.
//
// Protocol: [4 bytes LE uint32 length][payload bytes]
// Exits on: context cancellation, read error (EOF = graceful), or write error.
func runWriter(ctx context.Context, ft meshcorium.FrameTransport, r io.Reader) {
	for {
		// Check context before blocking read.
		if ctx.Err() != nil {
			return
		}

		// Read 4-byte length prefix (little-endian uint32).
		lenBuf := make([]byte, 4)
		if _, err := readFullContext(ctx, r, lenBuf); err != nil {
			if ctx.Err() != nil {
				return // normal shutdown
			}
			if err == io.EOF {
				log.Println("meshcorium-transport: stdin closed (EOF), shutting down")
				return
			}
			log.Printf("meshcorium-transport: read stdin prefix: %v", err)
			return
		}

		payloadLen := binary.LittleEndian.Uint32(lenBuf)

		if payloadLen == 0 {
			// Empty payload: still write an empty frame.
			if err := ft.WriteFrame(nil); err != nil {
				if ctx.Err() != nil {
					return
				}
				log.Printf("meshcorium-transport: write frame: %v", err)
				return
			}
			continue
		}

		// Read payload.
		payload := make([]byte, payloadLen)
		if _, err := readFullContext(ctx, r, payload); err != nil {
			if ctx.Err() != nil {
				return
			}
			log.Printf("meshcorium-transport: read stdin payload: %v", err)
			return
		}

		// Write frame to serial transport.
		if err := ft.WriteFrame(payload); err != nil {
			if ctx.Err() != nil {
				return
			}
			log.Printf("meshcorium-transport: write frame: %v", err)
			return
		}
	}
}
