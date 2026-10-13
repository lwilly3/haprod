/** Une image de référence : un chemin de la bibliothèque, ou « projet/<rel> » pour un média du projet (backend thumbs.py). */
export const PROJECT_PREFIX = "projet/";

const enc = (rel: string) => rel.split("/").map(encodeURIComponent).join("/");

export const refUrl = (pid: string, rel: string) => rel.startsWith(PROJECT_PREFIX)
  ? `/api/projects/${pid}/files/${enc(rel.slice(PROJECT_PREFIX.length))}`
  : `/api/projects/library/file/${enc(rel)}`;
