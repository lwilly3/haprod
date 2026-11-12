import { createRouter, createWebHistory } from "vue-router";
import { t } from "./i18n";

// meta.title : une clé de traduction

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "home", component: () => import("./pages/HomePage.vue"), meta: { title: "nav.projects" } },
    { path: "/nouveau", name: "new", component: () => import("./pages/NewProjectPage.vue"), meta: { title: "nav.newProject" } },
    { path: "/bibliotheque", name: "library", component: () => import("./pages/LibraryPage.vue"), meta: { title: "nav.library" } },
    { path: "/settings/:tab(channel|publish|services|interface)?", name: "settings", component: () => import("./pages/SettingsPage.vue"), meta: { title: "nav.settings" } },
    { path: "/reglages", redirect: "/settings" },
    { path: "/p/:pid", name: "project", component: () => import("./project/OverviewPage.vue") },
    { path: "/p/:pid/brief", name: "brief", component: () => import("./pages/NewProjectPage.vue"), meta: { title: "nav.brief" } },
    { path: "/p/:pid/ressources", name: "resources", component: () => import("./project/ResourcesPage.vue"), meta: { title: "nav.media" } },
    { path: "/p/:pid/:step", name: "step", component: () => import("./project/ProjectPage.vue") },
    // plein écran, sans la barre du haut (bare) : pensé pour le téléphone
    { path: "/prompteur", name: "prompteur-list", component: () => import("./pages/PrompteurPage.vue"), meta: { bare: true } },
    { path: "/prompteur/:pid", name: "prompteur", component: () => import("./pages/PrompteurPage.vue"), meta: { bare: true } },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});

router.afterEach((to) => {
  if (typeof to.meta.title === "string") document.title = `${t(to.meta.title)} · Daryl`;
});
