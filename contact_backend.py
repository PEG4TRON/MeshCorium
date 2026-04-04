"""Hybrid contacts facade.

The project uses a two-layer contact model:

- The companion/node contact table is a transient active working set that may be
  rebuilt, materialized, or evicted at runtime.
- SQLite ``contacts_cache`` is the local persistent mirror/store and the source
  of truth for the full backend-owned contact universe.

This facade exposes the stable backend API used by the web layer. Callers should
prefer these helpers over reaching into contact_store/contact_service details or
assuming that the current node-resident contact list is the full contact set.
"""

from __future__ import annotations

import threading
import dataclasses
from collections.abc import Callable
from dataclasses import dataclass

import contact_service
import contact_store
import contact_admin
import contact_groups
from contact_store import ADVERT_TYPE_REPEATER
from meshcorium_client import Contact, format_hex, format_latlon

CONTACT_MODEL_MIRRORED_FIELDS = (
    "public_key",
    "adv_type",
    "flags",
    "path_len_byte",
    "out_path_len",
    "out_path_hash_len",
    "out_path",
    "adv_name",
    "last_advert",
    "adv_lat",
    "adv_lon",
    "lastmod",
    "raw_payload_hex",
)

CONTACT_MODEL_FIELDS = tuple(field.name for field in dataclasses.fields(Contact))

if tuple(CONTACT_MODEL_FIELDS) != tuple(CONTACT_MODEL_MIRRORED_FIELDS):
    raise RuntimeError(
        "Contact companion field mapping is out of sync with meshcorium_client.Contact; "
        "update structured contact persistence before using the new fields"
    )


@dataclass(slots=True)
class ContactBackend:
    db_lock: threading.Lock
    db_path: str
    utc_now_epoch: Callable[[], int]
    get_contact_timeout_secs: Callable[[], int]
    get_repeater_timeout_secs: Callable[[], int]
    get_preserve_favorites_on_node: Callable[[], bool]
    get_preserve_repeaters_on_node: Callable[[], bool]
    get_full_table_behavior: Callable[[], str]
    contact_flag_star: int
    system_favorites_group: str
    get_contact_message_stats: Callable[[], dict]
    log_event: Callable[..., None] | None = None

    def is_favorite_contact(self, contact: dict) -> bool:
        return bool(int(contact.get("flags", 0)) & int(self.contact_flag_star))

    def is_local_self_contact(self, contact: dict | None) -> bool:
        if not isinstance(contact, dict):
            return False
        return bool(contact.get("is_local_self") or (contact.get("backend") or {}).get("is_local_self"))

    def has_local_direct_history(self, contact: dict | None) -> bool:
        if not isinstance(contact, dict):
            return False
        backend = contact.get("backend") or {}
        return int(contact.get("last_message_at") or backend.get("last_message_at") or 0) > 0

    def _emit_event(self, event: str, **fields) -> None:
        if self.log_event is None:
            return
        self.log_event(event, **fields)

    def should_preserve_contact(self, contact: dict) -> bool:
        if self.is_local_self_contact(contact):
            return False
        if self.get_preserve_favorites_on_node() and self.is_favorite_contact(contact):
            return True
        if self.has_local_direct_history(contact):
            return True
        if self.get_preserve_repeaters_on_node() and int(contact.get("adv_type") or 0) == ADVERT_TYPE_REPEATER:
            return True
        return False

    def _companion_payload(self, contact: dict) -> dict:
        existing = contact.get("companion")
        if isinstance(existing, dict):
            payload = dict(existing)
        else:
            payload = {}
        for field in CONTACT_MODEL_MIRRORED_FIELDS:
            if field in contact:
                payload[field] = contact.get(field)
        return payload

    def _backend_payload(self, contact: dict) -> dict:
        existing = contact.get("backend")
        if isinstance(existing, dict):
            payload = dict(existing)
        else:
            payload = {}
        payload["cache_updated_at"] = int(contact.get("updated_at") or payload.get("cache_updated_at") or 0)
        payload["last_interaction_at"] = int(contact.get("last_interaction_at") or payload.get("last_interaction_at") or 0)
        payload["last_public_traffic_at"] = int(contact.get("last_public_traffic_at") or payload.get("last_public_traffic_at") or 0)
        payload["last_public_advert_at"] = int(contact.get("last_public_advert_at") or payload.get("last_public_advert_at") or 0)
        payload["last_public_advert_mode"] = str(contact.get("last_public_advert_mode") or payload.get("last_public_advert_mode") or "")
        payload["last_materialized_at"] = int(contact.get("last_materialized_at") or payload.get("last_materialized_at") or 0)
        payload["last_removed_from_node_at"] = int(
            contact.get("last_removed_from_node_at") or payload.get("last_removed_from_node_at") or 0
        )
        payload["repeater_auth_saved"] = bool(contact.get("repeater_auth_saved", payload.get("repeater_auth_saved", False)))
        payload["repeater_auth_saved_at"] = int(
            contact.get("repeater_auth_saved_at") or payload.get("repeater_auth_saved_at") or 0
        )
        payload["is_on_node"] = bool(contact.get("is_on_node", payload.get("is_on_node", False)))
        payload["is_local_self"] = bool(contact.get("is_local_self", payload.get("is_local_self", False)))
        return payload

    def _layer_contact_record(self, contact: dict) -> dict:
        layered = dict(contact)
        layered["companion"] = self._companion_payload(contact)
        layered["backend"] = self._backend_payload(contact)
        return layered

    def contact_to_dict(self, contact: Contact) -> dict:
        lat = format_latlon(contact.adv_lat)
        lon = format_latlon(contact.adv_lon)
        return {
            "public_key": format_hex(contact.public_key),
            "adv_type": contact.adv_type,
            "flags": contact.flags,
            "path_len_byte": contact.path_len_byte,
            "out_path_len": contact.out_path_len,
            "out_path_hash_len": contact.out_path_hash_len,
            "out_path": format_hex(contact.out_path),
            "adv_name": contact.adv_name,
            "last_advert": contact.last_advert,
            "adv_lat_raw": int(contact.adv_lat),
            "adv_lon_raw": int(contact.adv_lon),
            "lat": lat,
            "lon": lon,
            "has_location": bool(contact.adv_lat or contact.adv_lon),
            "lastmod": contact.lastmod,
            "raw_payload_hex": str(contact.raw_payload_hex or ""),
        }

    def enrich_contacts_with_local_state(self, contacts: list[dict]) -> list[dict]:
        stats = self.get_contact_message_stats()
        groups = contact_groups.list_contact_groups(
            self.db_lock,
            self.db_path,
            reserved_group_name=self.system_favorites_group,
        )
        contact_groups_map: dict[str, list[str]] = {}
        for group_name, members in groups.items():
            for public_key in members:
                contact_groups_map.setdefault(public_key, []).append(group_name)
        enriched: list[dict] = []
        for item in contacts:
            contact = self._layer_contact_record(item)
            prefix = str(contact.get("public_key") or "").lower()[:12]
            public_key = str(contact.get("public_key") or "").lower()
            local = stats.get(prefix, {})
            contact["pubkey_prefix"] = prefix
            contact["unread_count"] = int(local.get("unread_count") or 0)
            contact["last_message_at"] = int(local.get("last_message_at") or 0)
            contact["last_message_text"] = str(local.get("last_message_text") or "")
            contact["last_message_from_self"] = bool(local.get("last_message_from_self", False))
            contact["is_favorite"] = self.is_favorite_contact(contact)
            group_tags = sorted(contact_groups_map.get(public_key, []))
            if contact["is_favorite"] and self.system_favorites_group not in group_tags:
                group_tags.append(self.system_favorites_group)
            contact["group_tags"] = sorted(group_tags, key=lambda value: value.lower())
            backend = dict(contact.get("backend") or {})
            backend["pubkey_prefix"] = prefix
            backend["unread_count"] = contact["unread_count"]
            backend["last_message_at"] = contact["last_message_at"]
            backend["last_message_text"] = contact["last_message_text"]
            backend["last_message_from_self"] = contact["last_message_from_self"]
            backend["is_favorite"] = contact["is_favorite"]
            backend["group_tags"] = list(contact["group_tags"])
            backend["repeater_auth_saved"] = bool(contact.get("repeater_auth_saved"))
            backend["repeater_auth_saved_at"] = int(contact.get("repeater_auth_saved_at") or 0)
            backend["is_on_node"] = bool(contact.get("is_on_node", backend.get("is_on_node", False)))
            backend["is_local_self"] = self.is_local_self_contact(contact)
            contact["backend"] = backend
            enriched.append(contact)
        return enriched

    def build_effective_groups(
        self,
        base_groups: dict[str, list[str]] | None,
        contacts: list[dict] | None,
    ) -> dict[str, list[str]]:
        effective: dict[str, list[str]] = {}
        for group_name, members in (base_groups or {}).items():
            normalized_group_name = str(group_name or "").strip()
            if not normalized_group_name or normalized_group_name.lower() == self.system_favorites_group.lower():
                continue
            effective[normalized_group_name] = sorted(
                {
                    str(public_key or "").strip().lower()
                    for public_key in list(members or [])
                    if len(str(public_key or "").strip()) == 64
                }
            )
        effective[self.system_favorites_group] = sorted(
            {
                str(contact.get("public_key") or "").strip().lower()
                for contact in list(contacts or [])
                if len(str(contact.get("public_key") or "").strip()) == 64 and self.is_favorite_contact(contact)
            }
        )
        return effective

    def build_contact_groups_payload(self, live_contacts: list[dict] | None = None) -> dict:
        return self.build_contact_groups_payload_for_scope("", live_contacts=live_contacts)

    def build_contact_groups_payload_for_scope(self, scope_key: str, live_contacts: list[dict] | None = None) -> dict:
        local_groups = contact_groups.list_contact_groups(
            self.db_lock,
            self.db_path,
            reserved_group_name=self.system_favorites_group,
            scope_key=scope_key,
        )
        contacts = self.compose_snapshot(live_contacts)
        return {
            "groups": local_groups,
            "effective_groups": self.build_effective_groups(local_groups, contacts),
            "scope": {
                "scope_key": str(scope_key or "").strip().lower(),
                "mode": "per-radio-with-legacy-fallback",
            },
            "semantics": {
                "local_groups_scope": "client-local-only",
                "storage_scope": "per-radio",
                "companion_flag_backed_groups": {
                    self.system_favorites_group: {
                        "flag_name": "CONTACT_FLAG_STAR",
                        "mode": "system-derived",
                    }
                },
                "rules": {
                    "local_groups_do_not_sync_to_companion_flags": True,
                    "only_system_groups_may_be_flag_backed": True,
                    "favorites_is_reserved": True,
                },
            },
        }

    def save_contact_group(self, group_name: str, members: list[str], *, scope_key: str = "") -> dict:
        local_groups = contact_groups.save_contact_group(
            self.db_lock,
            self.db_path,
            group_name=group_name,
            members=members,
            reserved_group_name=self.system_favorites_group,
            scope_key=scope_key,
        )
        return {
            "groups": local_groups,
            "effective_groups": self.build_effective_groups(local_groups, self.compose_snapshot()),
            "scope": {
                "scope_key": str(scope_key or "").strip().lower(),
                "mode": "per-radio-with-legacy-fallback",
            },
        }

    def delete_contact_group(self, group_name: str, *, scope_key: str = "") -> dict:
        local_groups = contact_groups.delete_contact_group(
            self.db_lock,
            self.db_path,
            group_name=group_name,
            reserved_group_name=self.system_favorites_group,
            scope_key=scope_key,
        )
        return {
            "groups": local_groups,
            "effective_groups": self.build_effective_groups(local_groups, self.compose_snapshot()),
            "scope": {
                "scope_key": str(scope_key or "").strip().lower(),
                "mode": "per-radio-with-legacy-fallback",
            },
        }

    def rename_contact_group(self, old_name: str, new_name: str, *, scope_key: str = "") -> dict:
        local_groups = contact_groups.rename_contact_group(
            self.db_lock,
            self.db_path,
            old_name=old_name,
            new_name=new_name,
            reserved_group_name=self.system_favorites_group,
            scope_key=scope_key,
        )
        return {
            "groups": local_groups,
            "effective_groups": self.build_effective_groups(local_groups, self.compose_snapshot()),
            "scope": {
                "scope_key": str(scope_key or "").strip().lower(),
                "mode": "per-radio-with-legacy-fallback",
            },
        }

    def delete_contact_local_overlay(self, public_key: str) -> None:
        contact_groups.delete_contact_local_overlay(
            self.db_lock,
            self.db_path,
            public_key=public_key,
        )

    def list_cached_contacts(self, limit: int | None = None) -> list[dict]:
        rows = contact_store.list_cached_contacts_raw(self.db_lock, self.db_path, limit)
        return self.enrich_contacts_with_local_state(rows)

    def get_cached_contact(self, public_key: str) -> dict | None:
        row = contact_store.get_cached_contact_raw(self.db_lock, self.db_path, public_key)
        if row is None:
            return None
        return self.enrich_contacts_with_local_state([row])[0]

    def mark_cached_contact_as_local_self(self, public_key: str) -> bool:
        updated = contact_store.mark_cached_contact_as_local_self(self.db_lock, self.db_path, public_key)
        if updated:
            self._emit_event("mark_cached_contact_as_local_self", public_key=str(public_key or "").strip().lower())
        return updated

    def get_cached_repeater_auth_password(self, public_key: str) -> str:
        return contact_store.get_cached_contact_repeater_auth_password(self.db_lock, self.db_path, public_key)

    def set_cached_repeater_auth_password(self, public_key: str, password: str) -> bool:
        updated = contact_store.set_cached_contact_repeater_auth_password(
            self.db_lock,
            self.db_path,
            public_key,
            str(password or ""),
            self.utc_now_epoch(),
        )
        if updated:
            self._emit_event("set_cached_repeater_auth_password", public_key=str(public_key or "").strip().lower())
        return updated

    def clear_cached_repeater_auth_password(self, public_key: str) -> bool:
        updated = contact_store.clear_cached_contact_repeater_auth_password(
            self.db_lock,
            self.db_path,
            public_key,
            self.utc_now_epoch(),
        )
        if updated:
            self._emit_event("clear_cached_repeater_auth_password", public_key=str(public_key or "").strip().lower())
        return updated

    def persist_contacts_cache(self, contacts: list[dict]) -> None:
        contact_store.persist_contacts_cache(self.db_lock, self.db_path, contacts, self.utc_now_epoch())

    def set_cached_contact_route(
        self,
        public_key: str,
        *,
        out_path_len: int,
        out_path_hash_len: int,
        out_path: str,
        interaction: bool = False,
    ) -> bool:
        return contact_store.set_cached_contact_route(
            self.db_lock,
            self.db_path,
            public_key,
            out_path_len=out_path_len,
            out_path_hash_len=out_path_hash_len,
            out_path=out_path,
            now_epoch=self.utc_now_epoch(),
            interaction=interaction,
        )

    def get_cache_metadata(self, *, stale_after_secs: int) -> dict:
        return contact_store.get_contact_cache_metadata(
            self.db_lock,
            self.db_path,
            now_epoch=self.utc_now_epoch(),
            stale_after_secs=stale_after_secs,
        )

    def build_cache_payload(
        self,
        *,
        stale_after_secs: int,
        limit: int | None = None,
        public_key: str | None = None,
    ) -> dict:
        payload = {"meta": self.get_cache_metadata(stale_after_secs=stale_after_secs)}
        target_public_key = str(public_key or "").strip().lower()
        if target_public_key:
            contact = self.get_cached_contact(target_public_key)
            if contact is None:
                raise ValueError("cached contact not found")
            payload["contact"] = contact
            return payload
        contacts = self.list_cached_contacts(limit)
        payload["contacts"] = contacts
        payload["count"] = len(contacts)
        return payload

    def prepare_snapshot(self, contacts: list[Contact]) -> list[dict]:
        return contact_service.prepare_contacts_snapshot(
            contacts,
            contact_to_dict=self.contact_to_dict,
            persist_contacts_cache=self.persist_contacts_cache,
            enrich_contacts_with_local_state=self.enrich_contacts_with_local_state,
        )

    def compose_snapshot(self, live_contacts: list[dict] | None = None) -> list[dict]:
        merged = contact_service.compose_contacts_snapshot(
            live_contacts,
            list_cached_contacts=lambda: self.list_cached_contacts(),
        )
        enriched = self.enrich_contacts_with_local_state(merged)
        return [contact for contact in enriched if not self.is_local_self_contact(contact)]

    def build_debug_payload(
        self,
        *,
        active_port: str | None,
        live_contacts: list[dict] | None,
        public_key: str | None,
        stale_after_secs: int,
        policy: dict,
        recent_events: list[dict] | None,
    ) -> dict:
        target_public_key = str(public_key or "").strip().lower()
        live_contacts_list = list(live_contacts or [])
        cached_contact = self.get_cached_contact(target_public_key) if len(target_public_key) == 64 else None
        cached_contacts = self.list_cached_contacts(500)
        live_public_keys = {
            str(contact.get("public_key") or "").strip().lower()
            for contact in live_contacts_list
            if len(str(contact.get("public_key") or "").strip()) == 64
        }
        live_contacts_summary = [
            {
                "public_key": str(contact.get("public_key") or "").strip().lower(),
                "adv_name": str(contact.get("adv_name") or ""),
                "adv_type": int(contact.get("adv_type") or 0),
                "is_favorite": bool(contact.get("is_favorite")),
                "last_materialized_at": int(contact.get("last_materialized_at") or 0),
                "last_interaction_at": int(contact.get("last_interaction_at") or 0),
            }
            for contact in live_contacts_list
        ]
        cached_only_count = sum(
            1
            for contact in cached_contacts
            if str(contact.get("public_key") or "").strip().lower() not in live_public_keys
        )
        return {
            "policy": dict(policy or {}),
            "summary": {
                "active_port": str(active_port or ""),
                "cached_contacts_total": len(cached_contacts),
                "live_contacts_total": len(live_contacts_list),
                "cached_only_contacts_total": cached_only_count,
            },
            "cache_meta": self.get_cache_metadata(stale_after_secs=stale_after_secs),
            "selected_public_key": target_public_key if len(target_public_key) == 64 else "",
            "selected_cached_contact": cached_contact,
            "live_contacts": live_contacts_summary,
            "recent_residency_events": list(recent_events or []),
        }

    def cached_contact_to_model(self, contact: dict) -> Contact:
        return contact_store.cached_contact_to_model(contact)

    def touch_cached_contact(self, public_key: str, *, interaction: bool = False, materialized: bool = False) -> None:
        target_public_key = str(public_key or "").strip().lower()
        contact_store.touch_cached_contact(
            self.db_lock,
            self.db_path,
            target_public_key,
            self.utc_now_epoch(),
            interaction=interaction,
            materialized=materialized,
        )
        if interaction or materialized:
            self._emit_event(
                "touch_cached_contact",
                public_key=target_public_key,
                interaction=bool(interaction),
                materialized=bool(materialized),
            )

    def touch_cached_contact_by_prefix(self, pubkey_prefix: str, *, interaction: bool = False) -> None:
        contact_store.touch_cached_contact_by_prefix(
            self.db_lock,
            self.db_path,
            pubkey_prefix,
            self.utc_now_epoch(),
            interaction=interaction,
        )

    def touch_cached_contact_packet_activity(self, public_key: str, *, advert_mode: str | None = None) -> bool:
        updated = contact_store.touch_cached_contact_packet_activity(
            self.db_lock,
            self.db_path,
            public_key,
            self.utc_now_epoch(),
            advert_mode=advert_mode,
        )
        if updated:
            self._emit_event(
                "touch_cached_contact_packet_activity",
                public_key=str(public_key or "").strip().lower(),
                advert_mode=str(advert_mode or "").strip().lower(),
            )
        return updated

    def touch_cached_contact_packet_activity_by_prefix(self, pubkey_prefix: str) -> bool:
        updated = contact_store.touch_cached_contact_packet_activity_by_prefix(
            self.db_lock,
            self.db_path,
            pubkey_prefix,
            self.utc_now_epoch(),
        )
        if updated:
            self._emit_event(
                "touch_cached_contact_packet_activity_by_prefix",
                pubkey_prefix=str(pubkey_prefix or "").strip().lower()[:12],
            )
        return updated

    def mark_cached_contacts_removed_from_node(self, public_keys: list[str]) -> None:
        contact_store.mark_cached_contacts_removed_from_node(
            self.db_lock,
            self.db_path,
            public_keys,
            self.utc_now_epoch(),
        )
        self._emit_event("mark_cached_contacts_removed_from_node", public_keys=list(public_keys))

    def delete_cached_contact(self, public_key: str) -> bool:
        deleted = contact_store.delete_cached_contact(self.db_lock, self.db_path, public_key)
        if deleted:
            self.delete_contact_local_overlay(str(public_key or "").strip().lower())
        self._emit_event("delete_cached_contact", public_key=str(public_key or "").strip().lower(), deleted=bool(deleted))
        return deleted

    def contact_residency_timeout_secs(self, contact: dict) -> int:
        return contact_store.contact_residency_timeout_secs(
            contact,
            contact_timeout_secs=self.get_contact_timeout_secs(),
            repeater_timeout_secs=self.get_repeater_timeout_secs(),
        )

    def contact_activity_epoch(self, contact: dict) -> int:
        return contact_store.contact_activity_epoch(contact)

    def evict_contacts_from_node(
        self,
        client,
        live_contacts: list[dict],
        *,
        max_contacts: int,
        reserve_non_favorite_slots: int = 0,
        preserve_public_keys: set[str] | None = None,
        expired_only: bool,
    ) -> list[dict]:
        before_keys = {
            str(contact.get("public_key") or "").strip().lower()
            for contact in list(live_contacts or [])
            if len(str(contact.get("public_key") or "").strip()) == 64
        }
        result = contact_service.evict_contacts_from_node(
            client,
            live_contacts,
            max_contacts=max_contacts,
            reserve_non_favorite_slots=reserve_non_favorite_slots,
            preserve_public_keys=preserve_public_keys,
            expired_only=expired_only,
            now_epoch=self.utc_now_epoch(),
            get_cached_contact=self.get_cached_contact,
            contact_activity_epoch=self.contact_activity_epoch,
            contact_residency_timeout_secs=self.contact_residency_timeout_secs,
            is_favorite_contact=self.is_favorite_contact,
            should_preserve_contact=self.should_preserve_contact,
            mark_cached_contacts_removed_from_node=self.mark_cached_contacts_removed_from_node,
            prepare_contacts_snapshot=self.prepare_snapshot,
        )
        after_keys = {
            str(contact.get("public_key") or "").strip().lower()
            for contact in list(result or [])
            if len(str(contact.get("public_key") or "").strip()) == 64
        }
        removed = sorted(before_keys - after_keys)
        self._emit_event(
            "evict_contacts_from_node",
            expired_only=bool(expired_only),
            max_contacts=int(max_contacts),
            reserve_non_favorite_slots=int(reserve_non_favorite_slots),
            non_favorite_before=sum(
                1
                for contact in list(live_contacts or [])
                if not self.is_favorite_contact(contact)
            ),
            non_favorite_after=sum(
                1
                for contact in list(result or [])
                if not self.is_favorite_contact(contact)
            ),
            before_count=len(before_keys),
            after_count=len(after_keys),
            removed_public_keys=removed,
            preserve_public_keys=sorted(str(public_key or "").strip().lower() for public_key in (preserve_public_keys or set())),
        )
        return result

    def ensure_contact_on_node(
        self,
        client,
        public_key: str,
        *,
        max_contacts: int,
        live_contacts: list[dict] | None = None,
    ) -> list[dict]:
        target_public_key = str(public_key or "").strip().lower()
        if self.is_local_self_contact(self.get_cached_contact(target_public_key)):
            raise MeshCoreError("self-contact is frozen and hidden from ordinary contact actions")
        before_on_node = any(
            str(contact.get("public_key") or "").strip().lower() == target_public_key
            for contact in list(live_contacts or [])
        )
        try:
            result = contact_service.ensure_contact_on_node(
                client,
                target_public_key,
                max_contacts=max_contacts,
                live_contacts=live_contacts,
                get_cached_contact=self.get_cached_contact,
                prepare_contacts_snapshot=self.prepare_snapshot,
                evict_contacts_from_node=self.evict_contacts_from_node,
                cached_contact_to_model=self.cached_contact_to_model,
                is_favorite_contact=self.is_favorite_contact,
                touch_cached_contact=lambda next_public_key: self.touch_cached_contact(next_public_key, interaction=True),
                materialize_cached_contact=lambda next_public_key: self.touch_cached_contact(
                    next_public_key,
                    interaction=True,
                    materialized=True,
                ),
                full_table_behavior=self.get_full_table_behavior(),
            )
        except Exception as exc:
            self._emit_event(
                "ensure_contact_on_node_error",
                public_key=target_public_key,
                max_contacts=int(max_contacts),
                full_table_behavior=self.get_full_table_behavior(),
                error=str(exc),
            )
            raise
        after_on_node = any(
            str(contact.get("public_key") or "").strip().lower() == target_public_key
            for contact in list(result or [])
        )
        self._emit_event(
            "ensure_contact_on_node",
            public_key=target_public_key,
            max_contacts=int(max_contacts),
            full_table_behavior=self.get_full_table_behavior(),
            on_node_before=bool(before_on_node),
            on_node_after=bool(after_on_node),
        )
        return result

    def rebuild_live_contacts_from_policy(
        self,
        client,
        *,
        max_contacts: int,
        live_contacts: list[dict] | None,
    ) -> list[dict]:
        current_contacts = list(live_contacts or [])
        now_epoch = self.utc_now_epoch()
        hidden_self_live_public_keys = sorted(
            {
                str(contact.get("public_key") or "").strip().lower()
                for contact in current_contacts
                if self.is_local_self_contact(self.get_cached_contact(str(contact.get("public_key") or "").strip().lower()))
            }
        )
        if hidden_self_live_public_keys:
            for public_key in hidden_self_live_public_keys:
                client.remove_contact(bytes.fromhex(public_key))
            self.mark_cached_contacts_removed_from_node(hidden_self_live_public_keys)
            _cursor, contacts = client.get_contacts(None)
            current_contacts = self.prepare_snapshot(contacts)
        live_public_keys = {
            str(contact.get("public_key") or "").strip().lower()
            for contact in current_contacts
            if len(str(contact.get("public_key") or "").strip()) == 64
        }
        candidates: list[tuple[tuple[int, int, str], str]] = []
        for contact in self.list_cached_contacts():
            public_key = str(contact.get("public_key") or "").strip().lower()
            if len(public_key) != 64 or public_key in live_public_keys:
                continue
            if self.is_local_self_contact(contact):
                continue
            preserve = self.should_preserve_contact(contact)
            last_removed_at = int(contact.get("last_removed_from_node_at") or 0)
            last_materialized_at = int(contact.get("last_materialized_at") or 0)
            # Respect an explicit node-removal decision until some later action
            # materializes the contact again on demand.
            if not preserve and last_removed_at and last_removed_at >= last_materialized_at:
                continue
            activity_epoch = self.contact_activity_epoch(contact)
            timeout_secs = self.contact_residency_timeout_secs(contact)
            is_active = activity_epoch > 0 and now_epoch - activity_epoch < timeout_secs
            if not preserve and not is_active:
                continue
            sort_key = (
                0 if preserve else 1,
                -int(activity_epoch),
                public_key,
            )
            candidates.append((sort_key, public_key))
        if not candidates:
            return current_contacts
        candidates.sort(key=lambda item: item[0])
        materialized_public_keys: list[str] = []
        for _sort_key, public_key in candidates:
            try:
                current_contacts = self.ensure_contact_on_node(
                    client,
                    public_key,
                    max_contacts=max_contacts,
                    live_contacts=current_contacts,
                )
            except Exception as exc:
                self._emit_event(
                    "rebuild_live_contacts_from_policy_error",
                    public_key=public_key,
                    max_contacts=int(max_contacts),
                    error=str(exc),
                )
                continue
            materialized_public_keys.append(public_key)
        self._emit_event(
            "rebuild_live_contacts_from_policy",
            max_contacts=int(max_contacts),
            initial_live_count=len(live_public_keys),
            final_live_count=len(
                {
                    str(contact.get("public_key") or "").strip().lower()
                    for contact in list(current_contacts or [])
                    if len(str(contact.get("public_key") or "").strip()) == 64
                }
            ),
            materialized_public_keys=materialized_public_keys,
            removed_hidden_self_public_keys=hidden_self_live_public_keys,
        )
        return current_contacts

    def dematerialize_new_live_contacts_from_node(
        self,
        client,
        *,
        live_contacts: list[dict] | None,
        previous_cached_contacts: dict[str, dict] | None = None,
    ) -> list[dict]:
        current_contacts = list(live_contacts or [])
        previous_cached = {
            str(public_key or "").strip().lower(): dict(contact)
            for public_key, contact in dict(previous_cached_contacts or {}).items()
            if len(str(public_key or "").strip()) == 64
        }
        candidate_public_keys: list[str] = []
        skipped_public_keys: list[str] = []
        for contact in current_contacts:
            public_key = str(contact.get("public_key") or "").strip().lower()
            if len(public_key) != 64:
                continue
            previous = previous_cached.get(public_key)
            was_previously_removed = bool(
                previous
                and int(previous.get("last_removed_from_node_at") or 0) > 0
                and int(previous.get("last_removed_from_node_at") or 0) >= int(previous.get("last_materialized_at") or 0)
            )
            if previous is not None and not was_previously_removed:
                continue
            cached_contact = self.get_cached_contact(public_key) or dict(contact)
            if self.should_preserve_contact(cached_contact):
                skipped_public_keys.append(public_key)
                continue
            candidate_public_keys.append(public_key)
        if not candidate_public_keys:
            return current_contacts
        removed_public_keys: list[str] = []
        for public_key in candidate_public_keys:
            try:
                client.remove_contact(bytes.fromhex(public_key))
                removed_public_keys.append(public_key)
            except Exception as exc:
                self._emit_event(
                    "dematerialize_new_live_contacts_from_node_error",
                    public_key=public_key,
                    error=str(exc),
                )
        if not removed_public_keys:
            return current_contacts
        self.mark_cached_contacts_removed_from_node(removed_public_keys)
        _cursor, contacts = client.get_contacts(None)
        refreshed_contacts = self.prepare_snapshot(contacts)
        self._emit_event(
            "dematerialize_new_live_contacts_from_node",
            before_count=len(
                {
                    str(contact.get("public_key") or "").strip().lower()
                    for contact in current_contacts
                    if len(str(contact.get("public_key") or "").strip()) == 64
                }
            ),
            after_count=len(
                {
                    str(contact.get("public_key") or "").strip().lower()
                    for contact in refreshed_contacts
                    if len(str(contact.get("public_key") or "").strip()) == 64
                }
            ),
            candidate_public_keys=sorted(candidate_public_keys),
            removed_public_keys=sorted(removed_public_keys),
            preserved_public_keys=sorted(skipped_public_keys),
        )
        return refreshed_contacts

    def reload_snapshot(self, session_kwargs: dict, *, serial_port_access, client_factory) -> list[dict]:
        return contact_service.reload_contacts_snapshot(
            session_kwargs,
            serial_port_access=serial_port_access,
            client_factory=client_factory,
            prepare_contacts_snapshot=self.prepare_snapshot,
            compose_contacts_snapshot=self.compose_snapshot,
        )

    def refresh_with_client(self, client, *, since: int | None = None) -> dict:
        previous_cached_contacts = {
            str(contact.get("public_key") or "").strip().lower(): contact
            for contact in self.list_cached_contacts()
            if len(str(contact.get("public_key") or "").strip()) == 64
        }
        refreshed = contact_service.refresh_contacts_with_client(
            client,
            since=since,
            prepare_contacts_snapshot=self.prepare_snapshot,
            compose_contacts_snapshot=self.compose_snapshot,
        )
        live_contacts = self.dematerialize_new_live_contacts_from_node(
            client,
            live_contacts=refreshed.get("live_contacts"),
            previous_cached_contacts=previous_cached_contacts,
        )
        live_contacts = self.rebuild_live_contacts_from_policy(
            client,
            max_contacts=contact_service.effective_node_contact_limit(live_contacts),
            live_contacts=live_contacts,
        )
        return {
            "next_since": refreshed.get("next_since"),
            **self.build_live_contacts_result(live_contacts),
        }

    def refresh_snapshot(
        self,
        session_kwargs: dict,
        *,
        since: int | None,
        serial_port_access,
        client_factory,
    ) -> dict:
        with serial_port_access(session_kwargs["port"]):
            with client_factory(
                port=session_kwargs["port"],
                baudrate=session_kwargs["baudrate"],
                timeout=session_kwargs["timeout"],
            ) as client:
                client.query_device(session_kwargs["protocol_version"])
                client.app_start(session_kwargs["app_name"], session_kwargs["app_version"])
                return self.refresh_with_client(client, since=since)

    def sync_favorites_group_with_client(
        self,
        client,
        desired_members: set[str],
    ) -> tuple[int, list[str], list[dict]]:
        return contact_service.sync_favorites_group_with_client(
            client,
            desired_members,
            contact_flag_star=self.contact_flag_star,
            prepare_contacts_snapshot=self.prepare_snapshot,
        )

    def sync_favorites_members_with_client(self, client, members: list[str]) -> dict:
        desired_members = {
            str(public_key or "").strip().lower()
            for public_key in list(members or [])
            if len(str(public_key or "").strip()) == 64
        }
        changed, updated_keys, contacts_dict = self.sync_favorites_group_with_client(
            client,
            desired_members,
        )
        return self.build_live_contacts_result(
            contacts_dict,
            changed=changed,
            updated_public_keys=updated_keys,
        )

    def build_live_contacts_result(self, live_contacts: list[dict], **extra_fields) -> dict:
        return {
            "contacts": self.compose_snapshot(live_contacts),
            "live_contacts": list(live_contacts or []),
            **extra_fields,
        }

    def sync_favorites_group(self, session_kwargs: dict, members: list[str], *, serial_port_access, client_factory) -> dict:
        return contact_service.sync_favorites_group(
            session_kwargs,
            members,
            serial_port_access=serial_port_access,
            client_factory=client_factory,
            contact_flag_star=self.contact_flag_star,
            prepare_contacts_snapshot=self.prepare_snapshot,
            compose_contacts_snapshot=self.compose_snapshot,
        )

    def remove_contacts_and_reload(
        self,
        session_kwargs: dict,
        *,
        mode: str,
        protect_favorites: bool,
        serial_port_access,
        client_factory,
    ) -> dict:
        live_contacts, summary = contact_admin.remove_contacts_and_reload(
            session_kwargs,
            mode=mode,
            protect_favorites=protect_favorites,
            serial_port_access=serial_port_access,
            client_factory=client_factory,
            is_favorite_contact=self.is_favorite_contact,
            get_contact_message_stats=self.get_contact_message_stats,
            contact_to_dict=self.contact_to_dict,
            mark_cached_contacts_removed_from_node=self.mark_cached_contacts_removed_from_node,
            prepare_contacts_snapshot=self.prepare_snapshot,
        )
        return self.build_live_contacts_result(live_contacts, **summary)

    def remove_contacts_with_client(
        self,
        client,
        *,
        mode: str,
        protect_favorites: bool,
        hard_device_limit: int,
    ) -> dict:
        live_contacts, summary = contact_admin.remove_contacts_with_client(
            client,
            mode=mode,
            protect_favorites=protect_favorites,
            hard_device_limit=hard_device_limit,
            is_favorite_contact=self.is_favorite_contact,
            get_contact_message_stats=self.get_contact_message_stats,
            contact_to_dict=self.contact_to_dict,
            mark_cached_contacts_removed_from_node=self.mark_cached_contacts_removed_from_node,
            prepare_contacts_snapshot=self.prepare_snapshot,
        )
        return self.build_live_contacts_result(live_contacts, **summary)

    def perform_action(
        self,
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
    ) -> dict:
        target_public_key = str(public_key or "").strip().lower()
        if len(target_public_key) == 64 and self.is_local_self_contact(self.get_cached_contact(target_public_key)):
            raise MeshCoreError("self-contact is frozen and hidden from ordinary contact actions")
        return contact_service.perform_contact_action(
            session_kwargs,
            public_key=public_key,
            action=action,
            favorite=favorite,
            import_uri=import_uri,
            route_path_len=route_path_len,
            route_path_hash_len=route_path_hash_len,
            route_path_hex=route_path_hex,
            serial_port_access=serial_port_access,
            client_factory=client_factory,
            ensure_contact_on_node=self.ensure_contact_on_node,
            touch_cached_contact=lambda target_public_key: self.touch_cached_contact(target_public_key, interaction=True),
            set_cached_contact_route=lambda target_public_key, **kwargs: self.set_cached_contact_route(
                target_public_key,
                interaction=True,
                **kwargs,
            ),
            get_cached_contact=self.get_cached_contact,
            cached_contact_to_model=self.cached_contact_to_model,
            mark_cached_contacts_removed_from_node=self.mark_cached_contacts_removed_from_node,
            delete_cached_contact=self.delete_cached_contact,
            find_contact_by_public_key=contact_service.find_contact_by_public_key,
            export_contact_uri=contact_service.export_contact_uri,
            reload_contacts_snapshot=lambda next_session_kwargs: self.reload_snapshot(
                next_session_kwargs,
                serial_port_access=serial_port_access,
                client_factory=client_factory,
            ),
            compose_contacts_snapshot=self.compose_snapshot,
            prepare_contacts_snapshot=self.prepare_snapshot,
        )

    def export_self_contact_uri(self, session_kwargs: dict, *, serial_port_access, client_factory) -> str:
        return contact_service.export_self_contact_uri(
            session_kwargs,
            serial_port_access=serial_port_access,
            client_factory=client_factory,
        )

    def export_self_contact_uri_with_client(self, client) -> str:
        return contact_service.export_self_contact_uri_with_client(
            client,
            export_contact_uri=contact_service.export_contact_uri,
        )

    def perform_action_with_client(
        self,
        client,
        *,
        public_key: str | None,
        action: str,
        favorite: bool | None,
        import_uri: str | None,
        route_path_len: int | None,
        route_path_hash_len: int | None,
        route_path_hex: str | None,
        hard_device_limit: int,
    ) -> dict:
        target_public_key = str(public_key or "").strip().lower()
        if len(target_public_key) == 64 and self.is_local_self_contact(self.get_cached_contact(target_public_key)):
            raise MeshCoreError("self-contact is frozen and hidden from ordinary contact actions")
        return contact_service.perform_contact_action_with_client(
            client,
            public_key=public_key,
            action=action,
            favorite=favorite,
            import_uri=import_uri,
            route_path_len=route_path_len,
            route_path_hash_len=route_path_hash_len,
            route_path_hex=route_path_hex,
            hard_device_limit=hard_device_limit,
            ensure_contact_on_node=self.ensure_contact_on_node,
            touch_cached_contact=lambda target_public_key: self.touch_cached_contact(target_public_key, interaction=True),
            set_cached_contact_route=lambda target_public_key, **kwargs: self.set_cached_contact_route(
                target_public_key,
                interaction=True,
                **kwargs,
            ),
            get_cached_contact=self.get_cached_contact,
            cached_contact_to_model=self.cached_contact_to_model,
            mark_cached_contacts_removed_from_node=self.mark_cached_contacts_removed_from_node,
            delete_cached_contact=self.delete_cached_contact,
            find_contact_by_public_key=contact_service.find_contact_by_public_key,
            export_contact_uri=contact_service.export_contact_uri,
            prepare_contacts_snapshot=self.prepare_snapshot,
            compose_contacts_snapshot=self.compose_snapshot,
        )

    def send_contact_text(
        self,
        session_kwargs: dict,
        *,
        public_key: str,
        text: str,
        sender_timestamp: int,
        serial_port_access,
        client_factory,
    ):
        if self.is_local_self_contact(self.get_cached_contact(public_key)):
            raise MeshCoreError("self-contact is frozen and hidden from direct messaging")
        return contact_service.send_contact_text(
            session_kwargs,
            public_key=public_key,
            text=text,
            sender_timestamp=sender_timestamp,
            serial_port_access=serial_port_access,
            client_factory=client_factory,
            ensure_contact_on_node=lambda client, next_public_key, max_contacts: self.ensure_contact_on_node(
                client,
                next_public_key,
                max_contacts=max_contacts,
                live_contacts=None,
            ),
            touch_cached_contact=lambda target_public_key: self.touch_cached_contact(target_public_key, interaction=True),
        )

    def send_contact_text_with_client(
        self,
        client,
        *,
        public_key: str,
        text: str,
        sender_timestamp: int,
        max_contacts: int,
        live_contacts: list[dict] | None,
    ):
        if self.is_local_self_contact(self.get_cached_contact(public_key)):
            raise MeshCoreError("self-contact is frozen and hidden from direct messaging")
        return contact_service.send_contact_text_with_client(
            client,
            public_key=public_key,
            text=text,
            sender_timestamp=sender_timestamp,
            max_contacts=max_contacts,
            live_contacts=live_contacts,
            ensure_contact_on_node=self.ensure_contact_on_node,
            touch_cached_contact=lambda target_public_key: self.touch_cached_contact(target_public_key, interaction=True),
        )
