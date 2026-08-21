import { createChoiceBuilder } from "./project-builder.js";

document.addEventListener("DOMContentLoaded", () => createChoiceBuilder({
  singleRoot: document.getElementById("visualType"),
  multiRoot: document.getElementById("visualExtras"),
  output: document.getElementById("visualBrief"),
  copyButton: document.getElementById("copyVisual"),
  status: document.getElementById("visualOk"),
  format: ({ primary, extras }) => `SYNAIRGY · FILM & VISUAL LAB\n\nФормат: ${primary}\nДополнительно: ${extras.length ? extras.join(", ") : "обсудить после задачи"}\n\nЦель / идея: ____________________\nПлощадка / формат: ____________________\nСрок: ____________________\n\nНужна консультация по структуре проекта.`
}));
