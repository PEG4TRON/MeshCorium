import { readonly, ref } from 'vue'
import { detectNativeShell } from '../lib/nativeShell'

const isNativeShell = ref(detectNativeShell())

export function useNativeShell() {
  return {
    isNativeShell: readonly(isNativeShell),
  }
}
