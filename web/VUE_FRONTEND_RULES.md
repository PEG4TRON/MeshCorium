# MeshCorium Vue Frontend Rules

Purpose:
- Define the agreed Vue frontend architecture for MeshCorium.
- Keep the Vue frontend route/API behavior stable while the old non-Vue frontend remains retired.
- Freeze a small set of rules so future migration work stays consistent across sessions.

Official basis:
- Vue Routing guide: https://vuejs.org/guide/scaling-up/routing
- Vue State Management guide: https://vuejs.org/guide/scaling-up/state-management.html
- Vue Composables guide: https://vuejs.org/guide/reusability/composables.html
- Vue Props guide: https://vuejs.org/guide/components/props.html
- Vue Style Guide essential rules: https://vuejs.org/style-guide/rules-essential.html
- Vue Router guide: https://router.vuejs.org/guide/
- Pinia introduction: https://pinia.vuejs.org/introduction.html
- Vite guide: https://vite.dev/guide/

Important note:
- Rules below marked as "Project decision" are MeshCorium-specific inferences built on top of the official docs. They are not direct framework requirements, but they are mandatory for this repository unless explicitly changed later.

## Chosen solution

Use this stack for the new production frontend under `web/`:
- `Vue 3` with single-file components
- `Vite` for local development and production build output
- `Vue Router` for all SPA navigation and browser history synchronization
- `Pinia` for shared application state
- `vue-i18n` for multilingual UI strings and route-title localization
- `VueUse` for browser/storage/document composables and reusable UI state helpers
- `Floating Vue` for tooltip / popover / dropdown positioning primitives
- `Vitest` plus `@vue/test-utils` for unit/component verification
- `Playwright` for browser smoke and parity checks
- Vue composables for reusable stateful logic, API orchestration, and SSE lifecycle wiring

Why this stack:
- Vue's official routing guide recommends the officially supported `Vue Router` for most SPAs.
- Vue's official state-management guide recommends `Pinia` for new applications, with `Vuex` now in maintenance mode.
- Vue's composables guide treats composables as the standard way to extract and reuse stateful logic with lifecycle hooks.
- Vite keeps `index.html` and built assets first-class, which fits the current Python-hosted `web/dist` deployment model well.
- Project decision: prefer `VueUse` over ad-hoc browser helper glue where it already provides a stable primitive (`storage`, `document title`, `visibility`, timers, element metrics, keyboard state).
- Project decision: all new user-facing copy in Vue screens should move behind `vue-i18n` keys instead of growing hard-coded strings in templates.
- Project decision: standardize future Vue tooltip/popover work on one floating layer (`Floating Vue`) instead of growing multiple independent custom positioning systems.
- Project decision: the approved stack is meant to be used proactively, not merely installed. When one of these tools already fits the problem, prefer it over custom ad-hoc code that would later need migration.

## Mandatory architecture rules

1. Preserve the Vue route contract.
- The Vue app owns the current path model: `/`, `/connect`, `/messages`, `/contacts`, `/contacts/groups`, `/contacts/repeater-login/:key`, `/contacts/repeater/:key/:category?`, `/maps`, `/maps/route-checks`, `/settings/:section?`.
- Do not switch the project to hash routing.
- Deep links, browser back/forward, and reload behavior must stay compatible with the current Python host.

2. Model the desktop shell with nested routes.
- Use `Vue Router` nested routes so the shared `rail / scroller / workspace / phonebar` frame is one durable shell, and feature screens render inside it.
- Internal workspace flows that behave like nested screens should map to nested route records, not to ad-hoc boolean toggles.
- Project decision: the connect/auth overlay is part of the shell model and should eventually live as a true overlay above the shared messages shell instead of being reimplemented as a disconnected standalone page.

3. Keep scroll ownership explicit.
- Configure router `scrollBehavior` deliberately.
- Browser back/forward should restore the expected position where appropriate.
- Project decision: nested MeshCorium scrollers remain screen-owned, so route transitions must not silently reset or steal scroll from the active `scroller` or workspace list.

4. Keep the backend as the source of truth.
- Existing REST and SSE contracts are compatibility boundaries during migration.
- Do not redesign API payloads just because the frontend stack changed.
- Frontend state may cache and shape backend data for rendering, but protocol semantics, auth, connect flow, and session lifecycle remain owned by Python backend code.

5. Centralize cross-screen state in Pinia, keep widget state local.
- Use `Pinia` stores for shared state that must survive route changes or be read by multiple screens: auth/session snapshot, selected port/baudrate, channels summary, contacts summary, live service state, unread counters, client settings, and route-linked UI state.
- Keep ephemeral component-only concerns local: input draft visibility toggles, hover state, temporary float openness, local filter text that is not shared, and similar short-lived view state.
- Project decision: one store per domain boundary is preferred over one giant global store.

6. Put side effects into composables and service adapters, not arbitrary view components.
- Reusable logic with lifecycle hooks belongs in composables named with `use...`.
- Composables should return plain objects containing refs, following the Vue composables guide.
- Project decision: direct `fetch()` / `EventSource` calls should live in thin `api/` and `sse/` adapters plus domain composables or stores, not be scattered across many UI components.

7. Keep one-way data flow strict.
- Props are one-way down; child components must not mutate props.
- Components should declare props as explicitly as practical.
- Mutations to shared state should happen through store actions, emitted events, or explicit callbacks, not through hidden prop/object mutation from deeply nested children.

8. Use durable component conventions.
- Use Vue single-file components for app code.
- Use multi-word component names.
- Project decision: prefer `script setup` for new components unless there is a concrete reason not to.
- Project decision: separate shell/container components from reusable presentational primitives so layout migration and behavior migration can progress independently.

9. Preserve the shared Vue shell before polishing visuals.
- Match layout structure and interaction flow first: route, frame, overlay behavior, connect flow, scroller ownership, and session state.
- Then tighten visual parity against screenshots and Chromium renders.
- Project decision: do not introduce third-party UI kits unless they clearly remove complexity without pulling the design away from the current MeshCorium look and behavior.

10. Keep Python-hosted production assets simple.
- Vite production output must stay buildable into `web/dist`.
- The Python server remains the production host for built assets.
- Avoid runtime CDN dependencies for core app code, icons, fonts, or framework assets unless explicitly approved.

11. Keep frontend verification first-class from the start.
- Unit and component behavior should be covered through `Vitest` plus `@vue/test-utils`.
- Browser smoke and parity checks should use `Playwright`, ideally against the same local Python-hosted build and Chromium setup used for manual screenshot review.
- Project decision: toolchain adoption should happen early in the migration instead of being postponed until after most screens are ported.

12. Use the approved stack by default when it matches the task.
- Prefer `Vue Router` over manual route-state booleans for screen/subscreen flow.
- Prefer `Pinia` over scattered shared refs when state crosses route or feature boundaries.
- Prefer `vue-i18n` for user-visible strings instead of growing hard-coded copy in templates.
- Prefer `VueUse` for browser/storage/document/timer/media helpers instead of ad-hoc wrappers.
- Prefer `Floating Vue` for tooltip/popover/dropdown positioning instead of one-off float logic.
- Prefer `Vitest` for unit/component checks and `Playwright` for browser smoke/parity when adding or changing significant frontend behavior.
- Project decision: "we will wire it later" is not the default path for these tools in this repository.

13. Keep the retired legacy namespace from returning as a fallback.
- Do not add new Vue-to-legacy handoffs.
- `/legacy/*` should redirect to Vue equivalents when a direct mapping exists or fail clearly for unmapped paths.
- Project decision: the old non-Vue desktop/mobile frontend has been removed from active serving; future mobile work should be built in Vue rather than restored from legacy code.

## Recommended source layout for `web/src`

Project decision:
- `app/` for app bootstrap, router, and top-level shell wiring
- `stores/` for Pinia domain stores
- `composables/` for reusable stateful logic
- `api/` for REST adapters
- `sse/` for live event adapters
- `features/messages`, `features/contacts`, `features/maps`, `features/settings`, `features/repeater` for screen modules
- `components/shell` for frame primitives
- `components/ui` for reusable presentational primitives

This layout is not mandatory line-for-line, but the ownership split is mandatory.

## Migration-specific implementation rules for MeshCorium

Project decision:
- Route names, params, and path semantics must stay aligned with the current backend.
- `messages` is the shell reference for desktop parity; new desktop screens should inherit that frame instead of inventing a new one.
- Connection/session orchestration should converge into one explicit session store that owns restore, reconnecting, queue-drain, and live snapshot state.
- Message, contact, and settings screens should consume shared domain stores instead of each screen re-fetching the same session context independently.
- Android WebView assumptions remain compatibility-sensitive: auth cookies, normal paths, and mute-sync bridge behavior must remain compatible unless intentionally redesigned and documented.

## Verification gate for frontend migration work

After meaningful Vue/frontend changes, run at least:
- `npm run build` in `web/`
- `python3 -m py_compile meshcorium/meshcorium_web.py meshcorium/meshcorium_client.py`

For UI-affecting work, also prefer:
- Chromium screenshot or smoke-check of the relevant route
- One desktop-sized render and one mobile-sized render when the change touches shared shell/layout behavior
