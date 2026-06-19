from __future__ import annotations

import argparse
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterable

from meshcorium_client import (
    DEFAULT_APP_NAME,
    DEFAULT_APP_VERSION,
    DEFAULT_BAUDRATE,
    DEFAULT_PROTOCOL_VERSION,
    DEFAULT_TIMEOUT,
    PUSH_MSG_WAITING,
    BatteryInfo,
    ChannelInfo,
    Contact,
    CoreStats,
    DeviceInfo,
    MeshCoreError,
    MeshCoreSerialClient,
    MessageEvent,
    RadioStats,
    SelfInfo,
    SelfTelemetry,
    SentMessageInfo,
    SerialException,
    format_hex,
    format_latlon,
    utc_now_epoch,
)
from meshcorium_transport import DEFAULT_CONNECTION_ROUTER


def discover_ports() -> list[dict[str, str]]:
    return list(DEFAULT_CONNECTION_ROUTER.discover("serial") or [])


def auto_pick_port() -> str:
    ports = discover_ports()
    if not ports:
        raise MeshCoreError("no serial ports found; pass --port explicitly")
    for port in ports:
        text = " ".join(port.values()).lower()
        if "heltec" in text or "cp210" in text or "usb serial" in text or "ch340" in text:
            return port["device"]
    return ports[0]["device"]


def open_client(args: argparse.Namespace) -> MeshCoreSerialClient:
    port = args.port or auto_pick_port()
    descriptor = DEFAULT_CONNECTION_ROUTER.from_legacy_serial_kwargs(
        port=port,
        baudrate=args.baudrate,
        timeout=args.timeout,
    )
    return DEFAULT_CONNECTION_ROUTER.open_client(descriptor)


@contextmanager
def _open_serial_client(
    *,
    port: str,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
):
    descriptor = DEFAULT_CONNECTION_ROUTER.from_legacy_serial_kwargs(
        port=port,
        baudrate=baudrate,
        timeout=timeout,
    )
    with DEFAULT_CONNECTION_ROUTER.open_client(descriptor) as client:
        yield client


def print_device_info(device_info: DeviceInfo) -> None:
    print(f"firmware_ver: {device_info.firmware_ver}")
    print(f"semantic_version: {device_info.semantic_version}")
    print(f"build_date: {device_info.firmware_build_date}")
    print(f"model: {device_info.manufacturer_model}")
    print(f"max_contacts: {device_info.max_contacts_div_2 * 2}")
    print(f"max_channels: {device_info.max_channels}")
    print(f"ble_pin: {device_info.ble_pin}")


def print_self_info(self_info: SelfInfo) -> None:
    print(f"name: {self_info.name}")
    print(f"public_key: {format_hex(self_info.public_key)}")
    print(f"adv_type: {self_info.adv_type}")
    print(f"tx_power_dbm: {self_info.tx_power_dbm}")
    print(f"max_tx_power: {self_info.max_tx_power}")
    print(f"radio_freq_hz_x1000: {self_info.radio_freq}")
    print(f"radio_bw_hz_x1000: {self_info.radio_bw}")
    print(f"radio_sf: {self_info.radio_sf}")
    print(f"radio_cr: {self_info.radio_cr}")
    print(f"lat: {format_latlon(self_info.adv_lat):.6f}")
    print(f"lon: {format_latlon(self_info.adv_lon):.6f}")
    print(f"multi_acks: {self_info.multi_acks}")
    print(f"advert_loc_policy: {self_info.advert_loc_policy}")
    print(f"telemetry_modes: {self_info.telemetry_modes}")
    print(f"manual_add_contacts: {self_info.manual_add_contacts}")


def print_contact(contact: Contact) -> None:
    print(
        f"pubkey={format_hex(contact.public_key)} name={contact.adv_name!r} "
        f"type={contact.adv_type} flags={contact.flags} lastmod={contact.lastmod} "
        f"lat={format_latlon(contact.adv_lat):.6f} lon={format_latlon(contact.adv_lon):.6f}"
    )


def print_message(event: MessageEvent) -> None:
    print(f"message_code={event.code} payload_hex={event.payload.hex()}")


def cmd_ports(_args: argparse.Namespace) -> int:
    ports = discover_ports()
    if not ports:
        print("No serial ports found.")
        return 1
    for port in ports:
        print(
            f"{port['device']}: {port['description']} | "
            f"{port['manufacturer']} | {port['product']} | {port['hwid']}"
        )
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    with open_client(args) as client:
        device_info = client.query_device(args.protocol_version)
        print_device_info(device_info)
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    with open_client(args) as client:
        device_info = client.query_device(args.protocol_version)
        self_info = client.app_start(args.app_name, args.app_version)
        print("[device]")
        print_device_info(device_info)
        print()
        print("[self]")
        print_self_info(self_info)
    return 0


def cmd_time_get(args: argparse.Namespace) -> int:
    with open_client(args) as client:
        client.query_device(args.protocol_version)
        client.app_start(args.app_name, args.app_version)
        epoch = client.get_device_time()
        print(f"epoch: {epoch}")
        print(f"utc: {datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()}")
    return 0


def cmd_time_set(args: argparse.Namespace) -> int:
    epoch = args.epoch if args.epoch is not None else utc_now_epoch()
    with open_client(args) as client:
        client.query_device(args.protocol_version)
        client.app_start(args.app_name, args.app_version)
        client.set_device_time(epoch)
        print(f"set epoch: {epoch}")
        print(f"utc: {datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()}")
    return 0


def cmd_time_sync(args: argparse.Namespace) -> int:
    epoch = utc_now_epoch()
    with open_client(args) as client:
        client.query_device(args.protocol_version)
        client.app_start(args.app_name, args.app_version)
        before = client.get_device_time()
        client.set_device_time(epoch)
        after = client.get_device_time()
        print(f"before: {before} ({datetime.fromtimestamp(before, tz=timezone.utc).isoformat()})")
        print(f"after: {after} ({datetime.fromtimestamp(after, tz=timezone.utc).isoformat()})")
    return 0


def cmd_contacts(args: argparse.Namespace) -> int:
    with open_client(args) as client:
        client.query_device(args.protocol_version)
        client.app_start(args.app_name, args.app_version)
        cursor, contacts = client.get_contacts(args.since)
        print(f"contacts: {len(contacts)}")
        print(f"next_since: {cursor}")
        for contact in contacts:
            print_contact(contact)
    return 0


def handle_push(client: MeshCoreSerialClient, frame: bytes, auto_sync_messages: bool) -> None:
    code = frame[0]
    if code == PUSH_MSG_WAITING and auto_sync_messages:
        result = client.drain_queued_messages()
        for event in result.messages:
            print_message(event)
        print("queue empty")
        return
    print(f"push_code={code} payload_hex={frame[1:].hex()}")


def cmd_listen(args: argparse.Namespace) -> int:
    with open_client(args) as client:
        client.query_device(args.protocol_version)
        self_info = client.app_start(args.app_name, args.app_version)
        print(f"connected: {self_info.name} {client.port}")
        if args.sync_time:
            client.set_device_time(utc_now_epoch())
            print("time synced")
        print("listening...")
        while True:
            frame = client.wait_for_frame()
            handle_push(client, frame, auto_sync_messages=not args.no_message_sync)


def cmd_advert(args: argparse.Namespace) -> int:
    with open_client(args) as client:
        client.query_device(args.protocol_version)
        client.app_start(args.app_name, args.app_version)
        if args.name:
            client.set_advert_name(args.name)
            print(f"advert name updated: {args.name}")
        client.send_self_advert(flood=args.flood)
        print("advert sent")
    return 0


def fetch_probe(
    port: str,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
) -> DeviceInfo:
    with _open_serial_client(port=port, baudrate=baudrate, timeout=timeout) as client:
        return client.query_device(protocol_version)


def fetch_info(
    port: str,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> tuple[DeviceInfo, SelfInfo]:
    with _open_serial_client(port=port, baudrate=baudrate, timeout=timeout) as client:
        return client.query_device(protocol_version), client.app_start(app_name, app_version)


def fetch_time(
    port: str,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> int:
    with _open_serial_client(port=port, baudrate=baudrate, timeout=timeout) as client:
        client.query_device(protocol_version)
        client.app_start(app_name, app_version)
        return client.get_device_time()


def sync_time(
    port: str,
    epoch: int | None = None,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> tuple[int, int]:
    target = epoch if epoch is not None else utc_now_epoch()
    with _open_serial_client(port=port, baudrate=baudrate, timeout=timeout) as client:
        client.query_device(protocol_version)
        client.app_start(app_name, app_version)
        before = client.get_device_time()
        client.set_device_time(target)
        after = client.get_device_time()
        return before, after


def fetch_contacts(
    port: str,
    since: int | None = None,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> tuple[int, list[Contact]]:
    with _open_serial_client(port=port, baudrate=baudrate, timeout=timeout) as client:
        client.query_device(protocol_version)
        client.app_start(app_name, app_version)
        return client.get_contacts(since)


def fetch_channels(
    port: str,
    max_channels: int | None = None,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> list[ChannelInfo]:
    with _open_serial_client(port=port, baudrate=baudrate, timeout=timeout) as client:
        device = client.query_device(protocol_version)
        client.app_start(app_name, app_version)
        count = max_channels if max_channels is not None else device.max_channels
        return [client.get_channel(index) for index in range(max(0, count))]


def set_channel_config(
    *,
    port: str,
    channel_idx: int,
    channel_name: str,
    channel_secret: bytes | None = None,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
) -> ChannelInfo:
    with _open_serial_client(port=port, baudrate=baudrate, timeout=timeout) as client:
        client.set_channel(channel_idx, channel_name, channel_secret)
        return client.get_channel(channel_idx)


def fetch_radio_stats(
    port: str,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> RadioStats:
    with _open_serial_client(port=port, baudrate=baudrate, timeout=timeout) as client:
        client.query_device(protocol_version)
        client.app_start(app_name, app_version)
        return client.get_radio_stats()


def fetch_core_stats(
    port: str,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> CoreStats:
    with _open_serial_client(port=port, baudrate=baudrate, timeout=timeout) as client:
        client.query_device(protocol_version)
        client.app_start(app_name, app_version)
        return client.get_core_stats()


def fetch_self_telemetry(
    port: str,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> SelfTelemetry:
    with _open_serial_client(port=port, baudrate=baudrate, timeout=timeout) as client:
        client.query_device(protocol_version)
        client.app_start(app_name, app_version)
        return client.get_self_telemetry()


def fetch_battery_info(
    port: str,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> BatteryInfo:
    with _open_serial_client(port=port, baudrate=baudrate, timeout=timeout) as client:
        client.query_device(protocol_version)
        client.app_start(app_name, app_version)
        return client.get_battery_info()


def fetch_connect_snapshot(
    port: str,
    since: int | None = None,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> tuple[DeviceInfo, SelfInfo, int, list[Contact], list[ChannelInfo], RadioStats | None, SelfTelemetry | None]:
    with _open_serial_client(port=port, baudrate=baudrate, timeout=timeout) as client:
        device = client.query_device(protocol_version)
        self_info = client.app_start(app_name, app_version)
        cursor, contacts = client.get_contacts(since)
        channels = [client.get_channel(index) for index in range(device.max_channels)]
        try:
            radio_stats = client.get_radio_stats()
        except MeshCoreError:
            radio_stats = None
        try:
            self_telemetry = client.get_self_telemetry()
        except MeshCoreError:
            self_telemetry = None
        return device, self_info, cursor, contacts, channels, radio_stats, self_telemetry


def send_advert(
    port: str,
    flood: bool = False,
    name: str | None = None,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> None:
    with _open_serial_client(port=port, baudrate=baudrate, timeout=timeout) as client:
        client.query_device(protocol_version)
        client.app_start(app_name, app_version)
        if name:
            client.set_advert_name(name)
        client.send_self_advert(flood=flood)


def send_contact_text(
    port: str,
    destination_public_key: bytes,
    text: str,
    timestamp: int | None = None,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> tuple[SentMessageInfo, bool]:
    with _open_serial_client(port=port, baudrate=baudrate, timeout=timeout) as client:
        client.query_device(protocol_version)
        client.app_start(app_name, app_version)
        sent = client.send_contact_text_message(destination_public_key, text, timestamp=timestamp)
        ack_timeout = max(5.0, min((sent.suggested_timeout_ms / 1000.0) * 1.2, 30.0))
        return sent, client.wait_for_ack(sent.expected_ack, ack_timeout)


def send_channel_text(
    port: str,
    channel_idx: int,
    text: str,
    timestamp: int | None = None,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> SentMessageInfo:
    with _open_serial_client(port=port, baudrate=baudrate, timeout=timeout) as client:
        client.query_device(protocol_version)
        client.app_start(app_name, app_version)
        return client.send_channel_text_message(channel_idx, text, timestamp=timestamp)


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", help="Serial port, e.g. /dev/ttyUSB0")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--protocol-version", type=int, default=DEFAULT_PROTOCOL_VERSION)
    parser.add_argument("--app-version", type=int, default=DEFAULT_APP_VERSION)
    parser.add_argument("--app-name", default=DEFAULT_APP_NAME)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Meshcorium companion USB client")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ports_parser = subparsers.add_parser("ports", help="List serial ports")
    ports_parser.set_defaults(func=cmd_ports)

    probe_parser = subparsers.add_parser("probe", help="Query device info")
    add_common_arguments(probe_parser)
    probe_parser.set_defaults(func=cmd_probe)

    info_parser = subparsers.add_parser("info", help="Query device info and self info")
    add_common_arguments(info_parser)
    info_parser.set_defaults(func=cmd_info)

    time_parser = subparsers.add_parser("time", help="Get or set device clock")
    time_subparsers = time_parser.add_subparsers(dest="time_command", required=True)

    time_get = time_subparsers.add_parser("get", help="Read device time")
    add_common_arguments(time_get)
    time_get.set_defaults(func=cmd_time_get)

    time_set = time_subparsers.add_parser("set", help="Set device time")
    add_common_arguments(time_set)
    time_set.add_argument("--epoch", type=int, help="Epoch seconds in UTC; default is current UTC time")
    time_set.set_defaults(func=cmd_time_set)

    time_sync = time_subparsers.add_parser("sync", help="Sync device time to current UTC")
    add_common_arguments(time_sync)
    time_sync.set_defaults(func=cmd_time_sync)

    contacts_parser = subparsers.add_parser("contacts", help="Download contacts list")
    add_common_arguments(contacts_parser)
    contacts_parser.add_argument("--since", type=int)
    contacts_parser.set_defaults(func=cmd_contacts)

    listen_parser = subparsers.add_parser("listen", help="Listen for push events")
    add_common_arguments(listen_parser)
    listen_parser.add_argument("--sync-time", action="store_true", help="Set device time on connect")
    listen_parser.add_argument(
        "--no-message-sync",
        action="store_true",
        help="Do not auto-fetch queued messages on PUSH_MSG_WAITING",
    )
    listen_parser.set_defaults(func=cmd_listen)

    advert_parser = subparsers.add_parser("advert", help="Send self advert")
    add_common_arguments(advert_parser)
    advert_parser.add_argument("--flood", action="store_true", help="Send flood advert instead of zero-hop")
    advert_parser.add_argument("--name", help="Update advert name before sending")
    advert_parser.set_defaults(func=cmd_advert)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return args.func(args)
    except SerialException as exc:
        print(f"Serial error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except MeshCoreError as exc:
        print(f"Meshcorium error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
