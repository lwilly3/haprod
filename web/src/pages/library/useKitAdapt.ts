/**
 * Reporter une inspiration dans le kit : un job Claude par carte. On suit les jobs tant qu'il y en a
 * un en cours ; quand l'un se termine, `onDone` recharge le kit.
 */
import { onBeforeUnmount, ref } from "vue";
import { api, postJson } from "../../lib/api";

export interface AdaptJob {
  file: string; title: string; status: string; finished: boolean; error: string | null;
  result: { name: string; message: string; hard_colors: string[] } | null;
}

export function useKitAdapt(onDone: (job: AdaptJob) => void, onError: (job: AdaptJob) => void) {
  const jobs = ref<AdaptJob[]>([]);
  let timer: number | undefined;

  function track(next: AdaptJob[]) {
    const before = new Map(jobs.value.map((j) => [j.file, j]));
    jobs.value = next;
    for (const j of next) {
      const was = before.get(j.file);
      if (!was || was.finished || !j.finished) continue;
      if (j.status === "done") onDone(j);
      else onError(j);
    }
    clearTimeout(timer);
    if (next.some((j) => !j.finished)) timer = window.setTimeout(refresh, 2500);
  }

  async function refresh() {
    track((await api<{ jobs: AdaptJob[] }>("/api/projects/library/kit/adapt")).jobs);
  }

  async function start(style: string, file: string) {
    track((await postJson<{ jobs: AdaptJob[] }>("/api/projects/library/kit/adapt", { style, file })).jobs);
  }

  const running = (file: string) => jobs.value.some((j) => j.file === file && !j.finished);

  onBeforeUnmount(() => clearTimeout(timer));
  return { jobs, refresh, start, running };
}
