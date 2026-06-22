const port = Number(process.argv[2] || 9223);

async function main() {
  const targets = await fetch(`http://127.0.0.1:${port}/json`).then((response) => response.json());
  const page = targets.find((target) => target.type === "page");
  if (!page) throw new Error("No Electron renderer target found");
  const socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  const result = await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error("Renderer evaluation timed out")), 5000);
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.id !== 1) return;
      clearTimeout(timeout);
      resolve(message);
    });
    socket.send(JSON.stringify({
      id: 1,
      method: "Runtime.evaluate",
      params: {
        expression: `JSON.stringify({
          ready: document.readyState,
          styles: document.styleSheets.length,
          api: Boolean(window.desktopShell?.request),
          title: document.title,
          errorToasts: document.querySelectorAll('.toast.error').length
        })`,
        returnByValue: true
      }
    }));
  });
  socket.close();
  const value = JSON.parse(result.result.result.value);
  if (value.ready !== "complete" || value.styles < 1 || !value.api || value.title !== "TpF2 Modmanager" || value.errorToasts) {
    throw new Error(`Renderer smoke test failed: ${JSON.stringify(value)}`);
  }
  console.log(`renderer-smoke-ok ${JSON.stringify(value)}`);
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
