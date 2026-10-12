/**
 * Lâche le fichier d'un <video> / <audio> qu'on n'utilise plus. Sans ça, l'élément retiré de la page continue
 * de télécharger jusqu'à son ramasse-miettes : en HTTP/2 (Vite en HTTPS) rien ne plafonne ces requêtes, et
 * chacune garde une connexion ouverte vers l'API, qui tombe au-delà de 512 (select() de Windows).
 */
export function releaseMedia(m: HTMLMediaElement | null | undefined) {
  if (!m) return;
  m.pause();
  m.removeAttribute("src");
  // sans src, load() coupe la requête en cours
  m.load();
}
