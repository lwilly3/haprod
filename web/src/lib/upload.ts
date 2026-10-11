import { t } from "../i18n";

/** Envoi de fichiers en multipart avec l'avancement (fetch ne le donne pas). */
export function upload<T = unknown>(url: string, files: File[], field = "files", extra: Record<string, string> = {},
  onProgress?: (fraction: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const f of files) form.append(field, f);
    for (const [k, v] of Object.entries(extra)) form.append(k, v);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress?.(e.loaded / e.total); };
    xhr.onload = () => {
      let body: any = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* corps non JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as T);
      else reject(new Error(body?.detail || xhr.statusText || t("format.uploadFailed")));
    };
    xhr.onerror = () => reject(new Error(t("format.uploadFailed")));
    xhr.send(form);
  });
}

/** Les fichiers d'un glisser-déposer. */
export function droppedFiles(e: DragEvent): File[] {
  return Array.from(e.dataTransfer?.files ?? []);
}
