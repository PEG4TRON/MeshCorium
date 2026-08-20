package meshcorium

import (
	"go.bug.st/serial"
)

// DiscoverSerialPorts returns a list of available serial port descriptors.
// GetPortsList returns port path strings; VID/PID/SerialNumber require
// opening each port and are left empty here.
func DiscoverSerialPorts() ([]ConnectionDescriptor, error) {
	ports, err := serial.GetPortsList()
	if err != nil {
		return nil, err
	}

	result := make([]ConnectionDescriptor, 0, len(ports))
	for _, portPath := range ports {
		result = append(result, ConnectionDescriptor{
			Device: portPath,
		})
	}
	return result, nil
}
