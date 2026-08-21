export function createChoiceBuilder({ singleRoot, multiRoot, output, copyButton, status, format }) {
  const render = () => {
    const primary = singleRoot.querySelector(".active")?.dataset.value ?? "Не выбран";
    const extras = [...multiRoot.querySelectorAll(".active")].map((item) => item.dataset.value);
    output.textContent = format({ primary, extras });
  };
  singleRoot.addEventListener("click", (event) => {
    const button = event.target.closest(".choice");
    if (!button) return;
    singleRoot.querySelectorAll(".choice").forEach((item) => item.classList.toggle("active", item === button));
    render();
  });
  multiRoot.addEventListener("click", (event) => {
    const button = event.target.closest(".choice");
    if (!button) return;
    button.classList.toggle("active");
    render();
  });
  copyButton.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(output.textContent); status.textContent = "Скопировано."; }
    catch { status.textContent = "Выдели текст и скопируй вручную."; }
  });
  render();
}
