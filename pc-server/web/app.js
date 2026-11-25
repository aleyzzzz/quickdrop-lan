(() => {
  const state = {
    items: [],
    filter: "all",
    info: null,
  };

  const els = {
    deviceMeta: document.getElementById("device-meta"),
    lanUrl: document.getElementById("lan-url"),
    sseDot: document.getElementById("sse-dot"),
    copyLanBtn: document.getElementById("copy-lan-btn"),
    autoCopyToggle: document.getElementById("auto-copy-toggle"),
    openDownloadsBtn: document.getElementById("open-downloads-btn"),
    textForm: document.getElementById("text-form"),
    textInput: document.getElementById("text-input"),
    textStatus: document.getElementById("text-status"),
    dropzone: document.getElementById("dropzone"),
    fileInput: document.getElementById("file-input"),
    uploadQueue: document.getElementById("upload-queue"),
    itemsList: document.getElementById("items-list"),
    toast: document.getElementById("toast"),
    tabs: Array.from(document.querySelectorAll(".tab")),
  };

  let toastTimer = null;
  function showToast(msg) {
    els.toast.textContent = msg;
    els.toast.classList.add("visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => els.toast.classList.remove("visible"), 2600);
  }

  function formatSize(bytes) {
    if (!bytes) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let val = bytes;
    let idx = 0;
    while (val >= 1024 && idx < units.length - 1) {
      val /= 1024;
      idx++;
    }
    return `${val.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`;
  }

  function formatTime(isoStr) {
    try {
      const d = new Date(isoStr);
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch {
      return "";
    }
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str || "";
    return div.innerHTML;
  }

  function renderItems() {
    const filtered = state.items.filter((item) => {
      if (state.filter === "all") return true;
      return item.direction === state.filter;
    });

    if (filtered.length === 0) {
      els.itemsList.innerHTML =
        '<div class="empty">No hay transferencias en esta vista todavía.</div>';
      return;
    }

    const fragment = document.createDocumentFragment();
    for (const item of filtered) {
      const card = document.createElement("article");
      card.className = "item";

      const dirLabel = item.direction === "to_pc" ? "Teléfono → PC" : "PC → Teléfono";
      const metaRight = `${escapeHtml(item.sender || "")} · ${formatTime(item.created_at)}`;

      let bodyHtml = "";
      if (item.kind === "link") {
        const safeUrl = escapeHtml(item.content);
        bodyHtml = `<div class="item-body"><a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${safeUrl}</a></div>`;
      } else if (item.kind === "text") {
        bodyHtml = `<div class="item-body">${escapeHtml(item.content)}</div>`;
      } else if (item.kind === "file") {
        const mime = (item.mime_type || "").toLowerCase();
        const inlineUrl = `${item.download_url}?inline=1`;
        let previewHtml = "";
        if (item.file_exists && mime.startsWith("image/")) {
          previewHtml = `<img class="media-preview" src="${inlineUrl}" alt="${escapeHtml(item.filename)}" loading="lazy" />`;
        } else if (item.file_exists && mime.startsWith("audio/")) {
          previewHtml = `<audio class="audio-preview" controls preload="none" src="${inlineUrl}"></audio>`;
        }
        bodyHtml = `
          <div class="item-body"><strong>${escapeHtml(item.filename)}</strong> <span class="muted">(${formatSize(item.size_bytes)})</span></div>
          ${previewHtml}
        `;
      }

      const actions = [];
      if (item.kind === "link" || item.kind === "text") {
        actions.push(`<button class="btn-xs" data-action="copy" data-id="${item.id}">Copiar</button>`);
        if (item.kind === "link") {
          actions.push(
            `<a class="btn-xs" href="${escapeHtml(item.content)}" target="_blank" rel="noopener noreferrer">Abrir enlace</a>`
          );
        }
      } else if (item.kind === "file" && item.file_exists) {
        actions.push(`<a class="btn-xs" href="${item.download_url}" download>Descargar</a>`);
        actions.push(`<button class="btn-xs" data-action="open" data-id="${item.id}">Abrir archivo</button>`);
        actions.push(`<button class="btn-xs" data-action="reveal" data-id="${item.id}">Ver en carpeta</button>`);
      }
      actions.push(`<button class="btn-xs danger" data-action="remove" data-id="${item.id}">Quitar</button>`);

      card.innerHTML = `
        <div class="item-top">
          <span class="badge ${item.direction}">${dirLabel}</span>
          <span>${metaRight}</span>
        </div>
        ${bodyHtml}
        <div class="item-actions">${actions.join("")}</div>
      `;
      fragment.appendChild(card);
    }

    els.itemsList.innerHTML = "";
    els.itemsList.appendChild(fragment);
  }

  async function loadInfo() {
    const res = await fetch("/api/info");
    if (!res.ok) return;
    state.info = await res.json();
    els.deviceMeta.textContent = `${state.info.hostname} · Guardando en ${state.info.download_dir}`;
    els.lanUrl.textContent = state.info.lan_url;
    els.autoCopyToggle.checked = Boolean(state.info.auto_copy_clipboard);
  }

  async function loadItems() {
    const res = await fetch("/api/items?limit=150");
    if (!res.ok) return;
    const data = await res.json();
    state.items = data.items || [];
    renderItems();
  }

  async function sendTextToPhone() {
    const content = els.textInput.value.trim();
    if (!content) return;
    els.textStatus.textContent = "Enviando…";
    try {
      const res = await fetch("/api/pc-send/text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, sender: state.info?.hostname || "PC" }),
      });
      if (!res.ok) throw new Error("Error al enviar");
      els.textInput.value = "";
      els.textStatus.textContent = "Enviado al teléfono ✓";
      setTimeout(() => (els.textStatus.textContent = ""), 2000);
    } catch {
      els.textStatus.textContent = "Error al enviar";
      showToast("No se pudo enviar el texto.");
    }
  }

  function uploadFileStreaming(file) {
    const row = document.createElement("div");
    row.className = "upload-row";
    row.innerHTML = `
      <div class="upload-row-top">
        <span class="upload-name">${escapeHtml(file.name)} (${formatSize(file.size)})</span>
        <span class="muted upload-pct">0%</span>
      </div>
      <div class="progress-track"><div class="progress-fill"></div></div>
    `;
    els.uploadQueue.prepend(row);
    const pctEl = row.querySelector(".upload-pct");
    const fillEl = row.querySelector(".progress-fill");

    const xhr = new XMLHttpRequest();
    const startedAt = performance.now();

    xhr.open("POST", "/api/pc-send/upload/raw", true);
    xhr.setRequestHeader("X-Filename", encodeURIComponent(file.name));
    xhr.setRequestHeader("X-Mime-Type", file.type || "application/octet-stream");
    xhr.setRequestHeader("X-Sender", state.info?.hostname || "PC");
    xhr.setRequestHeader("X-Direction", "to_phone");

    xhr.upload.onprogress = (evt) => {
      if (!evt.lengthComputable) return;
      const pct = Math.min(100, Math.round((evt.loaded / evt.total) * 100));
      const elapsedSec = Math.max(0.05, (performance.now() - startedAt) / 1000);
      const mbps = (evt.loaded / (1024 * 1024) / elapsedSec).toFixed(1);
      pctEl.textContent = `${pct}% · ${mbps} MB/s`;
      fillEl.style.width = `${pct}%`;
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        fillEl.style.width = "100%";
        pctEl.textContent = "Listo ✓";
        showToast(`Enviado al teléfono: ${file.name}`);
        setTimeout(() => row.remove(), 2200);
      } else {
        pctEl.textContent = `Error (${xhr.status})`;
        showToast(`Error subiendo ${file.name}`);
      }
    };

    xhr.onerror = () => {
      pctEl.textContent = "Error de red";
      showToast(`Error de conexión con ${file.name}`);
    };

    xhr.send(file);
  }

  function handleFiles(fileList) {
    for (const file of Array.from(fileList || [])) {
      uploadFileStreaming(file);
    }
  }

  function connectSse() {
    const source = new EventSource("/api/events");
    source.addEventListener("connected", () => {
      els.sseDot.classList.add("online");
    });
    source.addEventListener("item_created", (evt) => {
      const item = JSON.parse(evt.data);
      state.items = [item, ...state.items.filter((i) => i.id !== item.id)];
      renderItems();
    });
    source.addEventListener("item_updated", (evt) => {
      const item = JSON.parse(evt.data);
      state.items = state.items.map((i) => (i.id === item.id ? item : i));
      renderItems();
    });
    source.addEventListener("item_removed", (evt) => {
      const { id } = JSON.parse(evt.data);
      state.items = state.items.filter((i) => i.id !== id);
      renderItems();
    });
    source.addEventListener("settings_updated", (evt) => {
      const data = JSON.parse(evt.data);
      if (typeof data.auto_copy_clipboard === "boolean") {
        els.autoCopyToggle.checked = data.auto_copy_clipboard;
      }
    });
    source.onerror = () => {
      els.sseDot.classList.remove("online");
    };
  }

  // Event listeners
  els.textForm.addEventListener("submit", (e) => {
    e.preventDefault();
    sendTextToPhone();
  });

  els.textInput.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      sendTextToPhone();
    }
  });

  els.dropzone.addEventListener("click", () => els.fileInput.click());
  els.dropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      els.fileInput.click();
    }
  });
  els.fileInput.addEventListener("change", () => {
    handleFiles(els.fileInput.files);
    els.fileInput.value = "";
  });

  ["dragenter", "dragover"].forEach((ev) => {
    els.dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      els.dropzone.classList.add("drag-over");
    });
  });
  ["dragleave", "drop"].forEach((ev) => {
    els.dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      els.dropzone.classList.remove("drag-over");
    });
  });
  els.dropzone.addEventListener("drop", (e) => {
    handleFiles(e.dataTransfer?.files);
  });

  els.copyLanBtn.addEventListener("click", async () => {
    const url = els.lanUrl.textContent;
    try {
      await navigator.clipboard.writeText(url);
      showToast(`Copiado: ${url}`);
    } catch {
      showToast(url);
    }
  });

  els.autoCopyToggle.addEventListener("change", async () => {
    await fetch("/api/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auto_copy_clipboard: els.autoCopyToggle.checked }),
    });
  });

  els.openDownloadsBtn.addEventListener("click", async () => {
    await fetch("/api/open-downloads", { method: "POST" });
  });

  els.tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      els.tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      state.filter = tab.dataset.filter;
      renderItems();
    });
  });

  els.itemsList.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-action]");
    if (!btn) return;
    const { action, id } = btn.dataset;
    const item = state.items.find((i) => i.id === id);
    if (!item) return;

    if (action === "copy" && item.content) {
      await navigator.clipboard.writeText(item.content);
      showToast("Copiado al portapapeles");
    } else if (action === "open") {
      await fetch(`/api/items/${id}/open`, { method: "POST" });
    } else if (action === "reveal") {
      await fetch(`/api/items/${id}/reveal`, { method: "POST" });
    } else if (action === "remove") {
      await fetch(`/api/items/${id}`, { method: "DELETE" });
    }
  });

  loadInfo();
  loadItems();
  connectSse();
})();
