/**
 * MJPDF frontend — routes to existing /api/* endpoints only
 */
(function () {
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

  let currentTool = null;
  let selectedFiles = [];
  let isProcessing = false;
  let activeFilter = "all";
  let objectUrl = null;

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(2) + " MB";
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function friendlyError(msg) {
    const m = String(msg || "");
    if (/password/i.test(m)) return "Incorrect password or the file could not be unlocked.";
    if (/file type|invalid/i.test(m)) return "This file type is not supported for this tool.";
    if (/too large/i.test(m)) return "The file is too large. Maximum size is " + MJPDF.MAX_FILE_SIZE_MB + " MB.";
    if (/empty/i.test(m)) return "The uploaded file appears to be empty.";
    if (/network|failed to fetch/i.test(m)) return "Network error. Check your connection and try again.";
    if (m.length > 180) return "Something went wrong while processing your file. Please try again.";
    return m || "Something went wrong. Please try again.";
  }

  function setMeta(title, desc) {
    document.title = title;
    let el = document.querySelector('meta[name="description"]');
    if (!el) {
      el = document.createElement("meta");
      el.name = "description";
      document.head.appendChild(el);
    }
    el.content = desc;
    let ogt = document.querySelector('meta[property="og:title"]');
    if (ogt) ogt.content = title;
    let ogd = document.querySelector('meta[property="og:description"]');
    if (ogd) ogd.content = desc;
  }

  function pathToolId() {
    const p = location.pathname.replace(/\/+$/, "") || "/";
    if (p === "/" || p === "/index.html") return null;
    const id = p.replace(/^\//, "");
    if (["about", "contact", "privacy", "terms", "api", "static"].includes(id)) return null;
    return MJPDF.getTool(id) ? id : null;
  }

  function goHome() {
    history.pushState({}, "", "/");
    render();
    try {
      window.scrollTo(0, 0);
      document.documentElement.scrollTop = 0;
      document.body.scrollTop = 0;
    } catch (_) {}
  }

  function goTool(id) {
    history.pushState({}, "", "/" + id);
    render();
    scrollToToolTop();
  }

  function scrollToToolTop() {
    // Mobile: force viewport to upload area (not footer)
    var run = function () {
      try {
        window.scrollTo(0, 0);
        document.documentElement.scrollTop = 0;
        document.body.scrollTop = 0;
      } catch (_) {}
      var target =
        document.getElementById("view-workspace") ||
        document.getElementById("tool-title") ||
        document.getElementById("dropzone");
      if (target && target.scrollIntoView) {
        try {
          target.scrollIntoView({ block: "start", inline: "nearest", behavior: "auto" });
        } catch (_) {
          try { target.scrollIntoView(true); } catch (__) {}
        }
      }
      // Keep focus off footer links
      var title = document.getElementById("tool-title");
      if (title && title.focus) {
        try { title.setAttribute("tabindex", "-1"); title.focus({ preventScroll: true }); } catch (_) {}
      }
    };
    run();
    requestAnimationFrame(run);
    setTimeout(run, 30);
    setTimeout(run, 120);
  }

function iconLabel(tool) {
    const c = "currentColor";
    const icons = {
      doc: `<svg viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="1.8"><path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4"/><path d="M9 12h6M9 16h6"/></svg>`,
      pdf: `<svg viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="1.8"><path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4"/><path d="M9 13h3a2 2 0 0 1 0 4H9v-4z"/></svg>`,
      slides: `<svg viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="1.8"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>`,
      compress: `<svg viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="1.8"><path d="M12 3v10"/><path d="M8 9l4 4 4-4"/><rect x="5" y="15" width="14" height="6" rx="1"/></svg>`,
      merge: `<svg viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="1.8"><path d="M8 6v6a4 4 0 0 0 4 4h0a4 4 0 0 0 4-4V6"/><path d="M8 6H5M19 6h-3"/><path d="M12 16v5"/></svg>`,
      split: `<svg viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="1.8"><path d="M12 3v8"/><path d="M12 11l-5 5M12 11l5 5"/><path d="M7 21H5M19 21h-2"/></svg>`,
      extract: `<svg viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="1.8"><rect x="4" y="3" width="12" height="16" rx="1"/><path d="M16 8h4v12H10v-3"/><path d="M14 14l3-3 3 3"/></svg>`,
      delete: `<svg viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="1.8"><path d="M5 7h14"/><path d="M9 7V5h6v2"/><path d="M8 7l1 12h6l1-12"/></svg>`,
      image: `<svg viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="1.8"><rect x="3" y="4" width="14" height="12" rx="1"/><path d="M3 13l3-3 3 2 3-4 3 4"/><path d="M17 12v8H7"/></svg>`,
      gallery: `<svg viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="1.8"><rect x="4" y="3" width="12" height="16" rx="1"/><path d="M16 8h3v12H9"/><circle cx="9" cy="9" r="1.5"/></svg>`,
      rotate: `<svg viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="1.8"><path d="M20 9a8 8 0 1 0 1 4"/><path d="M20 5v4h-4"/></svg>`,
      organize: `<svg viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="1.8"><path d="M8 8h12M8 12h12M8 16h12"/><path d="M4 8h1M4 12h1M4 16h1"/></svg>`,
      watermark: `<svg viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="1.8"><path d="M5 5h14v14H5z"/><path d="M8 15l2.5-7L13 15"/><path d="M9 12h3.5"/><path d="M15 15v-4"/></svg>`,
      lock: `<svg viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="1.8"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>`,
      unlock: `<svg viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="1.8"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 7.5-2"/></svg>`,
    };
    return icons[tool.icon] || icons.pdf;
  }

  function renderHeaderActive() {
    const path = location.pathname.replace(/\/+$/, "") || "/";
    $$(".nav a[data-nav]").forEach((a) => {
      const n = a.getAttribute("data-nav");
      a.classList.toggle("active", n === "home" ? path === "/" : path.includes(n));
    });
  }

  function renderHome() {
    setMeta(
      "MJPDF — Simple PDF Tools. Powerful Results.",
      "Convert, compress, merge, split and manage PDF files online with MJPDF. Fast, simple and free PDF tools."
    );
    const home = $("#view-home");
    const work = $("#view-workspace");
    if (home) home.classList.remove("hidden");
    if (work) work.classList.add("hidden");
    renderToolsGrid();
    renderHeaderActive();
  }


  let searchQuery = "";

  function renderToolsGrid() {
    const grid = $("#tools-grid");
    if (!grid) return;
    const q = (searchQuery || "").trim().toLowerCase();
    let list = MJPDF.TOOLS.filter(
      (t) => activeFilter === "all" || t.category === activeFilter
    );
    if (q) {
      list = list.filter((t) => {
        const hay = [t.name, t.short, t.desc, t.id, t.category, t.howTo || ""]
          .join(" ")
          .toLowerCase();
        return hay.includes(q);
      });
    }
    if (!list.length) {
      grid.innerHTML = `<div class="search-empty">No tools match your search. Try “compress”, “word”, or “merge”.</div>`;
      return;
    }
    grid.innerHTML = list
      .map(
        (t) => `
      <article class="tool-card" role="link" tabindex="0" data-tool="${t.id}" aria-label="${escapeHtml(t.name)}">
        <div class="tool-icon" aria-hidden="true">${iconLabel(t)}</div>
        <h3>${escapeHtml(t.name)}</h3>
        <p>${escapeHtml(t.short)}</p>
        <span class="btn btn-secondary">Use tool</span>
      </article>`
      )
      .join("");
    grid.querySelectorAll("[data-tool]").forEach((card) => {
      const open = () => goTool(card.getAttribute("data-tool"));
      card.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        open();
      });
      card.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open();
        }
      });
    });
  }


  function renderOption(opt) {
    if (opt.type === "radio") {
      return `<div class="field">
        <span class="field-label">${escapeHtml(opt.label)}</span>
        <div class="segmented" role="radiogroup" aria-label="${escapeHtml(opt.label)}">
          ${opt.choices
            .map(
              (c) => {
                const id = `${opt.name}-${c.value}`;
                const checked = c.value === opt.default ? "checked" : "";
                const hint = c.hint
                  ? `<span class="segment-hint">${escapeHtml(c.hint)}</span>`
                  : "";
                return `<label class="segment" for="${id}">
                  <input type="radio" id="${id}" name="${opt.name}" value="${c.value}" ${checked} />
                  <span class="segment-text"><strong>${escapeHtml(c.label)}</strong>${hint}</span>
                </label>`;
              }
            )
            .join("")}
        </div></div>`;
    }
    if (opt.type === "select") {
      return `<div class="field"><label>${escapeHtml(opt.label)}</label>
        <select name="${opt.name}">
          ${opt.choices
            .map(
              (c) =>
                `<option value="${c}" ${c === opt.default ? "selected" : ""}>${escapeHtml(
                  String(c)
                )}</option>`
            )
            .join("")}
        </select></div>`;
    }
    return `<div class="field"><label>${escapeHtml(opt.label)}${
      opt.required ? " *" : ""
    }</label>
      <input type="${opt.type || "text"}" name="${opt.name}"
        placeholder="${escapeHtml(opt.placeholder || "")}"
        value="${escapeHtml(opt.default || "")}"
        ${opt.min != null ? `min="${opt.min}"` : ""}
        ${opt.max != null ? `max="${opt.max}"` : ""}
        ${opt.step != null ? `step="${opt.step}"` : ""}
        ${opt.required ? "required" : ""} /></div>`;
  }

  function resetWorkspaceUI() {
    selectedFiles = [];
    isProcessing = false;
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl);
      objectUrl = null;
    }
    $("#stage-upload")?.classList.add("hidden");
    $("#stage-processing")?.classList.add("hidden");
    $("#stage-success")?.classList.add("hidden");
    $("#stage-error")?.classList.add("hidden");
    $("#stage-idle")?.classList.remove("hidden");
    updateFileList();
  }

  function renderTool(tool) {
    currentTool = tool;
    setMeta(tool.seoTitle, tool.seoDesc);
    const home = $("#view-home");
    const work = $("#view-workspace");
    if (home) home.classList.add("hidden");
    if (work) work.classList.remove("hidden");

    $("#tool-title").textContent = tool.name;
    $("#tool-desc").textContent = tool.desc;
    $("#drop-hint").textContent =
      "Maximum file size: " +
      MJPDF.MAX_FILE_SIZE_MB +
      " MB · Accepted: " +
      tool.accept +
      (tool.multiple ? " (multiple files)" : "");
    const input = $("#file-input");
    input.accept = tool.accept;
    input.multiple = !!tool.multiple;

    const opts = $("#options-panel");
    if (tool.options && tool.options.length) {
      opts.classList.remove("hidden");
      opts.innerHTML = tool.options.map(renderOption).join("");
    } else {
      opts.classList.add("hidden");
      opts.innerHTML = "";
    }

    $("#seo-how h2").textContent = "How to use " + tool.name;
    $("#seo-how p").textContent = tool.howTo;

    resetWorkspaceUI();
    renderHeaderActive();
    scrollToToolTop();
  }

  function updateFileList() {
    const list = $("#file-list");
    const actions = $("#actions");
    const drop = $("#dropzone");
    if (!selectedFiles.length) {
      list.classList.add("hidden");
      actions.classList.add("hidden");
      drop.classList.remove("hidden");
      return;
    }
    drop.classList.add("hidden");
    list.classList.remove("hidden");
    actions.classList.remove("hidden");
    list.innerHTML = selectedFiles
      .map(
        (f, i) => `<div class="file-item">
        <div class="meta">
          <div class="name">${escapeHtml(f.name)}</div>
          <div class="size">${formatSize(f.size)}</div>
        </div>
        <button type="button" class="remove" data-i="${i}" aria-label="Remove file">×</button>
      </div>`
      )
      .join("");
    list.querySelectorAll(".remove").forEach((btn) => {
      btn.addEventListener("click", () => {
        selectedFiles.splice(+btn.dataset.i, 1);
        updateFileList();
      });
    });
  }

  function addFiles(fileList) {
    const arr = Array.from(fileList || []);
    const valid = arr.filter((f) => f.size <= MJPDF.MAX_FILE_SIZE);
    if (valid.length < arr.length) {
      showError("One or more files exceed the " + MJPDF.MAX_FILE_SIZE_MB + " MB limit.");
    }
    if (!currentTool) return;
    if (!currentTool.multiple) selectedFiles = valid.slice(0, 1);
    else selectedFiles = selectedFiles.concat(valid);
    updateFileList();
  }

  function collectOptions() {
    const data = {};
    $$("#options-panel input, #options-panel select").forEach((el) => {
      if (el.type === "radio") {
        if (el.checked) data[el.name] = el.value;
      } else data[el.name] = el.value;
    });
    return data;
  }

  function showStage(name) {
    ["idle", "upload", "processing", "success", "error"].forEach((s) => {
      const el = $("#stage-" + s);
      if (el) el.classList.toggle("hidden", s !== name);
    });
  }

  function showError(msg) {
    showStage("error");
    $("#error-msg").textContent = friendlyError(msg);
    isProcessing = false;
  }

  function xhrUpload(url, formData, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", url);
      xhr.responseType = "blob";
      let lastLoaded = 0;
      let lastTime = Date.now();

      xhr.upload.onprogress = (e) => {
        if (!e.lengthComputable) return;
        const now = Date.now();
        const dt = (now - lastTime) / 1000;
        const speed = dt > 0 ? (e.loaded - lastLoaded) / dt : 0;
        lastLoaded = e.loaded;
        lastTime = now;
        const pct = Math.round((e.loaded / e.total) * 100);
        const remain = speed > 0 ? Math.ceil((e.total - e.loaded) / speed) : null;
        onProgress({
          loaded: e.loaded,
          total: e.total,
          percent: pct,
          speed,
          remain,
        });
      };

      xhr.onload = () => {
        const headers = {};
        const raw = xhr.getAllResponseHeaders().trim().split(/[\r\n]+/);
        raw.forEach((line) => {
          const p = line.split(": ");
          headers[p.shift().toLowerCase()] = p.join(": ");
        });
        resolve({
          status: xhr.status,
          blob: xhr.response,
          headers,
          contentType: xhr.getResponseHeader("content-type") || "",
          disposition: xhr.getResponseHeader("content-disposition") || "",
        });
      };
      xhr.onerror = () => reject(new Error("Network error"));
      xhr.send(formData);
    });
  }

  async function processFiles() {
    if (!currentTool || !selectedFiles.length || isProcessing) return;
    isProcessing = true;

    const opts = collectOptions();
    if (currentTool.options) {
      for (const opt of currentTool.options) {
        if (opt.required && !opts[opt.name]) {
          showError(opt.label + " is required.");
          isProcessing = false;
          return;
        }
      }
    }

    const form = new FormData();
    if (currentTool.multiple) selectedFiles.forEach((f) => form.append("files", f));
    else form.append("file", selectedFiles[0]);
    Object.entries(opts).forEach(([k, v]) => {
      if (v !== undefined && v !== "") form.append(k, v);
    });

    showStage("upload");
    $("#upload-status").textContent = "Uploading your file…";
    const fill = $("#upload-fill");
    fill.style.width = "0%";

    const url = "/api/" + currentTool.id;

    try {
      const result = await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", url);
        xhr.responseType = "blob";
        let lastLoaded = 0;
        let lastTime = performance.now();
        let uploadDone = false;

        xhr.upload.onprogress = (e) => {
          if (!e.lengthComputable) return;
          const now = performance.now();
          const dt = (now - lastTime) / 1000;
          const speed = dt > 0 ? (e.loaded - lastLoaded) / dt : 0;
          lastLoaded = e.loaded;
          lastTime = now;
          const pct = Math.min(99, Math.round((e.loaded / e.total) * 100));
          fill.style.width = pct + "%";
          $("#upload-pct").textContent = pct + "%";
          $("#upload-bytes").textContent =
            formatSize(e.loaded) + " / " + formatSize(e.total);
          $("#upload-speed").textContent =
            speed > 0 ? formatSize(speed) + "/s" : "—";
          const remain = speed > 0 ? Math.ceil((e.total - e.loaded) / speed) : null;
          $("#upload-eta").textContent =
            remain == null ? "—" : remain <= 1 ? "About 1 second" : remain + " seconds";
        };

        xhr.upload.onload = () => {
          uploadDone = true;
          fill.style.width = "100%";
          $("#upload-pct").textContent = "100%";
          $("#upload-status").textContent = "✓ Upload complete";
          // Move to processing while waiting for server
          setTimeout(() => {
            if (xhr.readyState !== 4) {
              showStage("processing");
              $("#process-msg").textContent =
                currentTool.processHint || "Processing your file…";
            }
          }, 200);
        };

        xhr.timeout = 300000; // 5 minutes — large PDFs / cold start
        xhr.onload = () => {
          resolve({
            status: xhr.status,
            blob: xhr.response,
            contentType: xhr.getResponseHeader("content-type") || "",
            disposition: xhr.getResponseHeader("content-disposition") || "",
            orig: xhr.getResponseHeader("X-Original-Size"),
            comp: xhr.getResponseHeader("X-Compressed-Size"),
            red: xhr.getResponseHeader("X-Reduction-Percent"),
          });
        };
        xhr.onerror = () =>
          reject(
            new Error(
              "Network error. The free server may be sleeping — wait 30s, refresh, and try again."
            )
          );
        xhr.ontimeout = () =>
          reject(
            new Error(
              "Request timed out. Try a smaller file, or retry once the server is warm."
            )
          );
        xhr.send(form);
      });

      if (result.status < 200 || result.status >= 300) {
        let msg = "Processing failed";
        if (result.status === 502 || result.status === 503 || result.status === 504) {
          msg =
            "Server is waking up or temporarily busy. Wait 20–40 seconds and try again.";
        } else if (result.status === 413) {
          msg = "File is too large for the server.";
        } else if (result.status === 0) {
          msg =
            "Connection lost. Refresh the page and try again (free servers sleep when idle).";
        } else {
          try {
            const text = await result.blob.text();
            try {
              const j = JSON.parse(text);
              let d = j.detail != null ? j.detail : j.message || j.error;
              if (Array.isArray(d)) d = d.map((x) => x.msg || JSON.stringify(x)).join("; ");
              if (d) msg = String(d);
            } catch (_) {
              // HTML / plain error body from proxy
              const plain = (text || "").replace(/<[^>]+>/g, " ").trim();
              if (plain && plain.length < 300) msg = plain;
              else if (result.status >= 500)
                msg =
                  "Server error (" +
                  result.status +
                  "). Wait a moment and retry. Large files may fail on free hosting.";
            }
          } catch (_) {}
        }
        throw new Error(msg);
      }
      // Empty success body is also a failure
      if (!result.blob || result.blob.size === 0) {
        throw new Error("Server returned an empty file. Please try again.");
      }

      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = URL.createObjectURL(result.blob);

      let filename = "download";
      const m = result.disposition.match(/filename="?([^";]+)"?/i);
      if (m) filename = m[1];

      showStage("success");
      const rows = [];
      rows.push(
        `<div><span>Original</span><strong>${escapeHtml(
          selectedFiles.map((f) => f.name).join(", ")
        )}</strong></div>`
      );
      rows.push(
        `<div><span>Output</span><strong>${escapeHtml(filename)}</strong></div>`
      );
      if (result.orig && result.comp) {
        rows.push(
          `<div><span>Size</span><strong>${formatSize(+result.orig)} → ${formatSize(
            +result.comp
          )} (${result.red}% smaller)</strong></div>`
        );
      } else {
        rows.push(
          `<div><span>Output size</span><strong>${formatSize(
            result.blob.size
          )}</strong></div>`
        );
      }
      $("#success-summary").innerHTML = rows.join("");
      const dl = $("#download-btn");
      dl.href = objectUrl;
      dl.download = filename;
    } catch (err) {
      showError(err.message || "Processing failed");
    } finally {
      isProcessing = false;
    }
  }

  function render() {
    const id = pathToolId();
    if (id) renderTool(MJPDF.getTool(id));
    else renderHome();
  }

  function bind() {
    $("#filters")?.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-filter]");
      if (!btn) return;
      activeFilter = btn.getAttribute("data-filter");
      $$("#filters .filter-btn").forEach((b) =>
        b.classList.toggle("active", b === btn)
      );
      renderToolsGrid();
    });

    const drop = $("#dropzone");
    const input = $("#file-input");
    drop?.addEventListener("click", () => input.click());
    drop?.addEventListener("dragover", (e) => {
      e.preventDefault();
      drop.classList.add("dragover");
    });
    drop?.addEventListener("dragleave", () => drop.classList.remove("dragover"));
    drop?.addEventListener("drop", (e) => {
      e.preventDefault();
      drop.classList.remove("dragover");
      addFiles(e.dataTransfer.files);
    });
    input?.addEventListener("change", () => {
      addFiles(input.files);
      input.value = "";
    });

    $("#process-btn")?.addEventListener("click", processFiles);
    $("#clear-btn")?.addEventListener("click", () => {
      selectedFiles = [];
      updateFileList();
      showStage("idle");
    });
    $("#again-btn")?.addEventListener("click", () => {
      resetWorkspaceUI();
    });
    $("#retry-btn")?.addEventListener("click", () => {
      showStage("idle");
      updateFileList();
    });
    $("#back-home")?.addEventListener("click", (e) => {
      e.preventDefault();
      goHome();
    });

    const search = $("#tool-search");
    const clearBtn = $("#search-clear");
    search?.addEventListener("input", () => {
      searchQuery = search.value || "";
      if (clearBtn) clearBtn.classList.toggle("hidden", !searchQuery);
      renderToolsGrid();
    });
    clearBtn?.addEventListener("click", () => {
      if (search) search.value = "";
      searchQuery = "";
      clearBtn.classList.add("hidden");
      renderToolsGrid();
    });

    const navToggle = $("#nav-toggle");
    const mainNav = $("#main-nav");
    navToggle?.addEventListener("click", () => {
      const open = mainNav?.classList.toggle("open");
      navToggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    mainNav?.querySelectorAll("a").forEach((a) => {
      a.addEventListener("click", () => {
        mainNav.classList.remove("open");
        navToggle?.setAttribute("aria-expanded", "false");
      });
    });

    window.addEventListener("popstate", render);
  }

  document.addEventListener("DOMContentLoaded", () => {
    bind();
    render();
  });
})();
