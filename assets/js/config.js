export const siteConfig = Object.freeze({
  site: Object.freeze({ home: "/", sound: "sound.html", visual: "visual.html", automation: "automation.html" }),
  social: Object.freeze({ instagram: "https://www.instagram.com/synairgy.space/", telegram: null, youtube: null }),
  contact: Object.freeze({ email: null, location: "Hamburg, Germany" })
});

export function getConfigValue(path) {
  return path.split(".").reduce((value, key) => value?.[key], siteConfig) ?? null;
}
