const port = Number(process.argv[2] || 9223);
const expectFirstRun = process.argv.includes("--expect-first-run");
const expectNoFirstRun = process.argv.includes("--expect-no-first-run");

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
          errorToasts: document.querySelectorAll('.toast.error').length,
          dark: document.documentElement.classList.contains('dark'),
          themeDisabled: document.getElementById('themeToggle')?.disabled === true,
          sourcePanelsInMain: document.querySelectorAll('main .path-panel').length,
          sourcePanelsInSettings: document.querySelectorAll('#settingsModal .path-panel').length,
          firstRunModal: !document.getElementById('settingsModal')?.classList.contains('hidden')
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
  if (value.dark || !value.themeDisabled || value.sourcePanelsInMain !== 0 || value.sourcePanelsInSettings !== 1) {
    throw new Error(`Renderer layout smoke test failed: ${JSON.stringify(value)}`);
  }
  if (expectFirstRun && !value.firstRunModal) {
    throw new Error(`First-run source modal did not open: ${JSON.stringify(value)}`);
  }
  if (expectNoFirstRun && value.firstRunModal) {
    throw new Error(`First-run source modal opened more than once: ${JSON.stringify(value)}`);
  }
  console.log(`renderer-smoke-ok ${JSON.stringify(value)}`);
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
