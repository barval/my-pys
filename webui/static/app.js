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

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-fill]");
  if (!button) return;
  const fields = { ip: "ip", mac: "mac", deviceId: "device_id", model: "model" };
  Object.entries(fields).forEach(([key, name]) => {
    const value = button.dataset[key];
    const input = document.querySelector(`input[name="${name}"]`);
    if (value && input) input.value = value;
  });
});

document.querySelectorAll("[data-dialog-open]").forEach((button) => {
  const dialog = document.getElementById(button.getAttribute("data-dialog-open"));
  if (!dialog) return;
  button.addEventListener("click", () => dialog.showModal());
});

document.querySelectorAll("dialog [data-dialog-close]").forEach((button) => {
  const dialog = button.closest("dialog");
  if (dialog) button.addEventListener("click", () => dialog.close());
});
