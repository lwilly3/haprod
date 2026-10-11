/** Les catégories de la bibliothèque (backend projects/library.py) : mêmes clés côté projet (assets/<clé>/). */
import { t } from "../../../i18n";

export const CATEGORY_IDS = ["broll", "musique", "sfx", "images", "logos", "personnes", "lieux"] as const;

/** Libellé traduit d'une catégorie (à appeler au rendu). */
export const categoryLabel = (id: string): string => t(`sourcing.categories.${id}`);
