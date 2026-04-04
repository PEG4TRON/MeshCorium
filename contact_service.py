"""Contact orchestration for the hybrid contacts model.

Responsibilities here are intentionally limited to service-layer orchestration:
merging live companion contacts with the persistent SQLite mirror, performing
materialization/eviction decisions, and running companion sync operations.

The companion contact table is not treated as the full source of truth. It is a
transient active set layered on top of the backend-owned SQLite contact store.
"""

from __future__ import annotations

from collections.abc import Callable

from meshcorium_client import MeshCoreError, format_hex

CONTACT_FLAG_STAR = 0x01
BASE_NODE_NON_FAVORITE_CONTACT_LIMIT = 50


def favorite_contact_count(live_contacts: list[dict] | None = None) -> int:
    return sum(
        1
        for contact in list(live_contacts or [])
        if bool(int((contact or {}).get("flags", 0)) & CONTACT_FLAG_STAR)
    )


def non_favorite_contact_count(live_contacts: list[dict] | None = None) -> int:
    return sum(
        1
        for contact in list(live_contacts or [])
        if not bool(int((contact or {}).get("flags", 0)) & CONTACT_FLAG_STAR)
    )


def effective_node_contact_limit(
    live_contacts: list[dict] | None = None,
    *,
    reserve_favorite_slots: int = 0,
    hard_device_limit: int | None = None,
) -> int:
    limit = BASE_NODE_NON_FAVORITE_CONTACT_LIMIT
    if hard_device_limit is not None and int(hard_device_limit) > 0:
        limit = min(limit, int(hard_device_limit))
    return max(1, int(limit))


def prepare_contacts_snapshot(
    contacts: list,
    *,
    contact_to_dict: Callable[[object], dict],
    persist_contacts_cache: Callable[[list[dict]], None],
    enrich_contacts_with_local_state: Callable[[list[dict]], list[dict]],
) -> list[dict]:
    contacts_dict = [contact_to_dict(contact) for contact in contacts]
    persist_contacts_cache(contacts_dict)
    return enrich_contacts_with_local_state(contacts_dict)


def compose_contacts_snapshot(
    live_contacts: list[dict] | None = None,
    *,
    list_cached_contacts: Callable[[], list[dict]],
) -> list[dict]:
    cached_contacts = list_cached_contacts()
    if not cached_contacts and not live_contacts:
        return []
    if not cached_contacts:
        live_keys = {
            str((contact or {}).get("public_key") or "").strip().lower()
            for contact in list(live_contacts or [])
            if len(str((contact or {}).get("public_key") or "").strip()) == 64
        }
        return [
            {
                **dict(contact),
                "is_on_node": str(contact.get("public_key") or "").strip().lower() in live_keys,
            }
            for contact in list(live_contacts or [])
        ]
    live_map = {
        str((contact or {}).get("public_key") or "").strip().lower(): dict(contact)
        for contact in list(live_contacts or [])
        if len(str((contact or {}).get("public_key") or "").strip()) == 64
    }
    merged: list[dict] = []
    merged_keys: set[str] = set()
    for cached in cached_contacts:
        public_key = str(cached.get("public_key") or "").strip().lower()
        live = live_map.get(public_key)
        item = dict(cached)
        if live is not None:
            item.update(live)
        item["is_on_node"] = live is not None
        merged.append(item)
        merged_keys.add(public_key)
    for public_key, live in live_map.items():
        if public_key in merged_keys:
            continue
        item = dict(live)
        item["is_on_node"] = True
        merged.append(item)
    return merged


def evict_contacts_from_node(
    client,
    live_contacts: list[dict],
    *,
    max_contacts: int,
    reserve_non_favorite_slots: int = 0,
    preserve_public_keys: set[str] | None,
    expired_only: bool,
    now_epoch: int,
    get_cached_contact: Callable[[str], dict | None],
    contact_activity_epoch: Callable[[dict], int],
    contact_residency_timeout_secs: Callable[[dict], int],
    is_favorite_contact: Callable[[dict], bool],
    should_preserve_contact: Callable[[dict], bool],
    mark_cached_contacts_removed_from_node: Callable[[list[str]], None],
    prepare_contacts_snapshot: Callable[[list], list[dict]],
) -> list[dict]:
    preserve = {str(public_key or "").strip().lower() for public_key in (preserve_public_keys or set())}
    current_non_favorite_count = non_favorite_contact_count(live_contacts)
    candidates: list[tuple[tuple[int, int, int, str], dict]] = []
    for live in live_contacts:
        public_key = str(live.get("public_key") or "").strip().lower()
        if len(public_key) != 64 or public_key in preserve:
            continue
        cached = get_cached_contact(public_key) or dict(live)
        if not expired_only and is_favorite_contact(cached):
            continue
        if should_preserve_contact(cached):
            continue
        activity_epoch = contact_activity_epoch(cached)
        timeout_secs = contact_residency_timeout_secs(cached)
        is_expired = activity_epoch > 0 and now_epoch - activity_epoch >= timeout_secs
        if expired_only and not is_expired:
            continue
        sort_key = (
            0 if is_expired else 1,
            1 if is_favorite_contact(cached) else 0,
            activity_epoch,
            public_key,
        )
        candidates.append((sort_key, cached))
    if not candidates:
        return live_contacts
    candidates.sort(key=lambda item: item[0])
    target_non_favorite_count = max(0, int(max_contacts) - max(0, int(reserve_non_favorite_slots)))
    removed_public_keys: list[str] = []
    removed_non_favorite_count = 0
    for _sort_key, candidate in candidates:
        if not expired_only and current_non_favorite_count - removed_non_favorite_count <= target_non_favorite_count:
            break
        public_key = str(candidate.get("public_key") or "").strip().lower()
        try:
            client.remove_contact(bytes.fromhex(public_key))
            removed_public_keys.append(public_key)
            if not is_favorite_contact(candidate):
                removed_non_favorite_count += 1
        except MeshCoreError:
            continue
    if not removed_public_keys and not expired_only:
        raise MeshCoreError("unable to free a contact slot on the node")
    if removed_public_keys:
        mark_cached_contacts_removed_from_node(removed_public_keys)
        _cursor, contacts = client.get_contacts(None)
        return prepare_contacts_snapshot(contacts)
    return live_contacts


def ensure_contact_on_node(
    client,
    public_key: str,
    *,
    max_contacts: int,
    live_contacts: list[dict] | None,
    get_cached_contact: Callable[[str], dict | None],
    prepare_contacts_snapshot: Callable[[list], list[dict]],
    evict_contacts_from_node: Callable[..., list[dict]],
    cached_contact_to_model: Callable[[dict], object],
    is_favorite_contact: Callable[[dict], bool],
    touch_cached_contact: Callable[[str], None],
    materialize_cached_contact: Callable[[str], None],
    full_table_behavior: str,
) -> list[dict]:
    target_public_key = str(public_key or "").strip().lower()
    if len(target_public_key) != 64:
        raise MeshCoreError("public_key must be a 64-char hex string")
    current_contacts = list(live_contacts or [])
    if not current_contacts:
        _cursor, contacts = client.get_contacts(None)
        current_contacts = prepare_contacts_snapshot(contacts)
    if any(str(contact.get("public_key") or "").strip().lower() == target_public_key for contact in current_contacts):
        touch_cached_contact(target_public_key)
        return current_contacts
    cached_contact = get_cached_contact(target_public_key)
    if cached_contact is None:
        raise MeshCoreError(f"cached contact not found: {target_public_key[:12]}")
    target_is_favorite = is_favorite_contact(cached_contact)
    projected_non_favorite_count = non_favorite_contact_count(current_contacts) + (0 if target_is_favorite else 1)
    if projected_non_favorite_count > int(max_contacts):
        if str(full_table_behavior or "").strip().lower() == "reject_new":
            raise MeshCoreError("node contact table is full and residency policy forbids eviction")
        current_contacts = evict_contacts_from_node(
            client,
            current_contacts,
            max_contacts=max_contacts,
            reserve_non_favorite_slots=0 if target_is_favorite else 1,
            preserve_public_keys={target_public_key},
            expired_only=False,
        )
    client.update_contact(cached_contact_to_model(cached_contact))
    materialize_cached_contact(target_public_key)
    _cursor, contacts = client.get_contacts(None)
    return prepare_contacts_snapshot(contacts)


def find_contact_by_public_key(client, public_key_hex: str):
    _cursor, contacts = client.get_contacts(None)
    target = str(public_key_hex or "").strip().lower()
    for contact in contacts:
        if format_hex(contact.public_key).lower() == target:
            return contact
    raise MeshCoreError(f"contact not found: {target[:12]}")


def is_contact_on_node(client, public_key_hex: str) -> bool:
    target = str(public_key_hex or "").strip().lower()
    _cursor, contacts = client.get_contacts(None)
    return any(format_hex(contact.public_key).lower() == target for contact in contacts)


def export_contact_uri(advert_packet: bytes) -> str:
    if not advert_packet:
        raise MeshCoreError("empty advert packet")
    return f"meshcore://{advert_packet.hex()}"


def export_self_contact_uri(
    session_kwargs: dict,
    *,
    serial_port_access,
    client_factory,
) -> str:
    with serial_port_access(session_kwargs["port"]):
        with client_factory(
            port=session_kwargs["port"],
            baudrate=session_kwargs["baudrate"],
            timeout=session_kwargs["timeout"],
        ) as client:
            client.query_device(session_kwargs["protocol_version"])
            client.app_start(session_kwargs["app_name"], session_kwargs["app_version"])
            return export_contact_uri(client.export_contact(None))


def export_self_contact_uri_with_client(
    client,
    *,
    export_contact_uri,
) -> str:
    return export_contact_uri(client.export_contact(None))


def refresh_contacts_with_client(
    client,
    *,
    since: int | None,
    prepare_contacts_snapshot,
    compose_contacts_snapshot,
) -> dict:
    cursor, contacts = client.get_contacts(since)
    live_contacts = prepare_contacts_snapshot(contacts)
    return {
        "next_since": cursor,
        "live_contacts": live_contacts,
        "contacts": compose_contacts_snapshot(live_contacts),
    }


def perform_contact_action_with_client(
    client,
    *,
    public_key: str | None,
    action: str,
    favorite: bool | None,
    import_uri: str | None,
    route_path_len: int | None,
    route_path_hash_len: int | None,
    route_path_hex: str | None,
    hard_device_limit: int | None,
    ensure_contact_on_node,
    touch_cached_contact,
    set_cached_contact_route,
    get_cached_contact,
    cached_contact_to_model,
    mark_cached_contacts_removed_from_node,
    delete_cached_contact,
    find_contact_by_public_key,
    export_contact_uri,
    prepare_contacts_snapshot,
    compose_contacts_snapshot,
) -> dict:
    target_public_key = str(public_key or "").strip().lower()
    current_contacts_dict: list[dict] | None = None

    def _load_live_contacts() -> list[dict]:
        nonlocal current_contacts_dict
        _cursor, current_contacts = client.get_contacts(None)
        current_contacts_dict = prepare_contacts_snapshot(current_contacts)
        return list(current_contacts_dict or [])

    def _effective_limit_for_contacts(
        contacts_dict: list[dict],
        *,
        reserve_favorite_slots: int = 0,
    ) -> int:
        return effective_node_contact_limit(
            contacts_dict,
            reserve_favorite_slots=reserve_favorite_slots,
            hard_device_limit=hard_device_limit,
        )

    result: dict[str, object] = {"ok": True}
    if action == "import":
        uri = str(import_uri or "").strip()
        if not uri.startswith("meshcore://"):
            raise ValueError("meshcore:// URI is required")
        advert_packet = bytes.fromhex(uri[len("meshcore://"):])
        client.import_contact(advert_packet)
        result["imported"] = True
    else:
        if len(target_public_key) != 64:
            raise ValueError("public_key must be a 64-char hex string")
        public_key_bytes = bytes.fromhex(target_public_key)
        if action == "share":
            was_on_node = is_contact_on_node(client, target_public_key)
            current_contacts_dict = _load_live_contacts()
            ensure_contact_on_node(
                client,
                target_public_key,
                max_contacts=_effective_limit_for_contacts(current_contacts_dict),
                live_contacts=current_contacts_dict,
            )
            client.share_contact(public_key_bytes)
            touch_cached_contact(target_public_key)
            result["shared"] = True
            result["materialized_on_node"] = not was_on_node
        elif action == "export":
            was_on_node = is_contact_on_node(client, target_public_key)
            current_contacts_dict = _load_live_contacts()
            ensure_contact_on_node(
                client,
                target_public_key,
                max_contacts=_effective_limit_for_contacts(current_contacts_dict),
                live_contacts=current_contacts_dict,
            )
            result["uri"] = export_contact_uri(client.export_contact(public_key_bytes))
            touch_cached_contact(target_public_key)
            result["materialized_on_node"] = not was_on_node
        elif action == "export-self":
            result["uri"] = export_contact_uri(client.export_contact(None))
        elif action == "reset-path":
            was_on_node = is_contact_on_node(client, target_public_key)
            current_contacts_dict = _load_live_contacts()
            ensure_contact_on_node(
                client,
                target_public_key,
                max_contacts=_effective_limit_for_contacts(current_contacts_dict),
                live_contacts=current_contacts_dict,
            )
            client.reset_contact_path(public_key_bytes)
            touch_cached_contact(target_public_key)
            result["path_reset"] = True
            result["materialized_on_node"] = not was_on_node
        elif action == "set-path":
            was_on_node = is_contact_on_node(client, target_public_key)
            current_contacts_dict = _load_live_contacts()
            path_len = int(route_path_len or 0)
            hash_len = int(route_path_hash_len or 0)
            path_hex = str(route_path_hex or "").strip().lower()
            if path_len <= 0:
                raise MeshCoreError("contact static route must contain at least one hop")
            if hash_len < 1 or hash_len > 4:
                raise MeshCoreError("contact static route hash size must be between 1 and 4 bytes")
            if len(path_hex) != path_len * hash_len * 2:
                raise MeshCoreError("contact static route hex length does not match hop count and hash size")
            set_cached_contact_route(
                target_public_key,
                out_path_len=path_len,
                out_path_hash_len=hash_len,
                out_path=path_hex,
            )
            if was_on_node:
                client.remove_contact(public_key_bytes)
                cached_contact = get_cached_contact(target_public_key)
                if cached_contact is None:
                    raise MeshCoreError(f"cached contact not found: {target_public_key[:12]}")
                client.update_contact(cached_contact_to_model(cached_contact))
                touch_cached_contact(target_public_key)
                result["materialized_on_node"] = False
            else:
                ensure_contact_on_node(
                    client,
                    target_public_key,
                    max_contacts=_effective_limit_for_contacts(current_contacts_dict),
                    live_contacts=current_contacts_dict,
                )
                result["materialized_on_node"] = True
            result["path_saved"] = True
        elif action == "delete":
            client.remove_contact(public_key_bytes)
            mark_cached_contacts_removed_from_node([target_public_key])
            result["deleted"] = True
            result["deleted_layer"] = "node"
        elif action == "delete-backend":
            removed_from_node = False
            try:
                find_contact_by_public_key(client, target_public_key)
            except MeshCoreError:
                pass
            else:
                client.remove_contact(public_key_bytes)
                mark_cached_contacts_removed_from_node([target_public_key])
                removed_from_node = True
            deleted_from_backend = bool(delete_cached_contact(target_public_key))
            result["deleted"] = deleted_from_backend or removed_from_node
            result["deleted_layer"] = "backend"
            result["deleted_from_backend"] = deleted_from_backend
            result["removed_from_node"] = removed_from_node
        elif action == "favorite":
            was_on_node = is_contact_on_node(client, target_public_key)
            current_contacts_dict = _load_live_contacts()
            current_contact = next(
                (
                    contact
                    for contact in current_contacts_dict
                    if str(contact.get("public_key") or "").strip().lower() == target_public_key
                ),
                None,
            )
            reserve_favorite_slots = 1 if bool(favorite) and not bool(int((current_contact or {}).get("flags", 0)) & CONTACT_FLAG_STAR) else 0
            ensure_contact_on_node(
                client,
                target_public_key,
                max_contacts=_effective_limit_for_contacts(
                    current_contacts_dict,
                    reserve_favorite_slots=reserve_favorite_slots,
                ),
                live_contacts=current_contacts_dict,
            )
            contact = find_contact_by_public_key(client, target_public_key)
            next_flags = int(contact.flags)
            if bool(favorite):
                next_flags |= CONTACT_FLAG_STAR
            else:
                next_flags &= ~CONTACT_FLAG_STAR
            client.update_contact(contact, flags=next_flags)
            touch_cached_contact(target_public_key)
            result["favorite"] = bool(favorite)
            result["flags"] = next_flags
            result["materialized_on_node"] = not was_on_node
        else:
            raise MeshCoreError(f"unsupported contact action: {action}")

    refreshed = refresh_contacts_with_client(
        client,
        since=None,
        prepare_contacts_snapshot=prepare_contacts_snapshot,
        compose_contacts_snapshot=compose_contacts_snapshot,
    )
    result["contacts"] = refreshed["contacts"]
    result["live_contacts"] = refreshed["live_contacts"]
    return result


def send_contact_text(
    session_kwargs: dict,
    *,
    public_key: str,
    text: str,
    sender_timestamp: int,
    serial_port_access,
    client_factory,
    ensure_contact_on_node,
    touch_cached_contact,
):
    target_public_key = str(public_key or "").strip().lower()
    with serial_port_access(session_kwargs["port"]):
        with client_factory(
            port=session_kwargs["port"],
            baudrate=session_kwargs["baudrate"],
            timeout=session_kwargs["timeout"],
        ) as client:
            device = client.query_device(session_kwargs["protocol_version"])
            client.app_start(session_kwargs["app_name"], session_kwargs["app_version"])
            was_on_node = is_contact_on_node(client, target_public_key)
            _cursor, current_contacts = client.get_contacts(None)
            current_contacts_dict = prepare_contacts_snapshot(current_contacts)
            ensure_contact_on_node(
                client,
                target_public_key,
                max_contacts=effective_node_contact_limit(
                    current_contacts_dict,
                    hard_device_limit=int(device.max_contacts_div_2 * 2),
                ),
                live_contacts=current_contacts_dict,
            )
            sent = client.send_contact_text_message(
                bytes.fromhex(target_public_key),
                str(text),
                timestamp=int(sender_timestamp),
            )
            touch_cached_contact(target_public_key)
            return {"sent": sent, "materialized_on_node": not was_on_node}


def send_contact_text_with_client(
    client,
    *,
    public_key: str,
    text: str,
    sender_timestamp: int,
    max_contacts: int,
    live_contacts: list[dict] | None,
    ensure_contact_on_node,
    touch_cached_contact,
) -> tuple[object, list[dict], bool]:
    target_public_key = str(public_key or "").strip().lower()
    was_on_node = any(
        str(contact.get("public_key") or "").strip().lower() == target_public_key
        for contact in list(live_contacts or [])
    )
    current_contacts = ensure_contact_on_node(
        client,
        target_public_key,
        max_contacts=int(max_contacts),
        live_contacts=list(live_contacts or []),
    )
    sent = client.send_contact_text_message(
        bytes.fromhex(target_public_key),
        str(text),
        timestamp=int(sender_timestamp),
    )
    touch_cached_contact(target_public_key)
    return sent, current_contacts, (not was_on_node)


def reload_contacts_snapshot(
    session_kwargs: dict,
    *,
    serial_port_access,
    client_factory,
    prepare_contacts_snapshot,
    compose_contacts_snapshot,
) -> list[dict]:
    with serial_port_access(session_kwargs["port"]):
        with client_factory(
            port=session_kwargs["port"],
            baudrate=session_kwargs["baudrate"],
            timeout=session_kwargs["timeout"],
        ) as client:
            client.query_device(session_kwargs["protocol_version"])
            client.app_start(session_kwargs["app_name"], session_kwargs["app_version"])
            refreshed = refresh_contacts_with_client(
                client,
                since=None,
                prepare_contacts_snapshot=prepare_contacts_snapshot,
                compose_contacts_snapshot=compose_contacts_snapshot,
            )
    return list(refreshed["live_contacts"] or [])


def sync_favorites_group_with_client(
    client,
    desired_members: set[str],
    *,
    contact_flag_star: int,
    prepare_contacts_snapshot,
) -> tuple[int, list[str], list[dict]]:
    changed = 0
    updated_keys: list[str] = []
    _cursor, contacts = client.get_contacts(None)
    for contact in contacts:
        public_key_hex = format_hex(contact.public_key).lower()
        is_favorite = bool(int(contact.flags) & int(contact_flag_star))
        should_be_favorite = public_key_hex in desired_members
        if is_favorite == should_be_favorite:
            continue
        next_flags = int(contact.flags)
        if should_be_favorite:
            next_flags |= int(contact_flag_star)
        else:
            next_flags &= ~int(contact_flag_star)
        client.update_contact(contact, flags=next_flags)
        changed += 1
        updated_keys.append(public_key_hex)
    if changed > 0:
        _cursor, contacts = client.get_contacts(None)
    live_contacts = prepare_contacts_snapshot(contacts)
    return changed, updated_keys, live_contacts


def sync_favorites_group(
    session_kwargs: dict,
    members: list[str],
    *,
    serial_port_access,
    client_factory,
    contact_flag_star: int,
    prepare_contacts_snapshot,
    compose_contacts_snapshot,
) -> dict:
    desired_members = {
        str(public_key or "").strip().lower()
        for public_key in (members or [])
        if len(str(public_key or "").strip()) == 64
    }
    with serial_port_access(session_kwargs["port"]):
        with client_factory(
            port=session_kwargs["port"],
            baudrate=session_kwargs["baudrate"],
            timeout=session_kwargs["timeout"],
        ) as client:
            client.query_device(session_kwargs["protocol_version"])
            client.app_start(session_kwargs["app_name"], session_kwargs["app_version"])
            changed, updated_keys, live_contacts = sync_favorites_group_with_client(
                client,
                desired_members,
                contact_flag_star=contact_flag_star,
                prepare_contacts_snapshot=prepare_contacts_snapshot,
            )
    return {
        "ok": True,
        "changed": changed,
        "updated_public_keys": updated_keys,
        "contacts": compose_contacts_snapshot(live_contacts),
        "live_contacts": live_contacts,
    }


def perform_contact_action(
    session_kwargs: dict,
    *,
    public_key: str | None,
    action: str,
    favorite: bool | None,
    import_uri: str | None,
    route_path_len: int | None,
    route_path_hash_len: int | None,
    route_path_hex: str | None,
    serial_port_access,
    client_factory,
    ensure_contact_on_node,
    touch_cached_contact,
    set_cached_contact_route,
    get_cached_contact,
    cached_contact_to_model,
    mark_cached_contacts_removed_from_node,
    delete_cached_contact,
    find_contact_by_public_key,
    export_contact_uri,
    reload_contacts_snapshot,
    compose_contacts_snapshot,
    prepare_contacts_snapshot,
) -> dict:
    with serial_port_access(session_kwargs["port"]):
        with client_factory(
            port=session_kwargs["port"],
            baudrate=session_kwargs["baudrate"],
            timeout=session_kwargs["timeout"],
        ) as client:
            device = client.query_device(session_kwargs["protocol_version"])
            client.app_start(session_kwargs["app_name"], session_kwargs["app_version"])
            result = perform_contact_action_with_client(
                client,
                public_key=public_key,
                action=action,
                favorite=favorite,
                import_uri=import_uri,
                route_path_len=route_path_len,
                route_path_hash_len=route_path_hash_len,
                route_path_hex=route_path_hex,
                hard_device_limit=int(device.max_contacts_div_2 * 2),
                ensure_contact_on_node=ensure_contact_on_node,
                touch_cached_contact=touch_cached_contact,
                set_cached_contact_route=set_cached_contact_route,
                get_cached_contact=get_cached_contact,
                cached_contact_to_model=cached_contact_to_model,
                mark_cached_contacts_removed_from_node=mark_cached_contacts_removed_from_node,
                delete_cached_contact=delete_cached_contact,
                find_contact_by_public_key=find_contact_by_public_key,
                export_contact_uri=export_contact_uri,
                prepare_contacts_snapshot=prepare_contacts_snapshot,
                compose_contacts_snapshot=compose_contacts_snapshot,
            )
    live_contacts = reload_contacts_snapshot(session_kwargs)
    result["contacts"] = compose_contacts_snapshot(live_contacts)
    result["live_contacts"] = live_contacts
    return result
