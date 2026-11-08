const STRINGS = {
  en: {
    drop: "Drop images here or click to choose",
    dropActive: "Drop to show on the Frame",
    uploading: "Uploading {n} of {total} …",
    sending: "Sending to the Frame …",
    done: "Shown on the Frame",
    onFrame: "On the Frame",
    shown: "shown",
    empty: "No uploaded images on the Frame yet.",
    loading: "Asking the Frame …",
    refresh: "Refresh",
    notImage: "{name} is not an image",
    noEntity: "Set entity to a RemArt Frame media player",
    delete: "Delete from the Frame",
    confirmDelete: "Delete \"{name}\" from the Frame? This cannot be undone.",
    deleting: "Deleting …",
    deleted: "Deleted from the Frame",
  },
  de: {
    drop: "Bilder hierher ziehen oder klicken zum Auswählen",
    dropActive: "Loslassen, um es auf dem Frame zu zeigen",
    uploading: "Lade {n} von {total} hoch …",
    sending: "Sende an den Frame …",
    done: "Wird auf dem Frame gezeigt",
    onFrame: "Auf dem Frame",
    shown: "angezeigt",
    empty: "Noch keine hochgeladenen Bilder auf dem Frame.",
    loading: "Frage den Frame …",
    refresh: "Aktualisieren",
    notImage: "{name} ist kein Bild",
    noEntity: "entity muss ein RemArt-Frame-Mediaplayer sein",
    delete: "Vom Frame löschen",
    confirmDelete: "„{name}“ vom Frame löschen? Das lässt sich nicht rückgängig machen.",
    deleting: "Lösche …",
    deleted: "Vom Frame gelöscht",
  },
};

const STYLE = `
  ha-card { padding: 16px; }
  .header { display: flex; align-items: center; justify-content: space-between; }
  .name { font-size: 1.25em; font-weight: 500; }
  .drop {
    margin: 12px 0; padding: 24px 12px; text-align: center; cursor: pointer;
    border: 2px dashed var(--divider-color); border-radius: 12px;
    color: var(--secondary-text-color); transition: border-color .15s, background .15s;
  }
  .drop:hover, .drop.active {
    border-color: var(--primary-color); color: var(--primary-text-color);
    background: rgba(var(--rgb-primary-color, 3, 169, 244), .08);
  }
  .drop ha-icon { --mdc-icon-size: 36px; display: block; margin: 0 auto 6px; }
  .status { min-height: 1.4em; font-size: .9em; color: var(--secondary-text-color); }
  .status.error { color: var(--error-color); }
  .section {
    display: flex; align-items: center; justify-content: space-between;
    margin-top: 8px; font-weight: 500;
  }
  button.refresh {
    background: none; border: none; cursor: pointer; padding: 4px;
    color: var(--secondary-text-color); border-radius: 50%;
  }
  button.refresh:hover { color: var(--primary-text-color); }
  .grid {
    display: grid; gap: 8px; margin-top: 8px;
    grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  }
  .tile {
    position: relative; aspect-ratio: 16 / 9; border-radius: 8px; overflow: hidden;
    cursor: pointer; background: var(--secondary-background-color);
    outline: 3px solid transparent; outline-offset: -3px;
  }
  .tile:hover { outline-color: var(--divider-color); }
  .tile.current { outline-color: var(--primary-color); }
  .tile img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .tile .label {
    position: absolute; left: 0; right: 0; bottom: 0; padding: 2px 6px;
    font-size: .75em; color: #fff; background: rgba(0, 0, 0, .55);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .tile .badge {
    position: absolute; top: 4px; right: 4px; padding: 1px 6px; border-radius: 8px;
    font-size: .7em; color: var(--text-primary-color, #fff);
    background: var(--primary-color);
  }
  .tile button.delete {
    position: absolute; top: 4px; left: 4px; padding: 2px; border: none;
    border-radius: 50%; cursor: pointer; line-height: 0; opacity: 0;
    color: #fff; background: rgba(0, 0, 0, .55); transition: opacity .15s;
  }
  .tile button.delete ha-icon { --mdc-icon-size: 18px; }
  .tile:hover button.delete, .tile button.delete:focus-visible { opacity: 1; }
  .tile button.delete:hover { background: var(--error-color); }
  .tile { -webkit-touch-callout: none; user-select: none; -webkit-user-select: none; }
  .tile img { pointer-events: none; }
  /* Touch screens: long-press a tile to reveal its trash button. */
  @media (hover: none) {
    .tile button.delete { opacity: 0; pointer-events: none; }
    .tile.armed button.delete { opacity: 1; pointer-events: auto; padding: 6px; }
    .tile.armed button.delete ha-icon { --mdc-icon-size: 24px; }
  }
  .tile.armed { outline-color: var(--error-color); }
  .tile.busy { opacity: .5; pointer-events: none; }
  .hint { color: var(--secondary-text-color); font-size: .9em; margin-top: 8px; }
  input[type=file] { display: none; }
`;

const LONG_PRESS_MS = 500;
const CARD_BUILD = (() => {
  const entry = performance
    .getEntriesByType("resource")
    .find((e) => e.name.includes("remart-frame-card.js"));
  return entry ? new URL(entry.name).searchParams.get("v") || "?" : "?";
})();

// TEMP diagnostics: set "debug: true" in the card config.
const DEBUG_KEY = "remart-card-debug";
let debugInstances = 0;

class RemArtFrameCard extends HTMLElement {
  constructor() {
    super();
    this._instance = ++debugInstances + "-" + Math.random().toString(36).slice(2, 6);
    this._thumbs = new Map();
    this._items = null;
    this._busy = false;
    this._loading = false;
    this._reloadPending = false;
    this._lastShown = null;
  }

  static getStubConfig(hass) {
    const entity = Object.values(hass.entities || {}).find(
      (e) => e.platform === "remart" && e.entity_id.startsWith("media_player.")
    );
    return { entity: entity ? entity.entity_id : "" };
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("entity is required");
    }
    const changed = this._config && this._config.entity !== config.entity;
    this._config = config;
    this._renderDebug();
    if (changed) {
      this._items = null;
      if (this._hass) this._load();
    }
    this._renderHeader();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (!this.shadowRoot) {
      this._build();
      this._debug(`built, card ${CARD_BUILD}`);
    }
    this._renderHeader();
    // Reload when the Frame shows something new, e.g. from the media browser.
    const state = this._config && hass.states[this._config.entity];
    const shown = state
      ? [state.state, state.attributes.media_content_id, state.attributes.media_title].join("|")
      : null;
    const changed = shown !== this._lastShown;
    this._lastShown = shown;
    if (first || (changed && !this._busy)) this._load();
  }

  getCardSize() {
    return 6;
  }

  _t(key, vars = {}) {
    const lang = (this._hass && this._hass.language) || "en";
    const table = STRINGS[lang.split("-")[0]] || STRINGS.en;
    return (table[key] || STRINGS.en[key]).replace(/\{(\w+)\}/g, (_, k) => vars[k]);
  }

  _build() {
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="header"><span class="name"></span></div>
        <div class="drop" tabindex="0" role="button">
          <ha-icon icon="mdi:image-plus"></ha-icon>
          <span class="drop-text"></span>
        </div>
        <input type="file" accept="image/*" multiple>
        <div class="status"></div>
        <div class="section">
          <span class="section-title"></span>
          <button class="refresh"><ha-icon icon="mdi:refresh"></ha-icon></button>
        </div>
        <div class="grid"></div>
        <div class="hint"></div>
      </ha-card>`;
    const card = root.querySelector("ha-card");
    const drop = root.querySelector(".drop");
    const input = root.querySelector("input");
    // Android WebViews (e.g. the companion app) drop multi-selections from the
    // photo picker and report "cancel", so pick one image at a time there.
    input.multiple = !/Android/i.test(navigator.userAgent);

    drop.addEventListener("click", () => {
      this._debug(`drop click -> input.click() multiple=${input.multiple}`);
      input.click();
    });
    input.addEventListener("click", () => this._debug("input click"));
    input.addEventListener("cancel", () => this._debug("input cancel"));
    input.addEventListener("input", () =>
      this._debug(`input event: ${input.files ? input.files.length : "no"} files`)
    );
    document.addEventListener("visibilitychange", () =>
      this._debug(`visibility ${document.visibilityState}`)
    );
    drop.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") input.click();
    });
    input.addEventListener("change", () => {
      const picked = [...(input.files || [])];
      this._debug(
        `change: ${picked.length} files ` +
          picked.map((f) => `${f.name} type=${f.type || "-"} size=${f.size}`).join(", ")
      );
      this._upload(picked);
      input.value = "";
    });
    let depth = 0;
    card.addEventListener("dragenter", (ev) => {
      ev.preventDefault();
      depth += 1;
      this._setDropActive(true);
    });
    card.addEventListener("dragover", (ev) => {
      ev.preventDefault();
      ev.dataTransfer.dropEffect = "copy";
    });
    card.addEventListener("dragleave", () => {
      depth = Math.max(0, depth - 1);
      if (!depth) this._setDropActive(false);
    });
    card.addEventListener("drop", (ev) => {
      ev.preventDefault();
      depth = 0;
      this._setDropActive(false);
      this._handleDrop(ev.dataTransfer);
    });
    root.querySelector(".refresh").addEventListener("click", () => this._load());
  }

  _debug(message) {
    if (!this._config || !this._config.debug) return;
    const time = new Date().toLocaleTimeString();
    const lines = JSON.parse(localStorage.getItem(DEBUG_KEY) || "[]");
    lines.push(`${time} [${this._instance}${this.isConnected ? "" : " detached"}] ${message}`);
    localStorage.setItem(DEBUG_KEY, JSON.stringify(lines.slice(-30)));
    this._renderDebug();
  }

  _renderDebug() {
    const root = this.shadowRoot;
    if (!root || !this._config || !this._config.debug) return;
    let pre = root.querySelector("pre.debug");
    if (!pre) {
      pre = document.createElement("pre");
      pre.className = "debug";
      pre.style.cssText = "font-size:.7em;white-space:pre-wrap;max-height:240px;overflow:auto";
      pre.addEventListener("dblclick", () => {
        localStorage.removeItem(DEBUG_KEY);
        pre.textContent = "";
      });
      root.querySelector("ha-card").append(pre);
    }
    pre.textContent = JSON.parse(localStorage.getItem(DEBUG_KEY) || "[]").join("\n");
  }

  connectedCallback() {
    this._debug("connected");
  }

  disconnectedCallback() {
    this._debug("disconnected");
  }

  _renderHeader() {
    const root = this.shadowRoot;
    if (!root || !this._hass || !this._config) return;
    const state = this._hass.states[this._config.entity];
    root.querySelector(".name").textContent =
      this._config.title ||
      (state && state.attributes.friendly_name) ||
      this._config.entity;
    root.querySelector(".section-title").textContent = this._t("onFrame");
    root.querySelector(".refresh").title = this._t("refresh");
    if (!root.querySelector(".drop.active")) {
      root.querySelector(".drop-text").textContent = this._t("drop");
    }
  }

  _setDropActive(active) {
    const drop = this.shadowRoot.querySelector(".drop");
    drop.classList.toggle("active", active);
    drop.querySelector(".drop-text").textContent = this._t(
      active ? "dropActive" : "drop"
    );
  }

  _status(text, error = false) {
    const el = this.shadowRoot.querySelector(".status");
    el.textContent = text || "";
    el.classList.toggle("error", error);
  }

  _handleDrop(transfer) {
    const files = [...(transfer.files || [])];
    if (files.length) {
      this._upload(files);
      return;
    }
    // An image dragged from another browser tab arrives as a URL.
    const url = (transfer.getData("text/uri-list") || transfer.getData("text/plain"))
      .split("\n")
      .map((line) => line.trim())
      .find((line) => /^https?:\/\//.test(line));
    if (url) this._showUrl(url);
  }

  async _showUrl(url) {
    this._status(this._t("sending"));
    try {
      await this._play(url);
      this._status(this._t("done"));
    } catch (err) {
      this._status(err.message || String(err), true);
    }
  }

  async _upload(files) {
    this._debug(`upload: ${files.length} files, busy=${this._busy}`);
    if (this._busy || !files.length) return;
    this._busy = true;
    let failed = false;
    try {
      for (const [i, file] of files.entries()) {
        if (file.type && !file.type.startsWith("image/")) {
          this._status(this._t("notImage", { name: file.name }), true);
          failed = true;
          continue;
        }
        this._status(this._t("uploading", { n: i + 1, total: files.length }));
        const body = new FormData();
        body.append("file", file, file.name);
        const resp = await this._hass.fetchWithAuth(
          `/api/remart/upload/${encodeURIComponent(this._config.entity)}`,
          { method: "POST", body }
        );
        this._debug(`upload response ${resp.status}`);
        if (!resp.ok) {
          let message = `${resp.status} ${resp.statusText}`;
          try {
            message = (await resp.json()).message || message;
          } catch (_err) {
            // keep the status text
          }
          this._status(`${file.name}: ${message}`, true);
          failed = true;
        }
      }
      if (!failed) this._status(this._t("done"));
    } catch (err) {
      this._debug(`upload error: ${err.message || err}`);
      this._status(err.message || String(err), true);
    } finally {
      this._busy = false;
      this._load();
    }
  }

  _play(mediaId) {
    return this._hass.callService("media_player", "play_media", {
      entity_id: this._config.entity,
      media_content_id: mediaId,
      media_content_type: "image/jpeg",
    });
  }

  async _load() {
    if (!this._hass || !this._config || !this._config.entity) return;
    if (this._loading) {
      this._reloadPending = true;
      return;
    }
    this._loading = true;
    try {
      await this._fetchItems();
    } finally {
      this._loading = false;
    }
    if (this._reloadPending) {
      this._reloadPending = false;
      this._load();
    }
  }

  async _fetchItems() {
    const hint = this.shadowRoot.querySelector(".hint");
    if (!this._items) hint.textContent = this._t("loading");
    try {
      const result = await this._hass.callWS({
        type: "remart/frame_art",
        entity_id: this._config.entity,
      });
      this._items = result.items;
      hint.textContent = this._items.length ? "" : this._t("empty");
      this._renderGrid();
    } catch (err) {
      hint.textContent =
        err.code === "not_found" ? this._t("noEntity") : err.message || String(err);
    }
  }

  _renderGrid() {
    const grid = this.shadowRoot.querySelector(".grid");
    grid.replaceChildren(
      ...this._items.map((item) => {
        const tile = document.createElement("div");
        tile.className = "tile" + (item.current ? " current" : "");
        const label = [item.title, item.artist].filter(Boolean).join(" – ");
        tile.title = label || item.content_id;
        const img = document.createElement("img");
        img.alt = tile.title;
        img.loading = "lazy";
        this._thumbnail(item).then((src) => {
          if (src) img.src = src;
        });
        tile.append(img);
        if (label) {
          const caption = document.createElement("div");
          caption.className = "label";
          caption.textContent = label;
          tile.append(caption);
        }
        if (item.current) {
          const badge = document.createElement("div");
          badge.className = "badge";
          badge.textContent = this._t("shown");
          tile.append(badge);
        }
        const del = document.createElement("button");
        del.className = "delete";
        del.title = this._t("delete");
        del.setAttribute("aria-label", this._t("delete"));
        const icon = document.createElement("ha-icon");
        icon.icon = "mdi:delete-outline";
        del.append(icon);
        del.addEventListener("click", (ev) => {
          ev.stopPropagation();
          this._delete(item, tile, label || item.content_id);
        });
        tile.append(del);
        this._addLongPress(tile);
        tile.addEventListener("click", (ev) => {
          if (tile._longPressed) {
            tile._longPressed = false;
            return;
          }
          // A tap while some tile shows its trash button only dismisses it.
          if (this._disarm()) return;
          this._select(item, tile);
        });
        return tile;
      })
    );
  }

  async _select(item, tile) {
    if (item.current) return;
    tile.classList.add("busy");
    this._status(this._t("sending"));
    try {
      await this._play(item.media_content_id);
      for (const other of this._items) other.current = other === item;
      this._items.sort((a, b) => b.current - a.current);
      this._renderGrid();
      this._status(this._t("done"));
    } catch (err) {
      tile.classList.remove("busy");
      this._status(err.message || String(err), true);
    }
  }

  _addLongPress(tile) {
    let timer = null;
    let start = null;
    const cancel = () => {
      clearTimeout(timer);
      timer = null;
    };
    tile.addEventListener("pointerdown", (ev) => {
      tile._longPressed = false;
      if (ev.pointerType === "mouse") return;
      start = [ev.clientX, ev.clientY];
      cancel();
      timer = setTimeout(() => {
        timer = null;
        this._disarm();
        tile.classList.add("armed");
        tile._longPressed = true;
        if (navigator.vibrate) navigator.vibrate(20);
      }, LONG_PRESS_MS);
    });
    tile.addEventListener("pointermove", (ev) => {
      if (timer && start && Math.hypot(ev.clientX - start[0], ev.clientY - start[1]) > 10) {
        cancel();
      }
    });
    tile.addEventListener("pointerup", cancel);
    tile.addEventListener("pointercancel", cancel);
    tile.addEventListener("pointerleave", cancel);
    // Android opens a context menu on long-press otherwise.
    tile.addEventListener("contextmenu", (ev) => ev.preventDefault());
  }

  _disarm() {
    const armed = this.shadowRoot.querySelectorAll(".tile.armed");
    armed.forEach((tile) => tile.classList.remove("armed"));
    return armed.length > 0;
  }

  async _delete(item, tile, name) {
    if (!window.confirm(this._t("confirmDelete", { name }))) return;
    tile.classList.add("busy");
    this._status(this._t("deleting"));
    try {
      await this._hass.callWS({
        type: "remart/delete_art",
        entity_id: this._config.entity,
        content_id: item.content_id,
      });
      const src = await this._thumbs.get(item.content_id);
      if (src) URL.revokeObjectURL(src);
      this._thumbs.delete(item.content_id);
      this._items = this._items.filter((other) => other !== item);
      this.shadowRoot.querySelector(".hint").textContent = this._items.length
        ? ""
        : this._t("empty");
      this._renderGrid();
      this._status(this._t("deleted"));
    } catch (err) {
      tile.classList.remove("busy");
      this._status(err.message || String(err), true);
    }
  }

  _thumbnail(item) {
    if (!this._thumbs.has(item.content_id)) {
      const pending = this._hass
        .fetchWithAuth(item.thumbnail)
        .then((resp) => (resp.ok ? resp.blob() : null))
        .then((blob) => (blob ? URL.createObjectURL(blob) : null))
        .catch(() => null)
        .then((src) => {
          if (!src) this._thumbs.delete(item.content_id);
          return src;
        });
      this._thumbs.set(item.content_id, pending);
    }
    return this._thumbs.get(item.content_id);
  }
}

if (!customElements.get("remart-frame-card")) {
  customElements.define("remart-frame-card", RemArtFrameCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "remart-frame-card",
    name: "RemArt Frame",
    description:
      "Drop images to show them on the Frame, pick from or delete the images stored on it.",
    preview: false,
  });
}
