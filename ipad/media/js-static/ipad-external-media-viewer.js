(function () {
  "use strict";

  var CARD_TITLE = "external media";
  var urls = window.ipadDriveUrls;
  if (!urls) return;

  var root = document.getElementById("ipad-external-media-root");
  if (!root) return;

  var endpoint = root.getAttribute("data-endpoint");
  var placeId = root.getAttribute("data-resource-id");
  if (!endpoint || !placeId) return;

  var itemsByResourceId = {};
  var modal = null;
  var lastFocus = null;
  var enhanceTimer = null;

  function createModal() {
    if (modal) return modal;
    modal = document.createElement("div");
    modal.className = "ipad-drive-modal";
    modal.setAttribute("hidden", "hidden");
    modal.innerHTML =
      '<div class="ipad-drive-modal__backdrop" data-ipad-close="1"></div>' +
      '<div class="ipad-drive-modal__dialog" role="dialog" aria-modal="true" aria-labelledby="ipad-drive-modal-title">' +
      '<div class="ipad-drive-modal__header">' +
      '<h2 id="ipad-drive-modal-title" class="ipad-drive-modal__title"></h2>' +
      '<button type="button" class="ipad-drive-modal__close" data-ipad-close="1" aria-label="Close PDF preview">&times;</button>' +
      "</div>" +
      '<iframe class="ipad-drive-modal__frame" title="PDF preview" allow="fullscreen"></iframe>' +
      '<p class="ipad-drive-modal__note">If the preview is blank, the file may not be shared as anyone with the link.</p>' +
      "</div>";
    document.body.appendChild(modal);
    modal.addEventListener("click", function (event) {
      if (event.target && event.target.getAttribute("data-ipad-close") === "1") {
        closeModal();
      }
    });
    return modal;
  }

  function openModal(item) {
    var preview = urls.drivePreviewUrl(item.file_id);
    if (!preview) return;
    var node = createModal();
    lastFocus = document.activeElement;
    node.removeAttribute("hidden");
    var titleEl = node.querySelector("#ipad-drive-modal-title");
    titleEl.textContent = item.title || item.caption || "PDF";
    var frame = node.querySelector("iframe");
    frame.removeAttribute("srcdoc");
    frame.setAttribute("src", preview);
    frame.title = (item.title || item.caption || "PDF") + " preview";
    var closeBtn = node.querySelector(".ipad-drive-modal__close");
    if (closeBtn) closeBtn.focus();
    document.addEventListener("keydown", onKeydown);
  }

  function closeModal() {
    if (!modal || modal.hasAttribute("hidden")) return;
    var frame = modal.querySelector("iframe");
    if (frame) {
      frame.removeAttribute("src");
      frame.src = "about:blank";
    }
    modal.setAttribute("hidden", "hidden");
    document.removeEventListener("keydown", onKeydown);
    if (lastFocus && typeof lastFocus.focus === "function") {
      lastFocus.focus();
    }
  }

  function onKeydown(event) {
    if (event.key === "Escape" || event.key === "Esc") {
      event.preventDefault();
      closeModal();
    }
  }

  function isExternalMediaCard(section) {
    if (section.closest && section.closest(".report-related-resources")) {
      return false;
    }
    var titles = section.querySelectorAll(".rp-tile-title, dt");
    for (var i = 0; i < titles.length; i++) {
      var text = (titles[i].textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
      if (text === CARD_TITLE || text.indexOf(CARD_TITLE) !== -1) {
        return true;
      }
    }
    return false;
  }

  function resourceIdFromHref(href) {
    if (!href) return null;
    var match = String(href).match(/\/report\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i);
    return match ? match[1].toLowerCase() : null;
  }

  function addButtons(link, items) {
    if (link.getAttribute("data-ipad-pdf-bound") === "1") return;
    link.setAttribute("data-ipad-pdf-bound", "1");
    var wrap = document.createElement("span");
    wrap.className = "ipad-external-media-actions";
    items.forEach(function (item, index) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "btn btn-primary btn-sm ipad-view-pdf";
      button.textContent = items.length > 1 ? "View PDF " + (index + 1) : "View PDF";
      var labelTitle = item.caption || item.title || "document";
      button.setAttribute("aria-label", "View PDF: " + labelTitle);
      button.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        openModal(item);
      });
      wrap.appendChild(document.createTextNode(" "));
      wrap.appendChild(button);
    });
    if (link.parentNode) {
      link.parentNode.insertBefore(wrap, link.nextSibling);
    }
  }

  function enhance() {
    var sections = Array.prototype.slice.call(document.querySelectorAll(".rp-card-section"));
    sections.filter(isExternalMediaCard).forEach(function (section) {
      var links = section.querySelectorAll('a[href*="/report/"]');
      Array.prototype.forEach.call(links, function (link) {
        var resourceId = resourceIdFromHref(link.getAttribute("href"));
        var items = resourceId ? itemsByResourceId[resourceId] : null;
        if (!items || !items.length) return;
        addButtons(link, items);
      });
    });
  }

  function scheduleEnhance() {
    if (enhanceTimer) window.clearTimeout(enhanceTimer);
    enhanceTimer = window.setTimeout(enhance, 50);
  }

  function acceptItem(item) {
    if (!item || !urls.normalizeDriveFileId(item.file_id)) return false;
    if (item.storage_backend !== "google_drive") return false;
    if (item.mime_type !== "application/pdf") return false;
    return true;
  }

  function load() {
    window
      .fetch(endpoint, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (response) {
        if (!response.ok) return { items: [] };
        return response.json();
      })
      .then(function (payload) {
        var items = (payload && payload.items) || [];
        items.forEach(function (item) {
          if (!acceptItem(item)) return;
          var key = String(item.resource_id).toLowerCase();
          if (!itemsByResourceId[key]) itemsByResourceId[key] = [];
          itemsByResourceId[key].push(item);
        });
        enhance();
        var observer = new MutationObserver(scheduleEnhance);
        observer.observe(document.body, { childList: true, subtree: true });
      })
      .catch(function () {
        /* Leave the existing report untouched if the presentation API fails. */
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();
