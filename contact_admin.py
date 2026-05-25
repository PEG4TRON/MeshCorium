from __future__ import annotations

import time

from contact_service import effective_node_contact_limit
from contact_store import ADVERT_TYPE_REPEATER


def _connection_access_context(session_kwargs: dict, *, connection_access=None, serial_port_access=None):
    if connection_access is not None:
        return connection_access(session_kwargs)
    if serial_port_access is None:
        raise ValueError("connection_access or serial_port_access is required")
    return serial_port_access(session_kwargs["port"])


def remove_contacts_and_reload(
    session_kwargs: dict,
    *,
    mode: str,
    protect_favorites: bool,
    client_factory,
    connection_access=None,
    serial_port_access=None,
    is_favorite_contact,
    get_contact_message_stats,
    contact_to_dict,
    mark_cached_contacts_removed_from_node,
    prepare_contacts_snapshot,
) -> tuple[list[dict], dict]:
    direct_stats = get_contact_message_stats()

    def _has_local_direct_history(contact: dict) -> bool:
        prefix = str(contact.get("public_key") or "").strip().lower()[:12]
        if not prefix:
            return False
        local = direct_stats.get(prefix, {})
        return int(local.get("last_message_at") or 0) > 0

    def _filter_contacts_for_removal(contacts: list[dict]) -> list[dict]:
        items = []
        for contact in contacts:
            if mode == "repeaters-only" and int(contact.get("adv_type", 0)) != ADVERT_TYPE_REPEATER:
                continue
            if mode == "non-favorites-no-direct":
                if is_favorite_contact(contact):
                    continue
                if _has_local_direct_history(contact):
                    continue
            if protect_favorites and is_favorite_contact(contact):
                continue
            items.append(contact)
        return items

    def _build_remove_summary(
        *,
        contacts_dict: list[dict],
        to_remove: list[dict],
        next_cursor: int,
        hard_device_limit: int,
    ) -> tuple[list[dict], dict]:
        mark_cached_contacts_removed_from_node(
            [str(contact.get("public_key") or "").strip().lower() for contact in to_remove]
        )
        remaining_contacts_dict = prepare_contacts_snapshot(contacts_dict)
        return remaining_contacts_dict, {
            "removed": len(to_remove),
            "remaining": len(remaining_contacts_dict),
            "cursor": next_cursor,
            "max_contacts": effective_node_contact_limit(
                remaining_contacts_dict,
                hard_device_limit=hard_device_limit,
            ),
        }

    def _reload_contacts_after_bulk_remove() -> tuple[int, list]:
        # After a long remove-contact burst some radios briefly stop answering
        # cleanly on the same serial session, so reload via a fresh session.
        attempts = (
            {"sleep_secs": 0.0},
            {"sleep_secs": 1.25},
        )
        last_error = None
        for attempt in attempts:
            try:
                if attempt["sleep_secs"] > 0:
                    time.sleep(float(attempt["sleep_secs"]))
                with _connection_access_context(session_kwargs, connection_access=connection_access, serial_port_access=serial_port_access):
                    with client_factory(
                        port=session_kwargs["port"],
                        baudrate=session_kwargs["baudrate"],
                        timeout=session_kwargs["timeout"],
                    ) as reload_client:
                        reload_client.query_device(session_kwargs["protocol_version"])
                        reload_client.app_start(session_kwargs["app_name"], session_kwargs["app_version"])
                        return reload_client.get_contacts(None)
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise RuntimeError("bulk-remove reload failed without a captured exception")

    with _connection_access_context(session_kwargs, connection_access=connection_access, serial_port_access=serial_port_access):
        with client_factory(
            port=session_kwargs["port"],
            baudrate=session_kwargs["baudrate"],
            timeout=session_kwargs["timeout"],
        ) as client:
            device = client.query_device(session_kwargs["protocol_version"])
            client.app_start(session_kwargs["app_name"], session_kwargs["app_version"])
            _cursor, contacts = client.get_contacts(None)
            contacts_dict = [contact_to_dict(contact) for contact in contacts]
            to_remove = _filter_contacts_for_removal(contacts_dict)
            for contact in to_remove:
                client.remove_contact(bytes.fromhex(str(contact["public_key"])))
    next_cursor, remaining_contacts = _reload_contacts_after_bulk_remove()
    return _build_remove_summary(
        contacts_dict=remaining_contacts,
        to_remove=to_remove,
        next_cursor=next_cursor,
        hard_device_limit=int(device.max_contacts_div_2 * 2),
    )


def remove_contacts_with_client(
    client,
    *,
    mode: str,
    protect_favorites: bool,
    hard_device_limit: int,
    is_favorite_contact,
    get_contact_message_stats,
    contact_to_dict,
    mark_cached_contacts_removed_from_node,
    prepare_contacts_snapshot,
) -> tuple[list[dict], dict]:
    direct_stats = get_contact_message_stats()

    def _has_local_direct_history(contact: dict) -> bool:
        prefix = str(contact.get("public_key") or "").strip().lower()[:12]
        if not prefix:
            return False
        local = direct_stats.get(prefix, {})
        return int(local.get("last_message_at") or 0) > 0

    def _filter_contacts_for_removal(contacts: list[dict]) -> list[dict]:
        items = []
        for contact in contacts:
            if mode == "repeaters-only" and int(contact.get("adv_type", 0)) != ADVERT_TYPE_REPEATER:
                continue
            if mode == "non-favorites-no-direct":
                if is_favorite_contact(contact):
                    continue
                if _has_local_direct_history(contact):
                    continue
            if protect_favorites and is_favorite_contact(contact):
                continue
            items.append(contact)
        return items

    _cursor, contacts = client.get_contacts(None)
    contacts_dict = [contact_to_dict(contact) for contact in contacts]
    to_remove = _filter_contacts_for_removal(contacts_dict)
    for contact in to_remove:
        client.remove_contact(bytes.fromhex(str(contact["public_key"])))
    attempts = (0.0, 0.5, 1.25)
    last_error = None
    for sleep_secs in attempts:
        try:
            if sleep_secs > 0:
                time.sleep(float(sleep_secs))
            next_cursor, remaining_contacts = client.get_contacts(None)
            return _build_remove_summary(
                contacts_dict=remaining_contacts,
                to_remove=to_remove,
                next_cursor=next_cursor,
                hard_device_limit=hard_device_limit,
            )
        except Exception as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("bulk-remove reload failed without a captured exception")
