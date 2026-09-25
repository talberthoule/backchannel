// The analyst-lenses walkthrough (/analyst-lenses/): five scenes that build
// in timed beats. Markup carries the choreography:
//   data-b="k"        visible from beat k on
//   data-hl="k"       highlighted only during beat k
//   data-at="k cls"   gains class cls from beat k on (comma-separated rules)
// Without this script every scene element is visible and step 1 shows fully
// built, so the page reads complete at rest. With reduced motion, each step
// shows fully built and nothing auto-advances.
(function () {
  var player = document.getElementById("lw-player");
  if (!player) return;
  document.documentElement.classList.add("lw-js");

  var scenes = Array.prototype.slice.call(player.querySelectorAll(".lw-scene"));
  var chaps = Array.prototype.slice.call(player.querySelectorAll(".lw-chap"));
  var caption = document.getElementById("lw-caption");
  var playBtn = document.getElementById("lw-play");
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var plans = scenes.map(function (s) {
    return {
      beats: s.dataset.beats.split(" ").map(Number),
      dur: Number(s.dataset.dur),
      text: s.querySelector(".lw-scene-cap").textContent.trim(),
    };
  });

  var idx = 0, beat = -1, elapsed = 0, last = 0, playing = !reduce, ended = false, raf = null;

  function each(root, sel, fn) {
    Array.prototype.forEach.call(root.querySelectorAll(sel), fn);
  }

  function setBeat(s, b) {
    each(s, "[data-b]", function (el) { el.classList.toggle("on", Number(el.dataset.b) <= b); });
    each(s, "[data-hl]", function (el) { el.classList.toggle("hl", Number(el.dataset.hl) === b); });
    each(s, "[data-at]", function (el) {
      el.dataset.at.split(",").forEach(function (rule) {
        var parts = rule.trim().split(" ");
        el.classList.toggle(parts[1], b >= Number(parts[0]));
      });
    });
  }

  function fill(k, pct) {
    chaps[k].querySelector(".lw-fill").style.width = pct + "%";
  }

  function label(text) {
    playBtn.textContent = text;
    playBtn.setAttribute("aria-label", text);
  }

  function show(i) {
    idx = Math.max(0, Math.min(scenes.length - 1, i));
    elapsed = 0;
    scenes.forEach(function (s, k) {
      var on = k === idx;
      s.classList.toggle("is-active", on);
      s.setAttribute("aria-hidden", on ? "false" : "true");
    });
    chaps.forEach(function (c, k) {
      c.classList.toggle("cur", k === idx);
      c.classList.toggle("done", k < idx);
      c.setAttribute("aria-current", k === idx ? "step" : "false");
      fill(k, k < idx ? 100 : 0);
    });
    caption.textContent = plans[idx].text;
    beat = reduce || !playing ? plans[idx].beats.length - 1 : 0;
    setBeat(scenes[idx], beat);
    if (reduce || !playing) fill(idx, 100);
  }

  function start() {
    playing = true;
    label("Pause");
    if (raf === null) {
      last = performance.now();
      raf = requestAnimationFrame(tick);
    }
  }

  function stop() {
    playing = false;
    if (raf !== null) { cancelAnimationFrame(raf); raf = null; }
    beat = plans[idx].beats.length - 1;
    setBeat(scenes[idx], beat);
    fill(idx, 100);
    label(ended ? "Replay" : "Play");
  }

  function tick(now) {
    raf = null;
    if (!playing) return;
    elapsed += now - last;
    last = now;
    var plan = plans[idx];
    var b = 0;
    plan.beats.forEach(function (t, k) { if (elapsed >= t) b = k; });
    if (b !== beat) { beat = b; setBeat(scenes[idx], beat); }
    fill(idx, Math.min(100, (elapsed / plan.dur) * 100));
    if (elapsed >= plan.dur) {
      if (idx < scenes.length - 1) {
        show(idx + 1);
      } else {
        ended = true;
        chaps[idx].classList.add("done");
        stop();
        return;
      }
    }
    raf = requestAnimationFrame(tick);
  }

  playBtn.addEventListener("click", function () {
    if (playing) { stop(); return; }
    var from = ended ? 0 : idx;
    ended = false;
    playing = true;
    show(from);
    start();
  });

  // Jumping keeps the play state; a running loop picks up the new step.
  function jump(i) {
    if (ended) { ended = false; label("Play"); }
    show(i);
  }
  document.getElementById("lw-prev").addEventListener("click", function () { jump(idx - 1); });
  document.getElementById("lw-next").addEventListener("click", function () { jump(idx + 1); });
  chaps.forEach(function (c) {
    c.addEventListener("click", function () { jump(Number(c.dataset.i)); });
  });
  player.addEventListener("keydown", function (e) {
    if (e.key === "ArrowRight") { e.preventDefault(); jump(idx + 1); }
    if (e.key === "ArrowLeft") { e.preventDefault(); jump(idx - 1); }
  });
  document.addEventListener("visibilitychange", function () {
    if (document.hidden && playing) stop();
  });

  // Start only once the player is on screen, so a reader who lands mid-page
  // does not arrive at step 3 of a walkthrough they never saw begin.
  // Until then step 1 rests fully built.
  playing = false;
  show(0);
  label("Play");
  if (reduce) return;
  function begin() {
    if (playing || ended || idx !== 0) return;
    playing = true;
    show(0);
    start();
  }
  if (!("IntersectionObserver" in window)) { begin(); return; }
  var seen = new IntersectionObserver(function (entries) {
    if (entries.some(function (e) { return e.isIntersecting; })) {
      seen.disconnect();
      begin();
    }
  }, { threshold: 0.35 });
  seen.observe(player);
})();
