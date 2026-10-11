import { reactive } from "vue";

export const toastState = reactive({ message: "", error: false, visible: false });
let timer: ReturnType<typeof setTimeout> | undefined;

export function toast(message: string, error = false) {
  Object.assign(toastState, { message, error, visible: true });
  clearTimeout(timer);
  timer = setTimeout(() => (toastState.visible = false), 2400);
}
