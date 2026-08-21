import { createChoiceBuilder } from "./project-builder.js";

document.addEventListener("DOMContentLoaded", () => createChoiceBuilder({
  singleRoot: document.getElementById("aiType"),
  multiRoot: document.getElementById("aiExtras"),
  output: document.getElementById("aiBrief"),
  copyButton: document.getElementById("copyAi"),
  status: document.getElementById("aiOk"),
  format: ({ primary, extras }) => `SYNAIRGY · AI & AUTOMATION LAB\n\nЧто строим: ${primary}\nИнтеграции / данные: ${extras.length ? extras.join(", ") : "обсудить после разбора"}\n\nПроблема сейчас: ____________________\nЧто должно происходить автоматически: ____________________\nКакие данные / сервисы уже есть: ____________________\nСрок / приоритет: ____________________\n\nНужна консультация по архитектуре.`
}));
