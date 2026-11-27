(() => {
  function showFatalError(msg) {
    const banner = document.getElementById("error-banner");
    if (banner) {
      banner.textContent = `Error en la interfaz: ${msg}`;
      banner.classList.add("visible");
    }
  }

  window.onerror = (message, source, lineno, colno) => {
    const detail = `${message} (${source || "app.js"}:${lineno || 0}:${colno || 0})`;
    console.error("QuickDrop JS error:", detail);
    showFatalError(detail);
    return false;
  };

  window.addEventListener("unhandledrejection", (event) => {
    const reason = event?.reason?.message || String(event?.reason || "Promesa rechazada");
    console.error("QuickDrop unhandled rejection:", reason);
    showFatalError(reason);
  });

  const URL_REGEX = /^https?:\/\/\S+$/i;

  const ICONS = {
    copy: `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`,
    check: `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
    open: `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>`,
    download: `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>`,
    folder: `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>`,
    trash: `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>`,
    link: `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>`,
    image: `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>`,
    video: `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg>`,
    audio: `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>`,
    file: `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>`,
    text: `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="17" y1="10" x2="3" y2="10"/><line x1="21" y1="6" x2="3" y2="6"/><line x1="21" y1="14" x2="3" y2="14"/><line x1="17" y1="18" x2="3" y2="18"/></svg>`,
  };

  function init() {
    const savedView = (() => {
      try {
        return localStorage.getItem("quickdrop_view_mode") === "list" ? "list" : "cards";
      } catch {
        return "cards";
      }
    })();

    const state = {
      items: [],
      direction: "all",
      typeFilter: "all",
      search: "",
      viewMode: savedView,
      info: null,
      sse: null,
      sendingText: false,
      stagedFiles: [], // { id, file, previewUrl }
      uploadingStaged: false,
    };

    const els = {
      deviceMeta: document.getElementById("device-meta"),
      lanUrl: document.getElementById("lan-url"),
      sseDot: document.getElementById("sse-dot"),
      sseLabel: document.getElementById("sse-label"),
      copyLanBtn: document.getElementById("copy-lan-btn"),
      autoCopyToggle: document.getElementById("auto-copy-toggle"),
      openDownloadsBtn: document.getElementById("open-downloads-btn"),
      urlDetectedBadge: document.getElementById("url-detected-badge"),
      textForm: document.getElementById("text-form"),
      textInput: document.getElementById("text-input"),
      pasteBtn: document.getElementById("paste-btn"),
      sendTextBtn: document.getElementById("send-text-btn"),
      textStatus: document.getElementById("text-status"),
      dropzone: document.getElementById("dropzone"),
      fileInput: document.getElementById("file-input"),
      stagedSection: document.getElementById("staged-section"),
      stagedSummary: document.getElementById("staged-summary"),
      stagedList: document.getElementById("staged-list"),
      clearStagedBtn: document.getElementById("clear-staged-btn"),
      sendStagedBtn: document.getElementById("send-staged-btn"),
      uploadQueue: document.getElementById("upload-queue"),
      searchInput: document.getElementById("search-input"),
      searchClearBtn: document.getElementById("search-clear-btn"),
      viewCardsBtn: document.getElementById("view-cards-btn"),
      viewListBtn: document.getElementById("view-list-btn"),
      clearHistoryBtn: document.getElementById("clear-history-btn"),
      dirTabs: Array.from(document.querySelectorAll(".dir-tab")),
      typePills: Array.from(document.querySelectorAll(".type-pill")),
      countAll: document.getElementById("count-all"),
      countToPc: document.getElementById("count-to_pc"),
      countToPhone: document.getElementById("count-to_phone"),
      itemsList: document.getElementById("items-list"),
      lightboxModal: document.getElementById("lightbox-modal"),
      lightboxTitle: document.getElementById("lightbox-title"),
      lightboxSub: document.getElementById("lightbox-sub"),
      lightboxDownload: document.getElementById("lightbox-download"),
      lightboxClose: document.getElementById("lightbox-close"),
      lightboxStage: document.getElementById("lightbox-stage"),
      confirmModal: document.getElementById("confirm-modal"),
      confirmCancelBtn: document.getElementById("confirm-cancel-btn"),
      confirmAcceptBtn: document.getElementById("confirm-accept-btn"),
      toast: document.getElementById("toast"),
    };

    let toastTimer = null;
    function showToast(msg) {
      if (!els.toast) return;
      els.toast.textContent = msg;
      els.toast.classList.add("visible");
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => els.toast.classList.remove("visible"), 2600);
    }

    function setConnectionStatus(online, labelText) {
      if (els.sseDot) els.sseDot.classList.toggle("online", Boolean(online));
      if (els.sseLabel) {
        els.sseLabel.textContent = labelText || (online ? "Conectado" : "Reconectando…");
        els.sseLabel.classList.toggle("online", Boolean(online));
      }
    }

    function formatSize(bytes) {
      if (!bytes || bytes <= 0) return "0 B";
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
        if (Number.isNaN(d.getTime())) return "";
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

    function extractHost(urlStr) {
      try {
        return new URL(urlStr).hostname.replace(/^www\./, "");
      } catch {
        return "Enlace";
      }
    }

    async function fetchWithTimeout(url, options = {}, timeoutMs = 8000) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        return await fetch(url, { ...options, signal: controller.signal });
      } finally {
        clearTimeout(timer);
      }
    }

    function classifyItemType(item) {
      if (item.kind === "link") return "links";
      if (item.kind === "text") return "text";
      const mime = (item.mime_type || "").toLowerCase();
      const name = (item.filename || "").toLowerCase();
      if (mime.startsWith("image/") || /\.(png|jpe?g|gif|webp|bmp|svg|avif)$/.test(name)) {
        return "images";
      }
      if (
        mime.startsWith("audio/") ||
        mime.startsWith("video/") ||
        /\.(mp3|wav|ogg|flac|m4a|opus|aac|mp4|webm|mkv|mov|avi)$/.test(name)
      ) {
        return "av";
      }
      return "docs";
    }

    function isVideoItem(item) {
      const mime = (item.mime_type || "").toLowerCase();
      const name = (item.filename || "").toLowerCase();
      return mime.startsWith("video/") || /\.(mp4|webm|mkv|mov|avi)$/.test(name);
    }

    function isAudioItem(item) {
      const mime = (item.mime_type || "").toLowerCase();
      const name = (item.filename || "").toLowerCase();
      return mime.startsWith("audio/") || /\.(mp3|wav|ogg|flac|m4a|opus|aac)$/.test(name);
    }

    function isImageItem(item) {
      return item.kind === "file" && classifyItemType(item) === "images";
    }

    function getChronologicalGroup(isoStr) {
      const d = new Date(isoStr);
      if (Number.isNaN(d.getTime())) return "Anteriores";
      const now = new Date();
      const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      const startYesterday = new Date(startToday);
      startYesterday.setDate(startYesterday.getDate() - 1);
      const startWeek = new Date(startToday);
      startWeek.setDate(startWeek.getDate() - 6);

      if (d >= startToday) return "Hoy";
      if (d >= startYesterday) return "Ayer";
      if (d >= startWeek) return "Esta semana";
      return "Anteriores";
    }

    function updateDirectionCounts() {
      let toPc = 0;
      let toPhone = 0;
      for (const item of state.items) {
        if (item.direction === "to_pc") toPc++;
        else if (item.direction === "to_phone") toPhone++;
      }
      if (els.countAll) els.countAll.textContent = String(state.items.length);
      if (els.countToPc) els.countToPc.textContent = String(toPc);
      if (els.countToPhone) els.countToPhone.textContent = String(toPhone);
    }

    function applyViewMode(mode) {
      state.viewMode = mode === "list" ? "list" : "cards";
      try {
        localStorage.setItem("quickdrop_view_mode", state.viewMode);
      } catch {}
      if (els.viewCardsBtn) els.viewCardsBtn.classList.toggle("active", state.viewMode === "cards");
      if (els.viewListBtn) els.viewListBtn.classList.toggle("active", state.viewMode === "list");
      if (els.itemsList) {
        els.itemsList.classList.toggle("view-cards", state.viewMode === "cards");
        els.itemsList.classList.toggle("view-list", state.viewMode === "list");
      }
      renderItems();
    }

    function getFilteredItems() {
      const q = state.search.trim().toLowerCase();
      return state.items
        .filter((item) => {
          if (state.direction !== "all" && item.direction !== state.direction) return false;
          if (state.typeFilter !== "all") {
            const cat = classifyItemType(item);
            if (cat !== state.typeFilter) return false;
          }
          if (q) {
            const hay = `${item.filename || ""} ${item.content || ""} ${item.sender || ""} ${item.mime_type || ""}`.toLowerCase();
            if (!hay.includes(q)) return false;
          }
          return true;
        })
        .sort((a, b) => {
          const ta = Date.parse(a.created_at || "") || 0;
          const tb = Date.parse(b.created_at || "") || 0;
          return tb - ta;
        });
    }

    function buildIconActionsHtml(item) {
      const btns = [];
      if (item.kind === "link" || item.kind === "text") {
        btns.push(`<button class="icon-btn" type="button" data-action="copy" data-id="${item.id}" title="Copiar" aria-label="Copiar">${ICONS.copy}</button>`);
        if (item.kind === "link") {
          btns.push(`<a class="icon-btn" href="${escapeHtml(item.content)}" target="_blank" rel="noopener noreferrer" title="Abrir enlace" aria-label="Abrir enlace">${ICONS.open}</a>`);
        }
      } else if (item.kind === "file" && item.file_exists) {
        btns.push(`<a class="icon-btn" href="${item.download_url}" download title="Descargar" aria-label="Descargar">${ICONS.download}</a>`);
        btns.push(`<button class="icon-btn" type="button" data-action="open" data-id="${item.id}" title="Abrir archivo" aria-label="Abrir archivo">${ICONS.open}</button>`);
        btns.push(`<button class="icon-btn" type="button" data-action="reveal" data-id="${item.id}" title="Mostrar en carpeta" aria-label="Mostrar en carpeta">${ICONS.folder}</button>`);
      }
      btns.push(`<button class="icon-btn danger" type="button" data-action="remove" data-id="${item.id}" title="Quitar del historial" aria-label="Quitar del historial">${ICONS.trash}</button>`);
      return btns.join("");
    }

    function buildCardNode(item) {
      const card = document.createElement("article");
      card.className = "item-card";
      card.dataset.id = item.id;

      const dirLabel = item.direction === "to_pc" ? "↓ PC" : "↑ Teléfono";
      const metaRight = `${escapeHtml(item.sender || "")} · <span class="mono">${formatTime(item.created_at)}</span>`;

      let contentHtml = "";
      let leftFooterHtml = "";

      if (item.kind === "link") {
        const safeUrl = escapeHtml(item.content);
        const host = escapeHtml(extractHost(item.content));
        contentHtml = `
          <div class="link-box">
            <div class="link-favicon" aria-hidden="true">${ICONS.link}</div>
            <div class="link-info">
              <span class="link-host">${host}</span>
              <a class="link-url" href="${safeUrl}" target="_blank" rel="noopener noreferrer" title="${safeUrl}">${safeUrl}</a>
            </div>
          </div>
        `;
        leftFooterHtml = `
          <div class="quick-actions">
            <button class="chip-action" type="button" data-action="copy-chip" data-id="${item.id}">${ICONS.copy}<span>Copiar</span></button>
            <a class="chip-action" href="${safeUrl}" target="_blank" rel="noopener noreferrer">${ICONS.open}<span>Abrir</span></a>
          </div>
        `;
      } else if (item.kind === "text") {
        contentHtml = `<div class="text-snippet">${escapeHtml(item.content)}</div>`;
        leftFooterHtml = `
          <div class="quick-actions">
            <button class="chip-action" type="button" data-action="copy-chip" data-id="${item.id}">${ICONS.copy}<span>Copiar</span></button>
          </div>
        `;
      } else if (item.kind === "file") {
        const inlineUrl = `${item.download_url}?inline=1`;
        const fname = escapeHtml(item.filename || "Archivo");
        const sizeStr = formatSize(item.size_bytes);

        if (item.file_exists && isImageItem(item)) {
          contentHtml = `
            <div class="media-thumb-wrap" data-action="lightbox" data-id="${item.id}" role="button" tabindex="0" title="Clic para ampliar">
              <img class="media-thumb" src="${inlineUrl}" alt="${fname}" loading="lazy" />
              <span class="media-zoom-hint">Ampliar</span>
            </div>
            <div class="file-headline">
              <div class="file-name-wrap">
                <span class="file-name" title="${fname}">${fname}</span>
                <span class="file-sub mono">${sizeStr}</span>
              </div>
            </div>
          `;
        } else if (item.file_exists && isVideoItem(item)) {
          contentHtml = `
            <div class="media-thumb-wrap" data-action="lightbox" data-id="${item.id}" role="button" tabindex="0" title="Clic para reproducir">
              <video class="media-thumb" src="${inlineUrl}" muted preload="metadata"></video>
              <span class="media-zoom-hint">▶ Reproducir</span>
            </div>
            <div class="file-headline">
              <div class="file-name-wrap">
                <span class="file-name" title="${fname}">${fname}</span>
                <span class="file-sub mono">${sizeStr}</span>
              </div>
            </div>
          `;
        } else if (item.file_exists && isAudioItem(item)) {
          contentHtml = `
            <div class="file-headline">
              <div class="file-type-ico" aria-hidden="true">${ICONS.audio}</div>
              <div class="file-name-wrap">
                <span class="file-name" title="${fname}">${fname}</span>
                <span class="file-sub mono">${sizeStr}</span>
              </div>
            </div>
            <audio class="audio-player" controls preload="none" src="${inlineUrl}"></audio>
          `;
        } else {
          contentHtml = `
            <div class="file-headline">
              <div class="file-type-ico" aria-hidden="true">${ICONS.file}</div>
              <div class="file-name-wrap">
                <span class="file-name" title="${fname}">${fname}</span>
                <span class="file-sub mono">${sizeStr}</span>
              </div>
            </div>
          `;
        }
      }

      const rightIconsHtml =
        item.kind === "link" || item.kind === "text"
          ? `<button class="icon-btn danger" type="button" data-action="remove" data-id="${item.id}" title="Quitar del historial" aria-label="Quitar del historial">${ICONS.trash}</button>`
          : buildIconActionsHtml(item);

      card.innerHTML = `
        <div class="card-meta-row">
          <span class="dir-badge ${item.direction}">${dirLabel}</span>
          <span>${metaRight}</span>
        </div>
        ${contentHtml}
        <div class="card-footer">
          ${leftFooterHtml}
          <div class="icon-actions">${rightIconsHtml}</div>
        </div>
      `;
      return card;
    }

    function buildRowNode(item) {
      const row = document.createElement("article");
      row.className = "item-row";
      row.dataset.id = item.id;

      const dirLabel = item.direction === "to_pc" ? "↓ PC" : "↑ Tel";
      let leadingHtml = `<div class="row-ico">${ICONS.file}</div>`;
      let mainHtml = "";
      let metaStr = formatTime(item.created_at);

      if (item.kind === "link") {
        leadingHtml = `<div class="row-ico" style="color:var(--cyan)">${ICONS.link}</div>`;
        const safeUrl = escapeHtml(item.content);
        mainHtml = `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer" title="${safeUrl}">${safeUrl}</a>`;
      } else if (item.kind === "text") {
        leadingHtml = `<div class="row-ico">${ICONS.text}</div>`;
        mainHtml = `<span title="${escapeHtml(item.content)}">${escapeHtml(item.content)}</span>`;
      } else if (item.kind === "file") {
        const fname = escapeHtml(item.filename || "Archivo");
        metaStr = `${formatSize(item.size_bytes)} · ${formatTime(item.created_at)}`;
        if (item.file_exists && isImageItem(item)) {
          leadingHtml = `<img class="row-thumb" src="${item.download_url}?inline=1" alt="${fname}" data-action="lightbox" data-id="${item.id}" title="Clic para ampliar" loading="lazy" />`;
          mainHtml = `<span style="cursor:zoom-in" data-action="lightbox" data-id="${item.id}" title="${fname}">${fname}</span>`;
        } else if (item.file_exists && isVideoItem(item)) {
          leadingHtml = `<div class="row-ico" style="cursor:zoom-in;color:var(--cyan)" data-action="lightbox" data-id="${item.id}" title="Reproducir">${ICONS.video}</div>`;
          mainHtml = `<span style="cursor:zoom-in" data-action="lightbox" data-id="${item.id}" title="${fname}">${fname}</span>`;
        } else if (isAudioItem(item)) {
          leadingHtml = `<div class="row-ico" style="color:var(--emerald)">${ICONS.audio}</div>`;
          mainHtml = `<span title="${fname}">${fname}</span>`;
        } else {
          leadingHtml = `<div class="row-ico">${ICONS.file}</div>`;
          mainHtml = `<span title="${fname}">${fname}</span>`;
        }
      }

      row.innerHTML = `
        ${leadingHtml}
        <span class="row-dir ${item.direction}">${dirLabel}</span>
        <div class="row-main">${mainHtml}</div>
        <span class="row-meta mono">${metaStr}</span>
        <div class="icon-actions">${buildIconActionsHtml(item)}</div>
      `;
      return row;
    }

    function renderItems() {
      updateDirectionCounts();
      if (!els.itemsList) return;

      const filtered = getFilteredItems();
      if (filtered.length === 0) {
        const msg =
          state.items.length === 0
            ? "Aún no hay transferencias. Envía un enlace, pega una imagen (Ctrl+V) o arrastra un archivo."
            : "No hay elementos que coincidan con tu búsqueda o filtros actuales.";
        els.itemsList.innerHTML = `<div class="empty-state">${msg}</div>`;
        return;
      }

      const groupOrder = ["Hoy", "Ayer", "Esta semana", "Anteriores"];
      const groups = new Map();
      for (const item of filtered) {
        const g = getChronologicalGroup(item.created_at);
        if (!groups.has(g)) groups.set(g, []);
        groups.get(g).push(item);
      }

      const fragment = document.createDocumentFragment();
      for (const label of groupOrder) {
        const list = groups.get(label);
        if (!list || list.length === 0) continue;

        const section = document.createElement("section");
        section.className = "date-group";

        const heading = document.createElement("div");
        heading.className = "date-heading";
        heading.innerHTML = `<span>${label}</span><span class="mono">(${list.length})</span>`;
        section.appendChild(heading);

        const container = document.createElement("div");
        container.className = "group-items";
        for (const item of list) {
          container.appendChild(state.viewMode === "list" ? buildRowNode(item) : buildCardNode(item));
        }
        section.appendChild(container);
        fragment.appendChild(section);
      }

      els.itemsList.innerHTML = "";
      els.itemsList.appendChild(fragment);
    }

    function upsertItem(item) {
      if (!item || !item.id) return;
      state.items = [item, ...state.items.filter((i) => i.id !== item.id)];
      renderItems();
    }

    // --- URL Detection in Text Composer ---
    function updateUrlDetection() {
      if (!els.textInput || !els.urlDetectedBadge) return;
      const val = els.textInput.value.trim();
      els.urlDetectedBadge.classList.toggle("visible", URL_REGEX.test(val));
    }

    // --- Staged Files Preview Queue ---
    function addFilesToStage(fileList) {
      const files = Array.from(fileList || []).filter((f) => f && f.size >= 0);
      if (files.length === 0) return;

      for (const file of files) {
        const id = `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
        const isImg = (file.type || "").startsWith("image/") || /\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(file.name);
        const previewUrl = isImg ? URL.createObjectURL(file) : null;
        state.stagedFiles.push({ id, file, previewUrl });
      }
      renderStagedFiles();
    }

    function revokeLater(url) {
      if (!url) return;
      setTimeout(() => {
        try {
          URL.revokeObjectURL(url);
        } catch {}
      }, 1000);
    }

    function removeStagedFile(id) {
      const idx = state.stagedFiles.findIndex((f) => f.id === id);
      if (idx === -1) return;
      const [removed] = state.stagedFiles.splice(idx, 1);
      renderStagedFiles();
      revokeLater(removed.previewUrl);
    }

    function clearStagedFiles() {
      const urls = state.stagedFiles.map((e) => e.previewUrl).filter(Boolean);
      state.stagedFiles = [];
      renderStagedFiles();
      urls.forEach(revokeLater);
    }

    function renderStagedFiles() {
      if (!els.stagedSection || !els.stagedList) return;
      if (state.stagedFiles.length === 0) {
        els.stagedSection.hidden = true;
        els.stagedList.innerHTML = "";
        return;
      }

      els.stagedSection.hidden = false;
      const totalBytes = state.stagedFiles.reduce((acc, f) => acc + (f.file.size || 0), 0);
      const count = state.stagedFiles.length;
      if (els.stagedSummary) {
        els.stagedSummary.textContent = `${count} ${count === 1 ? "archivo" : "archivos"} · ${formatSize(totalBytes)}`;
      }
      if (els.sendStagedBtn) {
        els.sendStagedBtn.textContent = `Enviar ${count} ${count === 1 ? "archivo" : "archivos"} al teléfono`;
        els.sendStagedBtn.disabled = state.uploadingStaged;
      }

      const frag = document.createDocumentFragment();
      for (const entry of state.stagedFiles) {
        const row = document.createElement("div");
        row.className = "staged-item";

        const thumbHtml = entry.previewUrl
          ? `<img class="staged-thumb" src="${entry.previewUrl}" alt="${escapeHtml(entry.file.name)}" />`
          : `<div class="staged-thumb">${
              (entry.file.type || "").startsWith("audio/")
                ? ICONS.audio
                : (entry.file.type || "").startsWith("video/")
                  ? ICONS.video
                  : ICONS.file
            }</div>`;

        row.innerHTML = `
          ${thumbHtml}
          <div class="staged-info">
            <span class="staged-name" title="${escapeHtml(entry.file.name)}">${escapeHtml(entry.file.name)}</span>
            <span class="staged-size mono">${formatSize(entry.file.size)}</span>
          </div>
          <button type="button" class="staged-remove" data-remove-staged="${entry.id}" title="Quitar de la cola" aria-label="Quitar archivo">✕</button>
        `;
        frag.appendChild(row);
      }

      els.stagedList.innerHTML = "";
      els.stagedList.appendChild(frag);
    }

    function uploadFileStreaming(file) {
      return new Promise((resolve) => {
        if (!file || !els.uploadQueue) {
          resolve(false);
          return;
        }
        const row = document.createElement("div");
        row.className = "upload-row";
        row.innerHTML = `
          <div class="upload-row-top">
            <span class="upload-name">${escapeHtml(file.name)} <span class="mono" style="color:var(--text-3)">(${formatSize(file.size)})</span></span>
            <span class="upload-pct mono">0%</span>
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
        xhr.setRequestHeader("X-Sender", encodeURIComponent(state.info?.hostname || "PC"));
        xhr.setRequestHeader("X-Direction", "to_phone");

        xhr.upload.onprogress = (evt) => {
          if (!evt.lengthComputable || evt.total <= 0) return;
          const pct = Math.min(100, Math.round((evt.loaded / evt.total) * 100));
          const elapsedSec = Math.max(0.05, (performance.now() - startedAt) / 1000);
          const mbps = (evt.loaded / (1024 * 1024) / elapsedSec).toFixed(1);
          if (pctEl) pctEl.textContent = `${pct}% · ${mbps} MB/s`;
          if (fillEl) fillEl.style.width = `${pct}%`;
        };

        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            if (fillEl) fillEl.style.width = "100%";
            if (pctEl) {
              pctEl.textContent = "100% · Listo ✓";
              pctEl.style.color = "var(--emerald)";
            }
            try {
              upsertItem(JSON.parse(xhr.responseText));
            } catch {
              loadHistory();
            }
            showToast(`Enviado al teléfono: ${file.name}`);
            setTimeout(() => row.remove(), 2200);
            resolve(true);
          } else {
            if (pctEl) {
              pctEl.textContent = `Error (${xhr.status})`;
              pctEl.style.color = "var(--danger)";
            }
            showToast(`Error subiendo ${file.name} (${xhr.status})`);
            resolve(false);
          }
        };

        xhr.onerror = () => {
          if (pctEl) {
            pctEl.textContent = "Error de red";
            pctEl.style.color = "var(--danger)";
          }
          showToast(`Error de conexión con ${file.name}`);
          resolve(false);
        };

        xhr.send(file);
      });
    }

    async function sendStagedFiles() {
      if (state.uploadingStaged || state.stagedFiles.length === 0) return;
      state.uploadingStaged = true;
      const batch = state.stagedFiles.slice();
      clearStagedFiles();
      try {
        for (const entry of batch) {
          await uploadFileStreaming(entry.file);
        }
      } finally {
        state.uploadingStaged = false;
        renderStagedFiles();
      }
    }

    // --- Text & Link Send ---
    async function sendTextToPhone() {
      if (state.sendingText || !els.textInput) return;
      const content = els.textInput.value.trim();
      if (!content) {
        if (els.textStatus) {
          els.textStatus.textContent = "Escribe o pega algo primero";
          els.textStatus.classList.add("error");
        }
        showToast("Escribe o pega un enlace o texto primero.");
        els.textInput.focus();
        return;
      }

      state.sendingText = true;
      if (els.sendTextBtn) els.sendTextBtn.disabled = true;
      if (els.textStatus) {
        els.textStatus.textContent = "Enviando…";
        els.textStatus.classList.remove("error");
      }

      try {
        const res = await fetchWithTimeout(
          "/api/pc-send/text",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content, sender: state.info?.hostname || "PC" }),
          },
          15000
        );
        if (!res.ok) {
          let detail = `HTTP ${res.status}`;
          try {
            const errBody = await res.json();
            if (errBody?.detail) detail = errBody.detail;
          } catch {}
          throw new Error(detail);
        }
        const created = await res.json();
        upsertItem(created);
        els.textInput.value = "";
        updateUrlDetection();
        if (els.textStatus) els.textStatus.textContent = "Enviado ✓";
        showToast(created.kind === "link" ? "Enlace enviado al teléfono" : "Texto enviado al teléfono");
        setTimeout(() => {
          if (els.textStatus && els.textStatus.textContent === "Enviado ✓") {
            els.textStatus.textContent = "";
          }
        }, 2200);
      } catch (err) {
        if (els.textStatus) {
          els.textStatus.textContent = `Error: ${err.message || "falló"}`;
          els.textStatus.classList.add("error");
        }
        showToast("No se pudo enviar al teléfono.");
      } finally {
        state.sendingText = false;
        if (els.sendTextBtn) els.sendTextBtn.disabled = false;
      }
    }

    // --- Lightbox Modal ---
    function openLightbox(item) {
      if (!item || !els.lightboxModal || !els.lightboxStage) return;
      const url = `${item.download_url}?inline=1`;
      if (els.lightboxTitle) els.lightboxTitle.textContent = item.filename || "Vista previa";
      if (els.lightboxSub) els.lightboxSub.textContent = `${formatSize(item.size_bytes)} · ${item.sender || ""}`;
      if (els.lightboxDownload) {
        els.lightboxDownload.href = item.download_url;
        els.lightboxDownload.setAttribute("download", item.filename || "archivo");
      }

      els.lightboxStage.innerHTML = "";
      if (isVideoItem(item)) {
        const video = document.createElement("video");
        video.src = url;
        video.controls = true;
        video.autoplay = true;
        els.lightboxStage.appendChild(video);
      } else {
        const img = document.createElement("img");
        img.src = url;
        img.alt = item.filename || "Imagen";
        els.lightboxStage.appendChild(img);
      }
      els.lightboxModal.classList.add("open");
    }

    function closeLightbox() {
      if (!els.lightboxModal || !els.lightboxStage) return;
      els.lightboxModal.classList.remove("open");
      els.lightboxStage.innerHTML = "";
    }

    // --- Confirm Clear History Modal ---
    function openConfirmClear() {
      if (state.items.length === 0) {
        showToast("El historial ya está vacío.");
        return;
      }
      if (els.confirmModal) els.confirmModal.classList.add("open");
    }

    function closeConfirmClear() {
      if (els.confirmModal) els.confirmModal.classList.remove("open");
    }

    async function clearAllHistory() {
      closeConfirmClear();
      const ids = state.items.map((i) => i.id);
      if (ids.length === 0) return;

      const batchSize = 8;
      for (let i = 0; i < ids.length; i += batchSize) {
        const slice = ids.slice(i, i + batchSize);
        await Promise.allSettled(
          slice.map((id) => fetchWithTimeout(`/api/items/${id}`, { method: "DELETE" }))
        );
      }
      state.items = [];
      renderItems();
      showToast("Historial limpiado (archivos intactos en disco)");
    }

    // --- Backend Bootstrap & SSE ---
    async function loadInfo() {
      try {
        const res = await fetchWithTimeout("/api/info", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        state.info = await res.json();
        if (els.deviceMeta) {
          els.deviceMeta.textContent = state.info.hostname || "PC Local";
          els.deviceMeta.title = `${state.info.hostname} · ${state.info.download_dir}`;
        }
        if (els.lanUrl) {
          els.lanUrl.textContent = `${state.info.ip}:${state.info.port}`;
        }
        if (els.autoCopyToggle) {
          els.autoCopyToggle.checked = Boolean(state.info.auto_copy_clipboard);
        }
      } catch (err) {
        if (els.deviceMeta) els.deviceMeta.textContent = "PC Local";
        console.warn("Error cargando /api/info:", err);
      }
    }

    async function loadHistory() {
      try {
        const res = await fetchWithTimeout("/api/history?limit=300", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        state.items = Array.isArray(data.items) ? data.items : [];
        renderItems();
      } catch (err) {
        console.warn("Error cargando /api/history:", err);
        if (els.itemsList && state.items.length === 0) {
          els.itemsList.innerHTML =
            '<div class="empty-state">No se pudo cargar el historial inicial. Puedes enviar links o archivos normalmente.</div>';
        }
      }
    }

    function closeSse() {
      if (state.sse) {
        try {
          state.sse.close();
        } catch {}
        state.sse = null;
      }
    }

    function connectSse() {
      closeSse();
      if (typeof EventSource === "undefined") {
        setConnectionStatus(true, "Listo");
        return;
      }
      const source = new EventSource("/api/events");
      state.sse = source;

      source.onopen = () => setConnectionStatus(true, "Conectado");
      source.addEventListener("connected", () => setConnectionStatus(true, "Conectado"));
      source.addEventListener("item_created", (evt) => {
        try {
          upsertItem(JSON.parse(evt.data));
        } catch {}
      });
      source.addEventListener("item_updated", (evt) => {
        try {
          const updated = JSON.parse(evt.data);
          state.items = state.items.map((i) => (i.id === updated.id ? updated : i));
          renderItems();
        } catch {}
      });
      source.addEventListener("item_removed", (evt) => {
        try {
          const { id } = JSON.parse(evt.data);
          state.items = state.items.filter((i) => i.id !== id);
          renderItems();
        } catch {}
      });
      source.addEventListener("settings_updated", (evt) => {
        try {
          const data = JSON.parse(evt.data);
          if (els.autoCopyToggle && typeof data.auto_copy_clipboard === "boolean") {
            els.autoCopyToggle.checked = data.auto_copy_clipboard;
          }
        } catch {}
      });
      source.onerror = () => setConnectionStatus(false, "Reconectando…");
    }

    // --- Event Bindings ---
    window.addEventListener("beforeunload", closeSse);
    window.addEventListener("pagehide", closeSse);

    // Prevent browser from opening dropped files anywhere outside dropzone
    ["dragover", "drop"].forEach((ev) => {
      window.addEventListener(ev, (e) => e.preventDefault());
    });

    // Global Ctrl+V support for screenshots, images, or files anywhere on the page
    window.addEventListener("paste", (e) => {
      const dt = e.clipboardData;
      if (!dt) return;

      const pastedFiles = [];
      if (dt.items && dt.items.length > 0) {
        for (const item of Array.from(dt.items)) {
          if (item.kind === "file") {
            const rawFile = item.getAsFile();
            if (!rawFile) continue;
            // Give pasted screenshots a unique readable filename if generic
            const needsName = !rawFile.name || rawFile.name === "image.png" || rawFile.name === "blob";
            if (needsName) {
              const ext = (rawFile.type && rawFile.type.split("/")[1]) || "png";
              const stamp = new Date().toISOString().replace(/[:.T-]/g, "").slice(0, 14);
              const named = new File([rawFile], `captura_${stamp}.${ext}`, {
                type: rawFile.type || "image/png",
              });
              pastedFiles.push(named);
            } else {
              pastedFiles.push(rawFile);
            }
          }
        }
      } else if (dt.files && dt.files.length > 0) {
        pastedFiles.push(...Array.from(dt.files));
      }

      if (pastedFiles.length > 0) {
        e.preventDefault();
        addFilesToStage(pastedFiles);
        showToast(
          pastedFiles.length === 1
            ? `Imagen/archivo añadido a la cola: ${pastedFiles[0].name}`
            : `${pastedFiles.length} archivos añadidos a la cola`
        );
      }
    });

    // Escape closes Lightbox or Confirm modal
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        closeLightbox();
        closeConfirmClear();
      }
    });

    if (els.textInput) {
      els.textInput.addEventListener("input", updateUrlDetection);
      els.textInput.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
          e.preventDefault();
          sendTextToPhone();
        }
      });
    }

    if (els.pasteBtn) {
      els.pasteBtn.addEventListener("click", async () => {
        try {
          const clipText = await navigator.clipboard.readText();
          if (clipText && els.textInput) {
            els.textInput.value = clipText;
            updateUrlDetection();
            els.textInput.focus();
            showToast("Pegado desde el portapapeles");
          } else {
            showToast("El portapapeles no contiene texto.");
          }
        } catch {
          showToast("Usa Ctrl+V para pegar (permiso de portapapeles restringido).");
          if (els.textInput) els.textInput.focus();
        }
      });
    }

    if (els.textForm) {
      els.textForm.addEventListener("submit", (e) => {
        e.preventDefault();
        sendTextToPhone();
      });
    }

    if (els.sendTextBtn) {
      els.sendTextBtn.addEventListener("click", (e) => {
        e.preventDefault();
        sendTextToPhone();
      });
    }

    // Native <label for="file-input"> handles mouse click natively; add keyboard & drag-drop
    if (els.dropzone) {
      els.dropzone.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          if (els.fileInput) els.fileInput.click();
        }
      });

      ["dragenter", "dragover"].forEach((ev) => {
        els.dropzone.addEventListener(ev, (e) => {
          e.preventDefault();
          e.stopPropagation();
          els.dropzone.classList.add("drag-over");
        });
      });

      ["dragleave", "drop"].forEach((ev) => {
        els.dropzone.addEventListener(ev, (e) => {
          e.preventDefault();
          e.stopPropagation();
          els.dropzone.classList.remove("drag-over");
        });
      });

      els.dropzone.addEventListener("drop", (e) => {
        addFilesToStage(e.dataTransfer?.files);
      });
    }

    if (els.fileInput) {
      els.fileInput.addEventListener("change", () => {
        addFilesToStage(els.fileInput.files);
        els.fileInput.value = "";
      });
    }

    if (els.stagedList) {
      els.stagedList.addEventListener("click", (e) => {
        const btn = e.target.closest("button[data-remove-staged]");
        if (!btn) return;
        removeStagedFile(btn.dataset.removeStaged);
      });
    }

    if (els.clearStagedBtn) {
      els.clearStagedBtn.addEventListener("click", clearStagedFiles);
    }

    if (els.sendStagedBtn) {
      els.sendStagedBtn.addEventListener("click", sendStagedFiles);
    }

    if (els.copyLanBtn) {
      els.copyLanBtn.addEventListener("click", async () => {
        const url = state.info?.lan_url || window.location.origin;
        try {
          await navigator.clipboard.writeText(url);
          showToast(`Copiado: ${url}`);
        } catch {
          showToast(url);
        }
      });
    }

    if (els.autoCopyToggle) {
      els.autoCopyToggle.addEventListener("change", async () => {
        try {
          await fetchWithTimeout("/api/settings", {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ auto_copy_clipboard: els.autoCopyToggle.checked }),
          });
        } catch {
          showToast("No se pudo guardar el ajuste.");
        }
      });
    }

    if (els.openDownloadsBtn) {
      els.openDownloadsBtn.addEventListener("click", async () => {
        try {
          await fetchWithTimeout("/api/open-downloads", { method: "POST" });
        } catch {
          showToast("No se pudo abrir la carpeta.");
        }
      });
    }

    if (els.searchInput) {
      els.searchInput.addEventListener("input", () => {
        state.search = els.searchInput.value || "";
        if (els.searchClearBtn) els.searchClearBtn.hidden = state.search.length === 0;
        renderItems();
      });
    }

    if (els.searchClearBtn) {
      els.searchClearBtn.addEventListener("click", () => {
        state.search = "";
        if (els.searchInput) {
          els.searchInput.value = "";
          els.searchInput.focus();
        }
        els.searchClearBtn.hidden = true;
        renderItems();
      });
    }

    if (els.viewCardsBtn) els.viewCardsBtn.addEventListener("click", () => applyViewMode("cards"));
    if (els.viewListBtn) els.viewListBtn.addEventListener("click", () => applyViewMode("list"));

    els.dirTabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        els.dirTabs.forEach((t) => t.classList.remove("active"));
        tab.classList.add("active");
        state.direction = tab.dataset.direction || "all";
        renderItems();
      });
    });

    els.typePills.forEach((pill) => {
      pill.addEventListener("click", () => {
        els.typePills.forEach((p) => p.classList.remove("active"));
        pill.classList.add("active");
        state.typeFilter = pill.dataset.type || "all";
        renderItems();
      });
    });

    if (els.clearHistoryBtn) els.clearHistoryBtn.addEventListener("click", openConfirmClear);
    if (els.confirmCancelBtn) els.confirmCancelBtn.addEventListener("click", closeConfirmClear);
    if (els.confirmAcceptBtn) els.confirmAcceptBtn.addEventListener("click", clearAllHistory);
    if (els.confirmModal) {
      els.confirmModal.addEventListener("click", (e) => {
        if (e.target === els.confirmModal) closeConfirmClear();
      });
    }

    if (els.lightboxClose) els.lightboxClose.addEventListener("click", closeLightbox);
    if (els.lightboxModal) {
      els.lightboxModal.addEventListener("click", (e) => {
        if (e.target === els.lightboxModal) closeLightbox();
      });
    }

    if (els.itemsList) {
      els.itemsList.addEventListener("click", async (e) => {
        const trigger = e.target.closest("[data-action]");
        if (!trigger) return;
        const { action, id } = trigger.dataset;
        const item = state.items.find((i) => i.id === id);
        if (!item) return;

        try {
          if (action === "lightbox") {
            openLightbox(item);
          } else if ((action === "copy" || action === "copy-chip") && item.content) {
            await navigator.clipboard.writeText(item.content);
            trigger.classList.add("copied");
            const originalHtml = trigger.innerHTML;
            trigger.innerHTML = action === "copy-chip" ? `${ICONS.check}<span>Copiado ✓</span>` : ICONS.check;
            showToast("Copiado al portapapeles");
            setTimeout(() => {
              trigger.classList.remove("copied");
              trigger.innerHTML = originalHtml;
            }, 1600);
          } else if (action === "open") {
            await fetchWithTimeout(`/api/items/${id}/open`, { method: "POST" });
          } else if (action === "reveal") {
            await fetchWithTimeout(`/api/items/${id}/reveal`, { method: "POST" });
          } else if (action === "remove") {
            const res = await fetchWithTimeout(`/api/items/${id}`, { method: "DELETE" });
            if (res.ok) {
              state.items = state.items.filter((i) => i.id !== id);
              renderItems();
              showToast("Registro quitado del historial");
            }
          }
        } catch {
          showToast("No se pudo ejecutar la acción.");
        }
      });

      els.itemsList.addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        const trigger = e.target.closest("[data-action='lightbox']");
        if (!trigger) return;
        e.preventDefault();
        const item = state.items.find((i) => i.id === trigger.dataset.id);
        if (item) openLightbox(item);
      });
    }

    applyViewMode(state.viewMode);
    Promise.allSettled([loadInfo(), loadHistory()]).finally(() => {
      connectSse();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
