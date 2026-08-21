import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { siteConfig, getConfigValue } from "../assets/js/config.js";

assert.equal(getConfigValue("site.visual"), "visual.html");
assert.equal(getConfigValue("social.telegram"), null);
assert.ok(Object.isFrozen(siteConfig));

for (const page of ["index.html", "sound.html", "visual.html", "automation.html"]) {
  const html = readFileSync(new URL(`../${page}`, import.meta.url), "utf8");
  assert.match(html, /<main(?:\s|>)/, `${page} needs a main element`);
  assert.match(html, /assets\/css\/tokens\.css/, `${page} needs shared tokens`);
  assert.match(html, /assets\/js\/core\.js/, `${page} needs shared initialization`);
}

console.log("Site structure checks passed.");
