# Repeater CLI Commands — Full UI Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Add UI for all ~80 CLI commands across 8 remaining repeater categories (basic, radio, routing, adverts, bridge, acl, region, actions), matching the visual style of the existing `location-gps` category.

**Architecture:** Each category is a computed `repeater*Cards` array of card definitions. Each card has: `id`, `label` (i18n), `hint` (i18n), `fields` (inputs/selects bound to draft), `buildCommands(draft)` (returns `string[]` of CLI commands), and `onSuccess(card, draft)` (optional post-apply hook). Cards are rendered in `contactsMode === 'repeater-management'` when `repeaterCategoryId === '<category>'`. Buttons use `mc-btn`, rows use `mc-settings-row` with `mc-settings-row--contacts`, inputs use `mc-settings-row-control`. This matches the 4 existing location-gps cards exactly.

**Tech Stack:** Vue 3 Composition API, `session.api('/api/repeater/cli', ...)`, i18n (`t()` function), CSS classes from `styles.css`.

---

## Current State

**Already implemented (4 cards):**
- `location-gps`: coords, gps-state, gps-advert, gps-actions

**Draft fields already declared (`ContactsView.vue:135-`):**
```javascript
basic_name, basic_admin_password, basic_guest_password, basic_owner_info, 
basic_powersaving, basic_allow_read_only, radio_freq, radio_bw, radio_sf, 
radio_cr, radio_tx, radio_temp_freq/.../timeout, location_lat, location_lon, 
gps_state, gps_advert
```

**Missing draft fields for other categories:**
routing, adverts, bridge, acl, region, actions, sensors, operational, info/logging/neighbors

**Categories list (`repeaterCategories`):**
basic, radio, location-gps, routing, adverts, bridge, acl, region, actions

---

## Files to Change

| File | What |
|------|------|
| `web/src/views/ContactsView.vue` | Add draft fields, card definitions, buildCommands |
| `web/src/i18n/messages/en.js` | All new i18n keys under `contactsView.repeater.*` |
| `web/src/i18n/messages/ru.js` | Same — Russian translations |

---

## Task Plan (ordered by category, each task ~10-20 min)

### Task 1: Add missing draft fields for all categories

**Files:** `ContactsView.vue` (ref declarations ~line 135)

Add reactive refs for all CLI command parameters not yet declared:

```javascript
// routing
const routing_repeat = ref('')
const routing_path_hash_mode = ref('')
const routing_loop_detect = ref('')
const routing_txdelay = ref('')
const routing_direct_txdelay = ref('')
const routing_rxdelay = ref('')
const routing_dutycycle = ref('')
const routing_multi_acks = ref('')
const routing_flood_advert_interval = ref('')
const routing_advert_interval = ref('')
const routing_flood_max = ref('')

// adverts
const advert_zerohop = ref(false)

// bridge
const bridge_type = ref('')
const bridge_enabled = ref('')
const bridge_delay = ref('')
const bridge_source = ref('')
const bridge_baud = ref('')
const bridge_channel = ref('')
const bridge_secret = ref('')

// acl
const acl_public_key = ref('')
const acl_permissions = ref('')

// region
const region_name = ref('')
const region_filter = ref('')
const region_parent = ref('')

// actions / operational
const action_reboot = ref(false)
const action_shutdown = ref(false)
const action_erase = ref(false)

// info (read-only cards — no fields needed)

// CLI freeform
const cli_custom_command = ref('')
```

**Commit:** `feat: add draft fields for all repeater CLI categories`

---

### Task 2: Add i18n keys — categories and generic labels

**Files:** `en.js`, `ru.js` under `contactsView.repeater.*`

Add labels for all 9 categories (if missing) + generic action labels:

```javascript
// en.js
categories: {
  basic: 'Basic',
  radio: 'Radio',
  'location-gps': 'Location / GPS',
  routing: 'Routing',
  adverts: 'Adverts',
  bridge: 'Bridge',
  acl: 'ACL',
  region: 'Region',
  actions: 'Actions',
},
// Generic labels used across cards
cardLabels: {
  set: 'Set',
  get: 'Get',
  enable: 'Enable',
  disable: 'Disable',
  apply: 'Apply',
  clear: 'Clear',
  reboot: 'Reboot',
  shutdown: 'Shutdown',
  erase: 'Erase',
  customCommand: 'Custom command',
  customCommandHint: 'Enter any CLI command and send it to the repeater.',
  send: 'Send',
  output: 'Output',
},
```

**Commit:** `feat: add repeater CLI category labels and generic i18n keys`

---

### Task 3: Card definitions — Basic category (7 cards)

**Files:** `ContactsView.vue` — computed `repeaterBasicCards`

Cards: set-name, set-owner-info, set-admin-password, set-guest-password, get-public-key, get-ver, powersaving

Pattern (example — set-name):
```javascript
{
  id: 'basic-set-name',
  label: t('contactsView.repeater.basicCards.setName.label'),
  hint: t('contactsView.repeater.basicCards.setName.hint'),
  hasChanges(draft) { return draft.basic_name !== '' },
  buildCommands(draft) { return [`set name ${draft.basic_name}`] },
  onSuccess(card, draft) { draft.basic_name = '' }
}
```

Each card uses existing `basic_*` draft fields. Powersaving uses select (on/off). Get- cards are action-only (no fields).

**Commit:** `feat: add Basic repeater category cards (name, owner, passwords, powersaving)`

---

### Task 4: Card definitions — Radio category (5 cards)

**Files:** `ContactsView.vue` — computed `repeaterRadioCards`

Cards: get-radio, set-radio (freq,bw,sf,cr), get-tx, set-tx, get-freq, set-freq (combined), get-radio-rxgain, set-radio-rxgain

Uses existing `radio_*` draft fields. Set-radio combines 4 fields into one CLI command: `set radio <freq>,<bw>,<sf>,<cr>`.

**Commit:** `feat: add Radio repeater category cards`

---

### Task 5: Card definitions — Routing category (10 cards)

**Files:** `ContactsView.vue` — computed `repeaterRoutingCards`

Cards: get/set-repeat, get/set-path-hash-mode, get/set-loop-detect, get/set-txdelay, get/set-direct-txdelay, get/set-rxdelay, get/set-dutycycle, get/set-multi-acks, get/set-flood-advert-interval, get/set-advert-interval, get/set-flood-max

Uses `routing_*` draft fields. Select inputs for enum values (on/off, 0-2, minimal/moderate/strict).

**Commit:** `feat: add Routing repeater category cards`

---

### Task 6: Card definitions — Adverts category (2 cards)

**Files:** `ContactsView.vue` — computed `repeaterAdvertCards`

Cards: advert (action button), advert-zerohop (checkbox + apply)

**Commit:** `feat: add Adverts repeater category cards`

---

### Task 7: Card definitions — Bridge category (7 cards)

**Files:** `ContactsView.vue` — computed `repeaterBridgeCards`

Cards: get/set-bridge-type, get/set-bridge-enabled, get/set-bridge-delay, get/set-bridge-source, get/set-bridge-baud, get/set-bridge-channel, get/set-bridge-secret

Uses `bridge_*` draft fields.

**Commit:** `feat: add Bridge repeater category cards`

---

### Task 8: Card definitions — ACL category (3 cards)

**Files:** `ContactsView.vue` — computed `repeaterAclCards`

Cards: get-acl, setperm, get/set-allow-read-only

`setperm` uses text input for public_key + permissions string.

**Commit:** `feat: add ACL repeater category cards`

---

### Task 9: Card definitions — Region category (5 cards)

**Files:** `ContactsView.vue` — computed `repeaterRegionCards`

Cards: region-list, region-get, region-home, region-put, region-remove

**Commit:** `feat: add Region repeater category cards`

---

### Task 10: Card definitions — Actions category (6 cards)

**Files:** `ContactsView.vue` — computed `repeaterActionCards`

Cards: reboot, shutdown, clock-sync, clear-stats, neighbors, custom-cli

Custom CLI is a text input + send button — freeform command entry.

Reboot/shutdown have confirmation dialog (danger zone).

**Commit:** `feat: add Actions repeater category cards`

---

### Task 11: Card definitions — Info/Stats category (NEW 10th category)

**Files:** `ContactsView.vue` — add category to `repeaterCategories`, computed `repeaterInfoCards`

Cards: ver, board, stats-core, stats-radio, stats-packets, stats-network, log, sensors-list, get-bootloader-ver, get-pwrmgt-support/source/bootreason/bootmv

Read-only action cards — each sends a get- command and displays output.

**Commit:** `feat: add Info/Stats repeater category (10th category)`

---

### Task 12: Card renderer — wire up all category card arrays to template

**Files:** `ContactsView.vue` — template section where `repeaterCategoryId` switches

Ensure each category's template block renders its card array with the same pattern as `location-gps`:

```html
<template v-if="repeaterCategoryId === 'basic'">
  <div v-for="card in repeaterBasicCards" :key="card.id" class="mc-settings-row mc-settings-row--contacts">
    <!-- card fields and apply button -->
  </div>
</template>
```

Verify no category is empty (all 10 have at least one card).

**Commit:** `feat: wire all repeater category card renderers to template`

---

### Task 13: i18n — all card labels and hints (RU + EN)

**Files:** `en.js`, `ru.js`

Full i18n for every card from tasks 3-11. Structure per category:

```javascript
basicCards: {
  setName: { label: 'Node name', hint: 'Set the repeater node name.' },
  setOwnerInfo: { label: 'Owner info', hint: '...' },
  // ... all 7 basic cards
},
radioCards: { /* 5 cards */ },
routingCards: { /* 11 cards */ },
advertCards: { /* 2 cards */ },
bridgeCards: { /* 7 cards */ },
aclCards: { /* 3 cards */ },
regionCards: { /* 5 cards */ },
actionCards: { /* 6 cards */ },
infoCards: { /* 12 cards */ },
```

**Commit:** `feat: add full i18n for all repeater CLI card categories (RU+EN)`

---

### Task 14: Build + deploy + test

**Steps:**
1. `cd /opt/meshcorium/.release/dev/web && npm run build`
2. `rsync` web/src + web/dist to `192.168.4.3`
3. Clear Vite cache + `systemctl restart meshcorium.service`
4. Test: login to repeater, switch between categories, try set-name, get-ver, reboot

**Commit:** `feat: build and deploy full repeater CLI UI`

---

## Summary

| Task | What | Est. lines | Cards |
|------|------|-----------|-------|
| 1 | Draft fields | +40 | — |
| 2 | Generic i18n | +30 EN, +30 RU | — |
| 3 | Basic cards | +80 | 7 |
| 4 | Radio cards | +60 | 5 |
| 5 | Routing cards | +100 | 11 |
| 6 | Adverts cards | +25 | 2 |
| 7 | Bridge cards | +80 | 7 |
| 8 | ACL cards | +40 | 3 |
| 9 | Region cards | +60 | 5 |
| 10 | Actions cards | +70 | 6 |
| 11 | Info/Stats cards | +100 | 12 |
| 12 | Template wiring | +100 | — |
| 13 | Full i18n RU+EN | +300 | all |
| 14 | Build + deploy | — | — |

**Total:** ~14 tasks, ~1000 lines, ~58 CLI command cards across 10 categories.

## Visual Style Rules (preserved from existing location-gps cards)

1. **Row pattern:** `mc-settings-row mc-settings-row--contacts` with `mc-settings-row-label` + `mc-settings-row-control`
2. **Buttons:** `mc-btn mc-btn--sm` for apply actions, `mc-btn mc-btn--sm mc-btn--danger` for destructive
3. **Inputs:** standard `<input>` inside `mc-settings-row-control`, or `<select>` for enum values
4. **Checkboxes:** `mc-settings-checkbox` class
5. **Card groups:** `mc-settings-section` wrapper with optional heading
6. **Hints:** `mc-settings-row-hint` below the control
7. **Result display:** inline text after apply showing success/error
8. **Spacing:** `margin-top: 6px` for result text, `gap` from parent flex

## Risks

- Large PR: 1000+ lines across 3 files. Consider splitting by category into separate PRs.
- Draft reactivity: all new refs must be reset when leaving repeater mode (existing reset logic in `leaveRepeaterManagement()`).
- Template bloat: 10 category blocks in ContactsView.vue. Consider extracting to separate component (`RepeaterCard.vue`) if template exceeds 500 lines.
