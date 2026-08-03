// Click-to-enlarge for product screenshots. The native <dialog> supplies
// Esc-to-close, the backdrop, and a focus trap; we add a delegated open,
// keyboard activation, and lazy-load the larger *-full image (when present)
// only at open time so page load stays light.
//
// Inside the lightbox the shot has two states. "fit" scales it into the
// viewport; "actual" renders it at natural width in a scrolling stage, which
// is the only way a dense dashboard shot is legible on a phone. Panning and
// pinch are the browser's own scrolling -- no custom pointer maths -- and a
// short pull down from the top of the stage dismisses, because reaching a
// corner button one-handed is the other half of the clunkiness.
//
// Shared by every page that shows a screenshot. The dialog is built here
// rather than pasted into each page, so a page opts in with one script tag.
(function () {
  if (typeof HTMLDialogElement === "undefined") return;
  var dlg = document.getElementById("lightbox");
  if (!dlg) {
    dlg = document.createElement("dialog");
    dlg.id = "lightbox";
    dlg.className = "lightbox";
    dlg.setAttribute("aria-label", "Enlarged screenshot");
    dlg.dataset.zoom = "fit";
    dlg.dataset.zoomable = "true";
    dlg.innerHTML =
      '<div class="lightbox-controls">' +
      '<button type="button" class="lightbox-zoom" aria-pressed="false">Actual size</button>' +
      '<button type="button" class="lightbox-close" aria-label="Close enlarged screenshot">' +
      '<span aria-hidden="true">&times;</span></button></div>' +
      '<div class="lightbox-stage" tabindex="0" role="group" ' +
      'aria-label="Screenshot detail, scrollable"><img alt="" /></div>';
    document.body.appendChild(dlg);
  }
  if (typeof dlg.showModal !== "function") return;
  var big = dlg.querySelector("img");
  var stage = dlg.querySelector(".lightbox-stage");
  var zoomBtn = dlg.querySelector(".lightbox-zoom");
  var closeBtn = dlg.querySelector(".lightbox-close");
  var SEL = ".browser-frame img, .shot-strip img, .feature-visual img";
  var DISMISS_PX = 90; // pull-down distance that closes the lightbox
  var DRAG_MIN_PX = 6; // below this the gesture is still a tap
  var REPEAT_MS = 350; // swallows the second half of a double-tap
  var lastToggle = 0;
  var suppressClick = false;
  var dragY = 0;
  var dragging = false;
  var startX = 0;
  var startY = 0;

  Array.prototype.forEach.call(document.querySelectorAll(SEL), function (el) {
    el.classList.add("zoomable");
    el.tabIndex = 0;
    el.setAttribute("role", "button");
    el.setAttribute("aria-label", "Enlarge screenshot: " + (el.alt || "screenshot"));
  });

  function setZoom(actual) {
    dlg.dataset.zoom = actual ? "actual" : "fit";
    zoomBtn.setAttribute("aria-pressed", actual ? "true" : "false");
    zoomBtn.textContent = actual ? "Fit to screen" : "Actual size";
  }

  function fit() {
    setZoom(false);
    stage.scrollTop = 0;
    stage.scrollLeft = 0;
  }

  // Centre the stage on the point that was asked about, so tapping the right
  // edge of a wide shot lands there rather than back at the top left.
  function zoomInto(fx, fy) {
    setZoom(true);
    var maxX = stage.scrollWidth - stage.clientWidth;
    var maxY = stage.scrollHeight - stage.clientHeight;
    stage.scrollLeft = Math.max(0, Math.min(maxX, fx * stage.scrollWidth - stage.clientWidth / 2));
    stage.scrollTop = Math.max(0, Math.min(maxY, fy * stage.scrollHeight - stage.clientHeight / 2));
  }

  function ratio(value, min, size) {
    return size > 0 ? Math.min(1, Math.max(0, (value - min) / size)) : 0.5;
  }

  // A shot that already fits at natural size gets no toggle: there is
  // nothing to reveal, so the image keeps its older tap-to-dismiss role.
  function syncAffordance() {
    var fits = big.naturalWidth > 0 &&
      big.naturalWidth <= stage.clientWidth &&
      big.naturalHeight <= stage.clientHeight;
    dlg.dataset.zoomable = fits ? "false" : "true";
    if (!fits) return;
    if (document.activeElement === zoomBtn) closeBtn.focus();
    if (dlg.dataset.zoom === "actual") fit();
  }

  function open(el) {
    fit();
    dlg.dataset.zoomable = "true";
    big.src = el.dataset.full || el.currentSrc || el.src;
    big.alt = el.alt || "";
    dlg.showModal();
    if (big.complete) syncAffordance();
  }

  function endDrag() {
    dragging = false;
    dragY = 0;
    dlg.classList.remove("lb-dragging");
    stage.style.transform = "";
    stage.style.opacity = "";
  }

  big.addEventListener("load", syncAffordance);
  window.addEventListener("resize", function () { if (dlg.open) syncAffordance(); });

  document.addEventListener("click", function (e) {
    var el = e.target.closest ? e.target.closest(SEL) : null;
    if (el) { e.preventDefault(); open(el); return; }
    if (!dlg.open) return;
    if (e.target === big) {
      if (suppressClick) { suppressClick = false; return; }
      if (dlg.dataset.zoomable === "false") { dlg.close(); return; }
      // One toggle per gesture: a double-click or double-tap flips once and
      // the repeat click is swallowed instead of flipping straight back.
      var now = Date.now();
      if (e.detail > 1 || now - lastToggle < REPEAT_MS) return;
      lastToggle = now;
      if (dlg.dataset.zoom === "actual") { fit(); return; }
      var r = big.getBoundingClientRect();
      zoomInto(ratio(e.clientX, r.left, r.width), ratio(e.clientY, r.top, r.height));
      return;
    }
    if (e.target === dlg || e.target === stage) dlg.close();
  });

  document.addEventListener("keydown", function (e) {
    if ((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches(SEL)) {
      e.preventDefault(); open(e.target);
    }
  });

  zoomBtn.addEventListener("click", function () {
    lastToggle = Date.now();
    if (dlg.dataset.zoom === "actual") fit();
    else zoomInto(0.5, 0.5);
  });

  // Pull down to dismiss. Listeners stay passive so scrolling is never
  // delayed; the gesture only starts at the top of the stage, where there is
  // nothing left for the browser to scroll anyway.
  stage.addEventListener("touchstart", function (e) {
    suppressClick = false;
    dragging = e.touches.length === 1 && stage.scrollTop <= 0;
    dragY = 0;
    if (!dragging) return;
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
  }, { passive: true });

  stage.addEventListener("touchmove", function (e) {
    if (!dragging) return;
    if (e.touches.length !== 1 || stage.scrollTop > 0) { endDrag(); return; }
    var dy = e.touches[0].clientY - startY;
    var dx = e.touches[0].clientX - startX;
    if (dy < DRAG_MIN_PX || Math.abs(dx) > Math.abs(dy)) {
      if (dragY > 0) endDrag();
      return;
    }
    dragY = dy;
    dragging = true;
    suppressClick = true;
    dlg.classList.add("lb-dragging");
    stage.style.transform = "translateY(" + dy + "px)";
    stage.style.opacity = String(Math.max(0.4, 1 - dy / 420));
  }, { passive: true });

  stage.addEventListener("touchend", function () {
    var dismiss = dragY > DISMISS_PX;
    endDrag();
    if (dismiss) dlg.close();
  }, { passive: true });

  stage.addEventListener("touchcancel", endDrag, { passive: true });

  closeBtn.addEventListener("click", function () { dlg.close(); });
  dlg.addEventListener("close", function () {
    big.removeAttribute("src");
    suppressClick = false;
    endDrag();
    fit();
  });
})();
