<template>
  <div class="mc-mobile-shell mc-mobile-contacts-shell">
    <div class="mc-mobile-phonebar">
      <slot name="phonebar" />
    </div>

    <main class="mc-mobile-contacts-main">
      <slot name="contacts" />
    </main>

    <div class="mc-mobile-nodebar">
      <slot name="nodebar" />
    </div>

    <nav class="mc-mobile-dock">
      <slot name="dock" />
    </nav>
  </div>
</template>

<style scoped>
.mc-mobile-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  height: 100dvh;
  width: 100%;
  overflow: hidden;
  background: var(--mc-shell-unified-surface, #16212d);
}

.mc-mobile-phonebar {
  flex-shrink: 0;
  z-index: 10;
}

.mc-mobile-contacts-main {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.mc-mobile-nodebar {
  flex-shrink: 0;
  padding: 4px 12px;
  border-top: 1px solid rgba(255,255,255,0.04);
  background: var(--mc-shell-unified-surface, #16212d);
}

.mc-mobile-dock {
  flex-shrink: 0;
  display: flex;
  justify-content: space-around;
  align-items: center;
  height: 64px;
  padding: 0 8px;
  padding-bottom: env(safe-area-inset-bottom, 0px);
  background: var(--mc-shell-unified-surface, #16212d);
  border-top: 1px solid rgba(255,255,255,0.06);
  z-index: 20;
}
</style>
