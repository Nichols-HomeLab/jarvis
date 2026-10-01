export async function requireSession(): Promise<void> {
  const check = await fetch("/api/v2/auth/session");
  if (check.ok && (await check.json()).authenticated) return;

  const layer = document.createElement("div");
  layer.style.cssText = "position:fixed;inset:0;z-index:10000;background:#09151c;display:grid;place-items:center;color:#eaf4f2;font:16px sans-serif";
  const form = document.createElement("form");
  form.style.cssText = "display:grid;gap:16px;width:min(90vw,380px);padding:32px;background:#12303b;border:1px solid #538d91;border-radius:12px";
  const title = document.createElement("h1");
  title.textContent = "Jarvis access";
  title.style.margin = "0";
  const input = document.createElement("input");
  input.type = "password";
  input.required = true;
  input.autocomplete = "current-password";
  input.placeholder = "Access token";
  input.setAttribute("aria-label", "Access token");
  input.style.cssText = "padding:12px;font:inherit";
  const button = document.createElement("button");
  button.type = "submit";
  button.textContent = "Unlock";
  button.style.cssText = "padding:12px;font:inherit;cursor:pointer";
  const error = document.createElement("p");
  error.setAttribute("role", "alert");
  form.append(title, input, button, error);
  layer.append(form);
  document.body.append(layer);
  input.focus();

  await new Promise<void>(resolve => {
    form.addEventListener("submit", async event => {
      event.preventDefault();
      button.disabled = true;
      error.textContent = "";
      try {
        const result = await fetch("/api/v2/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: input.value }),
        });
        if (!result.ok) throw new Error("Invalid token or origin");
        input.value = "";
        layer.remove();
        resolve();
      } catch (cause) {
        error.textContent = String(cause);
      } finally {
        button.disabled = false;
      }
    });
  });
}
