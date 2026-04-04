<script setup>
import { computed, ref, useAttrs } from 'vue'
import { useElementSize } from '@vueuse/core'

defineOptions({
  inheritAttrs: false,
})

const props = defineProps({
  modelValue: {
    type: [String, Number, Boolean, Object],
    default: null,
  },
  options: {
    type: Array,
    default: () => [],
  },
  placeholder: {
    type: String,
    default: '',
  },
  disabled: {
    type: Boolean,
    default: false,
  },
  compact: {
    type: Boolean,
    default: false,
  },
  minWidth: {
    type: Number,
    default: 20,
  },
})

const emit = defineEmits(['update:modelValue'])

const attrs = useAttrs()
const triggerRef = ref(null)
const { width: triggerWidth } = useElementSize(triggerRef)

function sameValue(left, right) {
  return String(left ?? '') === String(right ?? '')
}

const normalizedOptions = computed(() => {
  return props.options.map((entry, index) => {
    if (typeof entry === 'object' && entry !== null) {
      return {
        key: entry.key ?? `${index}:${String(entry.value ?? '')}`,
        value: entry.value,
        label: String(entry.label ?? entry.value ?? ''),
        triggerLabel: String(entry.triggerLabel ?? entry.label ?? entry.value ?? ''),
        meta: entry.meta ? String(entry.meta) : '',
        disabled: Boolean(entry.disabled),
      }
    }
    return {
      key: `${index}:${String(entry ?? '')}`,
      value: entry,
      label: String(entry ?? ''),
      triggerLabel: String(entry ?? ''),
      meta: '',
      disabled: false,
    }
  })
})

const selectedOption = computed(() => {
  return normalizedOptions.value.find((entry) => sameValue(entry.value, props.modelValue)) || null
})

const buttonLabel = computed(() => {
  return selectedOption.value?.triggerLabel || props.placeholder
})

const menuMinWidth = computed(() => {
  return `${Math.max(props.minWidth, Math.round(triggerWidth.value || 0))}px`
})

function selectOption(option, hide) {
  if (option.disabled) {
    return
  }
  emit('update:modelValue', option.value)
  hide()
}
</script>

<template>
  <div class="mc-plugin-dropdown-shell" v-bind="attrs">
    <VDropdown
      theme="meshcorium-dropdown"
      placement="bottom-start"
      :distance="10"
      :disabled="disabled"
    >
      <button
        ref="triggerRef"
        class="mc-plugin-dropdown"
        :class="{ 'is-compact': compact, 'is-disabled': disabled }"
        type="button"
        :disabled="disabled"
      >
        <span class="mc-plugin-dropdown-side-spacer" aria-hidden="true"></span>
        <span class="mc-plugin-dropdown-label">{{ buttonLabel }}</span>
        <span class="mc-plugin-dropdown-caret" aria-hidden="true">▾</span>
      </button>

      <template #popper="{ hide }">
        <div class="mc-plugin-dropdown-menu" :style="{ minWidth: menuMinWidth }">
          <button
            v-for="option in normalizedOptions"
            :key="option.key"
            class="mc-plugin-dropdown-option"
            :class="{ active: selectedOption && sameValue(option.value, selectedOption.value), 'is-disabled': option.disabled }"
            type="button"
            :disabled="option.disabled"
            @click="selectOption(option, hide)"
          >
            <span class="mc-plugin-dropdown-option-mark mc-plugin-dropdown-option-mark--ghost" aria-hidden="true"></span>
            <span class="mc-plugin-dropdown-option-main">
              <span class="mc-plugin-dropdown-option-label">{{ option.label }}</span>
              <span v-if="option.meta" class="mc-plugin-dropdown-option-meta">{{ option.meta }}</span>
            </span>
            <span v-if="selectedOption && sameValue(option.value, selectedOption.value)" class="mc-plugin-dropdown-option-mark" aria-hidden="true">
              ✓
            </span>
          </button>
        </div>
      </template>
    </VDropdown>
  </div>
</template>
