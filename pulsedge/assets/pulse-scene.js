/* PulsEdge background scene.
 * A fixed canvas (#pulse-bg) behind the page. The page scrolls section by section (CSS scroll snap),
 * and each section has its own formation of lit voxel blocks, echoing the pixel-block logo:
 *   0 intro      crystal lattice          4 digest   funnel (most news filtered out)
 *   1 watchlist  blocks streaming inward  5 pricing  market grid of bars, clusters lit (Nifty 500)
 *   2 verdicts   three towers             6 join     the PulsEdge star
 *   3 how        four-step staircase
 * When the section changes, every block flies from where it is to its place in the next formation.
 * WebGL: Three.js + GSAP from cdnjs (fewer blocks on phones). No WebGL / Save-Data: a light Canvas2D version.
 * Colours come from the page's CSS tokens (--pur, --fg, --mute, --bg) and follow theme changes.
 * Also adds a slim section indicator on the right edge.
 */
(function () {
  "use strict";
  var canvas = document.getElementById("pulse-bg");
  if (!canvas) return;

  var root = document.documentElement;
  var reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  var saveData = !!(navigator.connection && navigator.connection.saveData);
  var CDN = "https://cdnjs.cloudflare.com/ajax/libs/";
  var LIBS = [CDN + "three.js/r128/three.min.js", CDN + "gsap/3.12.5/gsap.min.js"];
  var SECTIONS = [
    [".hero", "Intro"], ["#feed", "Watchlist"], ["#verdicts", "Verdicts"], ["#how", "How it works"],
    ["#digest", "Digest"], ["#pricing", "Pricing"], ["#join", "Early access"]
  ].map(function (s) { return { el: document.querySelector(s[0]), label: s[1] }; }).filter(function (s) { return s.el; });

  // ---------- shared helpers ----------
  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
  function smooth(t) { t = clamp(t, 0, 1); return t * t * (3 - 2 * t); }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function hexToRgb(s) {
    s = (s || "").trim();
    var m = s.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
    if (m) {
      var h = m[1].length === 3 ? m[1].replace(/(.)/g, "$1$1") : m[1];
      return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
    }
    m = s.match(/rgba?\(([^)]+)\)/);
    if (m) { var p = m[1].split(",").map(parseFloat); return [p[0], p[1], p[2]]; }
    return [124, 77, 255];
  }
  function readTheme() {
    var cs = getComputedStyle(root);
    var bg = hexToRgb(cs.getPropertyValue("--bg")), lum = (0.2126 * bg[0] + 0.7152 * bg[1] + 0.0722 * bg[2]) / 255;
    return { primary: hexToRgb(cs.getPropertyValue("--pur")), ink: hexToRgb(cs.getPropertyValue("--fg")), mute: hexToRgb(cs.getPropertyValue("--mute")), dark: lum < 0.5 };
  }
  function onThemeChange(fn) {
    new MutationObserver(fn).observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    var mq = matchMedia("(prefers-color-scheme: dark)");
    if (mq.addEventListener) mq.addEventListener("change", fn); else mq.addListener(fn);
  }
  function hasWebGL() {
    try { var c = document.createElement("canvas"); return !!(window.WebGLRenderingContext && (c.getContext("webgl") || c.getContext("experimental-webgl"))); }
    catch (e) { return false; }
  }
  function loadScript(src) {
    return new Promise(function (res, rej) {
      var s = document.createElement("script"); s.src = src; s.async = false; s.crossOrigin = "anonymous";
      s.onload = res; s.onerror = function () { rej(new Error(src)); };
      document.head.appendChild(s);
    });
  }

  // ---------- section tracking + right-edge indicator ----------
  var listeners = [], current = 0;
  function onSection(fn) { listeners.push(fn); }
  (function track() {
    if (!SECTIONS.length) return;
    var css = document.createElement("style");
    css.textContent =
      "#pulse-rail{position:fixed;right:max(14px,env(safe-area-inset-right,0px));top:50%;transform:translateY(-50%);z-index:4;display:flex;flex-direction:column;gap:12px;align-items:flex-end}" +
      "#pulse-rail button{display:flex;align-items:center;gap:10px;background:none;border:0;padding:4px 0;cursor:pointer;color:var(--mute);font:inherit;font-size:11px;letter-spacing:.08em;text-transform:uppercase}" +
      "#pulse-rail i{display:block;width:14px;height:2px;border-radius:2px;background:currentColor;opacity:.45;transition:width .4s,opacity .4s,background .4s}" +
      "#pulse-rail span{opacity:0;transform:translateX(6px);transition:opacity .3s,transform .3s;white-space:nowrap}" +
      "#pulse-rail button[aria-current=true]{color:var(--pur)}#pulse-rail button[aria-current=true] i{width:28px;opacity:1}" +
      "#pulse-rail button[aria-current=true] span,#pulse-rail button:hover span,#pulse-rail button:focus-visible span{opacity:1;transform:none}" +
      "@media (max-width:1200px){#pulse-rail span{display:none}}" +
      "@media (max-width:760px){#pulse-rail{right:max(3px,env(safe-area-inset-right,0px));gap:8px}#pulse-rail i{width:7px}#pulse-rail button[aria-current=true] i{width:12px}#pulse-rail button{padding:3px 0}}";
    document.head.appendChild(css);
    var rail = document.createElement("nav");
    rail.id = "pulse-rail"; rail.setAttribute("aria-label", "Page sections");
    SECTIONS.forEach(function (s, i) {
      var b = document.createElement("button"); b.type = "button";
      b.setAttribute("aria-label", "Go to " + s.label);
      var l = document.createElement("span"); l.textContent = s.label;
      b.append(l, document.createElement("i"));
      b.addEventListener("click", function () { s.el.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" }); });
      rail.appendChild(b);
    });
    document.body.appendChild(rail);
    function set(i) {
      if (i === current && rail.dataset.init) return;
      current = i; rail.dataset.init = "1";
      Array.prototype.forEach.call(rail.children, function (b, k) { b.setAttribute("aria-current", k === i ? "true" : "false"); });
      listeners.forEach(function (fn) { fn(i); });
    }
    // The section crossing the middle of the screen is the current one.
    function pick() {
      var mid = innerHeight * 0.5, best = 0;
      SECTIONS.forEach(function (s, i) { if (s.el.getBoundingClientRect().top <= mid) best = i; });
      set(best);
    }
    var ticking = false;
    addEventListener("scroll", function () { if (!ticking) { ticking = true; requestAnimationFrame(function () { ticking = false; pick(); }); } }, { passive: true });
    addEventListener("resize", pick);
    pick();
  })();

  // ---------- choose mode ----------
  if (!saveData && hasWebGL()) {
    LIBS.reduce(function (p, src) { return p.then(function () { return loadScript(src); }); }, Promise.resolve())
      .then(function () { try { startGL(); } catch (e) { startLite(); } })
      .catch(startLite);
  } else {
    startLite();
  }

  // =====================================================================
  // WebGL: lit voxel blocks (InstancedMesh), one formation per section
  // =====================================================================
  function startGL() {
    var THREE = window.THREE, gsap = window.gsap;
    var W = innerWidth, H = innerHeight, mobile = W < 768;
    var N = mobile ? 360 : 820, U = 0.2;                     // block count, block size
    var renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: !mobile, powerPreference: "default" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, mobile ? 1.75 : 1.5));
    renderer.setSize(W, H, false);
    renderer.setClearColor(0x000000, 0);

    var scene = new THREE.Scene();
    var camera = new THREE.PerspectiveCamera(mobile ? 50 : 36, W / H, 0.1, 100);
    var hemi = new THREE.HemisphereLight(0xffffff, 0x1a1825, 0.75);
    var key = new THREE.DirectionalLight(0xffffff, 0.95); key.position.set(5, 9, 7);
    var rim = new THREE.PointLight(0xffffff, 1.4, 40); rim.position.set(-7, -3, 6);
    scene.add(hemi, key, rim);

    var mat = new THREE.MeshStandardMaterial({ color: 0xffffff, metalness: 0.32, roughness: 0.36 });
    var mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), mat, N);
    mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    mesh.frustumCulled = false;
    scene.add(mesh);

    // ---- static formation data ----
    var i, j, k, x, y, z;
    var rnd = new Float32Array(N * 3);
    for (i = 0; i < N * 3; i++) rnd[i] = Math.random();

    // 0 crystal lattice: two shells of an octahedron |x|+|y|+|z| = R
    var lattice = [];
    [5, 3].forEach(function (R, shell) {
      for (x = -R; x <= R; x++) for (y = -R; y <= R; y++) for (z = -R; z <= R; z++)
        if (Math.abs(x) + Math.abs(y) + Math.abs(z) === R) lattice.push([x, y, z, shell ? 1 : 0.25]);
    });
    // 2 three towers (act / watch / ignore)
    var towers = [], TH = [12, 7, 3];
    TH.forEach(function (h, t) { for (y = 0; y < h; y++) for (x = 0; x < 3; x++) for (z = 0; z < 3; z++) towers.push([(t - 1) * 5.5 + x - 1, y, z - 1, t === 0 ? 1 : t === 1 ? 0.45 : 0.1]); });
    // 3 four-step staircase
    var stairs = [];
    for (k = 0; k < 4; k++) for (x = 0; x < 4; x++) for (z = 0; z < 4; z++) stairs.push([k * 5 - 7.5 + x, k * 2.2, z - 1.5, k]);
    // 4 funnel rings
    var funnel = [];
    for (j = 0; j < 8; j++) {
      var rr = 3.4 - j * 0.38, m = Math.max(4, Math.round(2 * Math.PI * rr / (U * 1.7)));
      for (k = 0; k < m; k++) funnel.push([j, rr, k / m * Math.PI * 2]);
    }
    // 5 market grid (columns), with lit clusters
    var GC = mobile ? 12 : 24, GR = mobile ? 10 : 12, grid = [];
    var clusters = [[0.22, 0.3], [0.7, 0.62], [0.45, 0.8], [0.85, 0.22]];
    for (x = 0; x < GC; x++) for (z = 0; z < GR; z++) {
      var gx = x / (GC - 1), gz = z / (GR - 1), hot = 0;
      clusters.forEach(function (c) { hot = Math.max(hot, Math.exp(-((gx - c[0]) * (gx - c[0]) + (gz - c[1]) * (gz - c[1])) / 0.012)); });
      grid.push([x - (GC - 1) / 2, z - (GR - 1) / 2, 0.25 + 0.5 * Math.random() * Math.random() + hot * 2.4, hot, Math.random() * 6.28]);
    }
    // 6 the PulsEdge star: six stepped arms, two blocks deep
    var star = [];
    for (j = 0; j < 6; j++) for (k = 0; k < 7; k++) for (z = 0; z < 2; z++) {
      var off = (k % 2) * 0.5 * (j % 2 ? -1 : 1), a = j * Math.PI / 3;
      var rx = k + 1.1, px = Math.cos(a) * rx - Math.sin(a) * off, py = Math.sin(a) * rx + Math.cos(a) * off;
      star.push([px, py, z - 0.5, 1 - k / 9]);
    }
    for (x = 0; x < 2; x++) for (y = 0; y < 2; y++) for (z = 0; z < 2; z++) star.push([x - 0.5, y - 0.5, z - 0.5, 1]);

    // where each formation sits on screen (desktop / phone)
    // Shapes sit in the empty part of each section so they never fight the text.
    var OFF = mobile
      ? [[0, 5.0, -4], [0, 0, -3], [0, 0.5, -4], [0, 0, -4], [0, 0, -3], [0, -0.5, -3], [0, -0.4, -2]]
      : [[4.1, 0, -2.5], [3.2, 0, -3], [4.6, 1.5, -3], [4.4, 1.9, -3], [4.7, -3.2, -3], [0, -2.4, -5], [0, -0.6, -3]];
    // How strongly the scene shows in each section: bold on the intro and the closing screen, quiet behind dense text.
    var ALPHA = mobile ? [0.8, 0.3, 0.32, 0.32, 0.3, 0.28, 0.85] : [0.85, 0.38, 0.7, 0.65, 0.6, 0.38, 0.9];

    // ---- formation: writes position, scale (sx, sy), highlight for block i at time t ----
    var o = { x: 0, y: 0, z: 0, s: 0, sy: 1, h: 0 };
    function formation(stage, idx, t, out) {
      var r0 = rnd[idx * 3], r1 = rnd[idx * 3 + 1], r2 = rnd[idx * 3 + 2], p, c, sn, cs;
      out.sy = 1; out.h = 0; out.s = U;
      if (stage === 0) {                       // crystal lattice, rotating
        p = lattice[idx % lattice.length];
        if (idx >= lattice.length) { out.s = 0; } else out.s = U * (mobile ? 1.45 : 1.7);
        var ay = t * 0.22, ax = 0.45 + Math.sin(t * 0.3) * 0.12, sc = U * (mobile ? 2.2 : 2.9);
        x = p[0] * sc; y = p[1] * sc; z = p[2] * sc;
        c = Math.cos(ay); sn = Math.sin(ay); var x1 = x * c + z * sn, z1 = -x * sn + z * c;
        c = Math.cos(ax); sn = Math.sin(ax); out.x = x1; out.y = y * c - z1 * sn; out.z = y * sn + z1 * c;
        out.h = p[3];
      } else if (stage === 1) {                // streams spiralling into one point
        var lane = idx % 7, f = (r0 + t * (0.05 + r1 * 0.05)) % 1, ang = lane / 7 * Math.PI * 2 + (1 - f) * 2.1 + r2 * 0.2;
        var rad = (mobile ? 5.5 : 8) * Math.pow(1 - f, 1.3);
        out.x = Math.cos(ang) * rad; out.y = Math.sin(ang) * rad * 0.55; out.z = -3.5 * (1 - f) + (r2 - 0.5) * 0.6;
        out.s = U * (0.35 + 0.75 * (1 - f)); out.h = f > 0.85 ? 1 : 0.25 + f * 0.5;
      } else if (stage === 2) {                // three towers
        p = towers[idx % towers.length]; if (idx >= towers.length) out.s = 0;
        var sw = mobile ? 0.55 : 1, ry = 0.55 + Math.sin(t * 0.25) * 0.18;
        x = p[0] * U * 1.08 * sw; y = (p[1] - 6) * U * 1.08; z = p[2] * U * 1.08;
        cs = Math.cos(ry); sn = Math.sin(ry); out.x = x * cs + z * sn; out.y = y; out.z = -x * sn + z * cs;
        out.h = p[3];
      } else if (stage === 3) {                // staircase; highlight walks up the steps
        p = stairs[idx % stairs.length]; if (idx >= stairs.length) out.s = 0;
        var sw3 = mobile ? 0.55 : 1;
        out.x = p[0] * U * 1.08 * sw3; out.y = (p[1] - 3.3) * U * 1.08; out.z = p[2] * U * 1.08;
        var step = Math.floor(t * 0.7) % 4; out.h = p[3] === step ? 1 : 0.2 + p[3] * 0.08;
      } else if (stage === 4) {                // funnel, rings counter-rotating; bottom rings lit
        p = funnel[idx % funnel.length]; if (idx >= funnel.length) out.s = 0;
        var sp = (p[0] % 2 ? -1 : 1) * (0.15 + p[0] * 0.03), aa = p[2] + t * sp, scl = mobile ? 0.7 : 0.66;
        out.x = Math.cos(aa) * p[1] * scl; out.z = Math.sin(aa) * p[1] * scl * 0.6; out.y = (2 - p[0] * 0.55) * scl;
        out.h = p[0] >= 6 ? 1 : 0.15;
      } else if (stage === 5) {                // market grid; heights breathe, clusters lit
        p = grid[idx % grid.length]; if (idx >= grid.length) out.s = 0;
        var hh = p[2] * (0.88 + 0.12 * Math.sin(t * 0.9 + p[4]));
        out.sy = hh / U; out.x = p[0] * U * 1.5; out.z = p[1] * U * 1.5; out.y = -1.6 + hh / 2;
        out.h = p[3];
      } else {                                 // PulsEdge star
        p = star[idx % star.length]; if (idx >= star.length) out.s = 0;
        var sc6 = U * (mobile ? 0.95 : 1.6), ry6 = t * 0.3, rx6 = 0.35;
        x = p[0] * sc6; y = p[1] * sc6; z = p[2] * sc6;
        cs = Math.cos(ry6); sn = Math.sin(ry6); var x6 = x * cs + z * sn, z6 = -x * sn + z * cs;
        cs = Math.cos(rx6); sn = Math.sin(rx6); out.x = x6; out.y = y * cs - z6 * sn; out.z = y * sn + z6 * cs;
        out.s = idx < star.length ? sc6 * 0.96 : 0; out.h = p[3];
      }
      var of = OFF[stage]; out.x += of[0]; out.y += of[1]; out.z += of[2];
      if (out.s === 0) { out.x = of[0] + (r0 - 0.5) * 2; out.y = of[1] + (r1 - 0.5) * 2; out.z = of[2] - 2; }
    }

    // camera per section (position, look-at)
    var CAM = mobile
      ? [[0, 0, 15, 0, 0.6, 0], [0, 0, 15, 0, 0, 0], [3, 2, 14, 0, 0, 0], [0, 1.5, 14, 0, 0, 0], [0, 2, 13, 0, 0, 0], [0, 6, 13, 0, -1.5, 0], [0, 0, 12, 0, 0.4, 0]]
      : [[0, 0, 14, 0, 0, 0], [0, 0, 13, 0, 0, 0], [1.6, 1.4, 13, 0.6, 0.2, 0], [-0.6, 1.2, 13, 0, 0.2, 0], [0.4, 0.6, 12.5, 0.4, 0, 0], [0, 4.2, 12, 0, -1.2, 0], [0, 0, 12, 0, 0.3, 0]];
    var fade = { a: 1 }, themeAlpha = 1;
    function setOpacity() { canvas.style.opacity = String(themeAlpha * fade.a); }
    var cam = { x: 0, y: 0, z: 14, lx: 0, ly: 0, lz: 0 };

    // ---- transition state ----
    var fromPos = new Float32Array(N * 3), fromS = new Float32Array(N), fromSy = new Float32Array(N), fromH = new Float32Array(N);
    var curPos = new Float32Array(N * 3), curS = new Float32Array(N), curSy = new Float32Array(N), curH = new Float32Array(N);
    var stage = 0, tr = { p: 1 }, time = 0;
    function goTo(s) {
      if (s === stage && tr.p >= 1) return;
      fromPos.set(curPos); fromS.set(curS); fromSy.set(curSy); fromH.set(curH);
      stage = s; tr.p = 0;
      gsap.killTweensOf(tr); gsap.killTweensOf(cam);
      var c = CAM[s], d = reduced ? 0 : 1.6;
      gsap.to(tr, { p: 1, duration: d, ease: "power3.inOut" });
      gsap.to(cam, { x: c[0], y: c[1], z: c[2], lx: c[3], ly: c[4], lz: c[5], duration: d, ease: "power3.inOut" });
      gsap.killTweensOf(fade);
      gsap.to(fade, { a: ALPHA[s], duration: d, ease: "power2.inOut", onUpdate: setOpacity });
    }

    // ---- colours ----
    var cPrim = new THREE.Color(), cInk = new THREE.Color(), cBase = new THREE.Color(), cTmp = new THREE.Color(), dark = true;
    function applyTheme() {
      var th = readTheme(); dark = th.dark;
      cPrim.setRGB(th.primary[0] / 255, th.primary[1] / 255, th.primary[2] / 255);
      cInk.setRGB(th.ink[0] / 255, th.ink[1] / 255, th.ink[2] / 255);
      // resting blocks: a muted mix of brand purple and ink; lit blocks: full brand purple
      cBase.copy(cPrim).lerp(cInk, dark ? 0.55 : 0.35);
      if (dark) cBase.multiplyScalar(0.55); else cBase.lerp(new THREE.Color(1, 1, 1), 0.35);
      rim.color.copy(cPrim);
      hemi.intensity = dark ? 0.65 : 0.95;
      themeAlpha = dark ? 1 : 0.75; setOpacity();
    }
    applyTheme();
    onThemeChange(applyTheme);

    // start fully formed in the current section, then follow section changes
    stage = current; var c0 = CAM[stage]; fade.a = ALPHA[stage]; setOpacity();
    cam.x = c0[0]; cam.y = c0[1]; cam.z = c0[2]; cam.lx = c0[3]; cam.ly = c0[4]; cam.lz = c0[5];
    for (i = 0; i < N; i++) { formation(stage, i, 0, o); curPos[i * 3] = o.x; curPos[i * 3 + 1] = o.y; curPos[i * 3 + 2] = o.z; curS[i] = o.s; curSy[i] = o.sy; curH[i] = o.h; }
    onSection(goTo);

    var mx = 0, my = 0, px = 0, py = 0;
    if (!reduced && !mobile) addEventListener("pointermove", function (e) { mx = e.clientX / innerWidth - 0.5; my = e.clientY / innerHeight - 0.5; }, { passive: true });
    var resizeT;
    addEventListener("resize", function () {
      clearTimeout(resizeT);
      resizeT = setTimeout(function () { W = innerWidth; H = innerHeight; renderer.setSize(W, H, false); camera.aspect = W / H; camera.updateProjectionMatrix(); }, 150);
    });

    var dummy = new THREE.Object3D(), clock = new THREE.Clock();
    function frame() {
      var dt = Math.min(clock.getDelta(), 0.05);
      if (!reduced) time += dt;
      var P = tr.p;
      for (i = 0; i < N; i++) {
        formation(stage, i, time, o);
        var e = smooth(P * 1.5 - rnd[i * 3 + 2] * 0.5), lift = Math.sin(e * Math.PI) * (0.6 + rnd[i * 3] * 1.4);
        var x0 = lerp(fromPos[i * 3], o.x, e), y0 = lerp(fromPos[i * 3 + 1], o.y, e) + lift * 0.35, z0 = lerp(fromPos[i * 3 + 2], o.z, e) + lift;
        var s0 = lerp(fromS[i], o.s, e), sy0 = lerp(fromSy[i], o.sy, e), h0 = lerp(fromH[i], o.h, e);
        if (P >= 1) { x0 = o.x; y0 = o.y; z0 = o.z; s0 = o.s; sy0 = o.sy; h0 = o.h; }
        curPos[i * 3] = x0; curPos[i * 3 + 1] = y0; curPos[i * 3 + 2] = z0; curS[i] = s0; curSy[i] = sy0; curH[i] = h0;
        dummy.position.set(x0, y0, z0);
        dummy.rotation.set(lift * 0.9, lift * 1.3 * (rnd[i * 3 + 1] - 0.5), 0);   // blocks tumble mid-flight, settle square
        dummy.scale.set(s0, s0 * sy0, s0);
        dummy.updateMatrix();
        mesh.setMatrixAt(i, dummy.matrix);
        cTmp.copy(cBase).lerp(cPrim, clamp(h0, 0, 1));
        mesh.setColorAt(i, cTmp);
      }
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;

      px += (mx - px) * 0.05; py += (my - py) * 0.05;
      camera.position.set(cam.x + px * 1.2, cam.y - py * 0.8, cam.z);
      camera.lookAt(cam.lx, cam.ly, cam.lz);
      renderer.render(scene, camera);
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
    canvas.setAttribute("data-mode", "gl");
  }

  // =====================================================================
  // No WebGL / Save-Data: small Canvas2D squares that regroup per section
  // =====================================================================
  function startLite() {
    var ctx = canvas.getContext("2d");
    if (!ctx) return;
    var dpr = Math.min(window.devicePixelRatio || 1, 2), W, H, N = 120, theme = readTheme(), i;
    var from = [], to = [], cur = [], prog = 1, t0 = 0;
    function layout(s) {
      var pts = [], cols, n;
      for (n = 0; n < N; n++) {
        var x, y;
        if (s === 0) { var a = n / N * Math.PI * 2, r = (n % 2 ? 0.16 : 0.1) * Math.min(W, H); x = W * 0.5 + Math.cos(a * 4) * r * Math.cos(a); y = H * 0.3 + Math.sin(a) * r; }
        else if (s === 5) { cols = 12; x = W * (0.08 + 0.84 * (n % cols) / (cols - 1)); y = H * (0.25 + 0.5 * Math.floor(n / cols) / (N / cols)); }
        else if (s === 6) { var arm = n % 6, k = Math.floor(n / 6) % 10, aa = arm * Math.PI / 3; x = W * 0.5 + Math.cos(aa) * k * 9; y = H * 0.5 + Math.sin(aa) * k * 9; }
        else { cols = 3 + s; x = W * (0.2 + 0.6 * (n % cols) / (cols - 1)) + (Math.random() - 0.5) * 30; y = H * (0.25 + 0.5 * Math.random()); }
        pts.push([x, y]);
      }
      return pts;
    }
    function size() { W = innerWidth; H = innerHeight; canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); cur = to = layout(current); }
    size();
    addEventListener("resize", size);
    function draw(now) {
      if (!t0) t0 = now;
      prog = reduced ? 1 : clamp((now - t0) / 1200, 0, 1);
      var e = smooth(prog), col = theme.primary;
      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = "rgba(" + col[0] + "," + col[1] + "," + col[2] + "," + (theme.dark ? 0.45 : 0.3) + ")";
      for (i = 0; i < N; i++) {
        var f = from[i] || to[i], x = lerp(f[0], to[i][0], e), y = lerp(f[1], to[i][1], e);
        cur[i] = [x, y];
        ctx.fillRect(x - 2, y - 2, 4, 4);
      }
      if (prog < 1) requestAnimationFrame(draw);
    }
    onSection(function (s) { from = cur.slice(); to = layout(s); t0 = 0; requestAnimationFrame(draw); });
    onThemeChange(function () { theme = readTheme(); t0 = 0; requestAnimationFrame(draw); });
    requestAnimationFrame(draw);
    canvas.setAttribute("data-mode", "lite");
  }
})();
