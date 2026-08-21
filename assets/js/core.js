import { getConfigValue } from "./config.js";

function configureLinks(root = document) {
  root.querySelectorAll("[data-link]").forEach((element) => {
    const url = getConfigValue(element.dataset.link);
    if (url) {
      element.href = url;
      element.removeAttribute("aria-disabled");
      element.classList.remove("site-placeholder");
      return;
    }
    element.removeAttribute("href");
    element.setAttribute("aria-disabled", "true");
    element.classList.add("site-placeholder");
  });
}

function configureYears(root = document) {
  root.querySelectorAll("[data-current-year]").forEach((element) => { element.textContent = String(new Date().getFullYear()); });
}

function configureMobileNavigation(root = document) {
  root.querySelectorAll("[data-nav-root]").forEach((navRoot) => {
    const toggle = navRoot.querySelector("[data-nav-toggle]");
    const menu = navRoot.querySelector("[data-nav-menu]");
    if (!toggle || !menu) return;
    const close = () => { menu.dataset.open = "false"; toggle.setAttribute("aria-expanded", "false"); };
    toggle.addEventListener("click", () => {
      const open = menu.dataset.open !== "true";
      menu.dataset.open = String(open);
      toggle.setAttribute("aria-expanded", String(open));
    });
    menu.addEventListener("click", (event) => { if (event.target.closest("a")) close(); });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") close(); });
  });
}

export function initSite(root = document) {
  configureLinks(root);
  configureYears(root);
  configureMobileNavigation(root);
}

document.addEventListener("DOMContentLoaded", () => initSite());
