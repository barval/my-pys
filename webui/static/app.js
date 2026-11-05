document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;
  const value = button.getAttribute("data-copy") || "";
  try {
    await navigator.clipboard.writeText(value);
    const label = button.textContent;
    button.textContent = "Скопировано";
    setTimeout(() => {
      button.textContent = label;
    }, 1200);
  } catch {
    window.prompt("Скопируйте значение:", value);
  }
});
