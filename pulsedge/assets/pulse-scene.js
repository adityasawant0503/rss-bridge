/* PulsEdge background scene.
 * A fixed canvas (#pulse-bg) behind the page. Scroll drives three stages:
 *   hero      -> a rotating crystal behind the headline
 *   #feed     -> the crystal breaks into streams of data nodes flowing to one point
 *   #digest.. -> the nodes spread into a market grid where clusters light up
 * Desktop with WebGL: Three.js + GSAP ScrollTrigger (loaded from cdnjs on demand).
 * Phones / no WebGL: a light Canvas2D version of the same three stages, no libraries.
 * Colours come from the page's own CSS tokens (--pur, --fg, --mute, --bg) and follow theme changes.
 */
(function () {
  "use strict";
  var canvas = document.getElementById("pulse-bg");
  if (!canvas) return;

  var root = document.documentElement;
  var reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  var saveData = !!(navigator.connection && navigator.connection.saveData);
  var CDN = "https://cdnjs.cloudflare.com/ajax/libs/";
  var LIBS = [CDN + "three.js/r128/three.min.js", CDN + "gsap/3.12.5/gsap.min.js", CDN + "gsap/3.12.5/ScrollTrigger.min.js"];

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
    return {
      primary: hexToRgb(cs.getPropertyValue("--pur")),
      ink: hexToRgb(cs.getPropertyValue("--fg")),
      mute: hexToRgb(cs.getPropertyValue("--mute")),
      dark: lum < 0.5
    };
  }
  function onThemeChange(fn) {
    new MutationObserver(fn).observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    var mq = matchMedia("(prefers-color-scheme: dark)");
    if (mq.addEventListener) mq.addEventListener("change", fn); else mq.addListener(fn);
  }
  function sectionTop(el) { return el.getBoundingClientRect().top + window.scrollY; }
  // Scroll progress identical to the ScrollTrigger ranges used on desktop.
  function scrollStages() {
    var vh = innerHeight, y = window.scrollY;
    var feed = document.getElementById("feed"), dig = document.getElementById("digest"), pri = document.getElementById("pricing") || dig;
    var m1 = 0, m2 = 0;
    if (feed) {
      var s1 = sectionTop(feed) - vh, e1 = sectionTop(feed) + feed.offsetHeight / 2 - vh / 2;
      m1 = clamp((y - s1) / Math.max(1, e1 - s1), 0, 1);
    }
    if (dig && pri) {
      var s2 = sectionTop(dig) - vh, e2 = sectionTop(pri) + pri.offsetHeight / 2 - vh / 2;
      m2 = clamp((y - s2) / Math.max(1, e2 - s2), 0, 1);
    }
    return { m1: m1, m2: m2 };
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

  // ---------- choose mode ----------
  var wantGL = innerWidth >= 768 && !saveData && hasWebGL();
  if (wantGL) {
    LIBS.reduce(function (p, src) { return p.then(function () { return loadScript(src); }); }, Promise.resolve())
      .then(function () { try { startGL(); } catch (e) { startLite(); } })
      .catch(startLite);
  } else {
    startLite();
  }

  // =====================================================================
  // Desktop: Three.js + GSAP ScrollTrigger
  // =====================================================================
  function startGL() {
    var THREE = window.THREE, gsap = window.gsap, ScrollTrigger = window.ScrollTrigger;
    gsap.registerPlugin(ScrollTrigger);

    var W = innerWidth, H = innerHeight;
    var N = W * H > 1400000 ? 3600 : 2600;
    var renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: false, powerPreference: "default" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.setSize(W, H, false);
    renderer.setClearColor(0x000000, 0);

    var scene = new THREE.Scene();
    var camera = new THREE.PerspectiveCamera(45, W / H, 0.1, 100);
    camera.position.set(0, 0, 8);
    var world = new THREE.Group();
    scene.add(world);

    // --- A: crystal (icosahedron edges + faces) ---
    var R = 1.35;
    var ico = new THREE.IcosahedronGeometry(R, 0);
    var tri = ico.attributes.position.array;                 // non-indexed triangles
    var edges = new THREE.EdgesGeometry(ico).attributes.position.array;
    var posA = new Float32Array(N * 3), posB = new Float32Array(N * 3), posC = new Float32Array(N * 3), rnd = new Float32Array(N * 4);
    var i, k, t;
    var nEdge = Math.floor(N * 0.45), triCount = tri.length / 9, edgeCount = edges.length / 6;
    for (i = 0; i < N; i++) {
      var x, y, z;
      if (i < nEdge) {
        k = (i % edgeCount) * 6; t = Math.random();
        x = lerp(edges[k], edges[k + 3], t); y = lerp(edges[k + 1], edges[k + 4], t); z = lerp(edges[k + 2], edges[k + 5], t);
      } else {
        k = Math.floor(Math.random() * triCount) * 9;
        var u = Math.random(), v = Math.random(); if (u + v > 1) { u = 1 - u; v = 1 - v; }
        var w = 1 - u - v, depth = 0.55 + Math.random() * 0.45;       // fill toward the core: a data cluster
        x = (tri[k] * u + tri[k + 3] * v + tri[k + 6] * w) * depth;
        y = (tri[k + 1] * u + tri[k + 4] * v + tri[k + 7] * w) * depth;
        z = (tri[k + 2] * u + tri[k + 5] * v + tri[k + 8] * w) * depth;
      }
      posA[i * 3] = x; posA[i * 3 + 1] = y; posA[i * 3 + 2] = z;

      // --- B: stream parameters (angle, max radius, depth); position computed in the shader ---
      var streams = 12, s = i % streams;
      posB[i * 3] = (s / streams) * Math.PI * 2 + (Math.random() - 0.5) * 0.25;
      posB[i * 3 + 1] = 5 + Math.random() * 2;
      posB[i * 3 + 2] = -2.5 + Math.random() * 1.5;

      // rnd: stagger, stream phase, stream speed, size
      rnd[i * 4] = Math.random(); rnd[i * 4 + 1] = Math.random(); rnd[i * 4 + 2] = 0.05 + Math.random() * 0.06; rnd[i * 4 + 3] = 0.6 + Math.random() * 0.8;
    }
    // --- C: market grid ---
    var cols = Math.ceil(Math.sqrt(N * 1.75)), rows = Math.ceil(N / cols), gw = 15, gh = gw * rows / cols;
    for (i = 0; i < N; i++) {
      var cx = i % cols, cy = Math.floor(i / cols);
      posC[i * 3] = (cx / (cols - 1) - 0.5) * gw;
      posC[i * 3 + 1] = (cy / Math.max(1, rows - 1) - 0.5) * gh;
      posC[i * 3 + 2] = 0;
    }

    var geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(posA.slice(), 3));   // bounding only
    geo.setAttribute("posA", new THREE.BufferAttribute(posA, 3));
    geo.setAttribute("posB", new THREE.BufferAttribute(posB, 3));
    geo.setAttribute("posC", new THREE.BufferAttribute(posC, 3));
    geo.setAttribute("rnd", new THREE.BufferAttribute(rnd, 4));
    geo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 20);

    var clusters = [];
    for (i = 0; i < 6; i++) clusters.push(new THREE.Vector3((Math.random() - 0.5) * gw * 0.85, (Math.random() - 0.5) * gh * 0.8, Math.random() * 6.28));

    var uniforms = {
      uTime: { value: 0 }, uM1: { value: 0 }, uM2: { value: 0 },
      uRot: { value: new THREE.Vector2(0, 0) }, uOffA: { value: new THREE.Vector3(-2.3, 0.75, 0) }, uFocus: { value: new THREE.Vector3(0.6, 0, 0) },
      uSize: { value: 3.2 }, uPR: { value: renderer.getPixelRatio() },
      uPrimary: { value: new THREE.Color() }, uInk: { value: new THREE.Color() },
      uMixP: { value: 0.85 }, uOpacity: { value: 0.5 }, uGlow: { value: 1 },
      uClusters: { value: clusters }
    };
    var material = new THREE.ShaderMaterial({
      uniforms: uniforms, transparent: true, depthWrite: false,
      vertexShader: [
        "attribute vec3 posA; attribute vec3 posB; attribute vec3 posC; attribute vec4 rnd;",
        "uniform float uTime, uM1, uM2, uSize, uPR, uGlow; uniform vec2 uRot; uniform vec3 uOffA, uFocus; uniform vec3 uClusters[6];",
        "varying float vHot; varying float vEdge;",
        "float ease(float t){ t=clamp(t,0.,1.); return t*t*(3.-2.*t); }",
        "void main(){",
        "  float cy=cos(uRot.y), sy=sin(uRot.y), cx=cos(uRot.x), sx=sin(uRot.x);",
        "  vec3 a=posA; a=vec3(a.x*cy+a.z*sy, a.y, -a.x*sy+a.z*cy); a=vec3(a.x, a.y*cx-a.z*sx, a.y*sx+a.z*cx); a+=uOffA;",
        "  float t=fract(rnd.y+uTime*rnd.z);",
        "  float ang=posB.x+(1.-t)*2.6; float r=posB.y*pow(1.-t,1.25);",
        "  vec3 b=uFocus+vec3(cos(ang)*r, sin(ang)*r*0.62, posB.z*(1.-t));",
        "  float m1=ease(uM1*1.5-rnd.x*0.5), m2=ease(uM2*1.5-rnd.x*0.5);",
        "  vec3 c=posC; c.z+=sin(c.x*0.6+uTime*0.6)*0.12;",
        "  vec3 p=mix(mix(a,b,m1),c,m2);",
        "  float hot=0.;",
        "  for(int i=0;i<6;i++){ vec3 k=uClusters[i]; float d=distance(posC.xy,k.xy); hot=max(hot, smoothstep(1.5,0.,d)*(0.55+0.45*sin(uTime*1.4+k.z))); }",
        "  vHot=hot*m2*uGlow; vEdge=1.-m1;",
        "  vec4 mv=modelViewMatrix*vec4(p,1.);",
        "  gl_PointSize=uSize*uPR*rnd.w*(1.+vHot*1.3)*(8./-mv.z);",
        "  gl_Position=projectionMatrix*mv;",
        "}"
      ].join("\n"),
      fragmentShader: [
        "uniform vec3 uPrimary, uInk; uniform float uMixP, uOpacity;",
        "varying float vHot; varying float vEdge;",
        "void main(){",
        "  float d=length(gl_PointCoord-0.5); if(d>0.5) discard;",
        "  float a=smoothstep(0.5,0.12,d);",
        "  vec3 col=mix(uInk,uPrimary,clamp(uMixP+vHot,0.,1.));",
        "  gl_FragColor=vec4(col, a*uOpacity*(0.6+vHot*0.9));",
        "}"
      ].join("\n")
    });
    var points = new THREE.Points(geo, material);
    world.add(points);

    // faint crystal wireframe, fades as the crystal breaks apart
    var wire = new THREE.LineSegments(new THREE.EdgesGeometry(ico), new THREE.LineBasicMaterial({ transparent: true, opacity: 0.3, depthWrite: false }));
    world.add(wire);

    function applyTheme() {
      var th = readTheme();
      uniforms.uPrimary.value.setRGB(th.primary[0] / 255, th.primary[1] / 255, th.primary[2] / 255);
      var ink = th.dark ? th.ink : th.mute;
      uniforms.uInk.value.setRGB(ink[0] / 255, ink[1] / 255, ink[2] / 255);
      material.blending = th.dark ? THREE.AdditiveBlending : THREE.NormalBlending;
      material.needsUpdate = true;
      wire.material.color.copy(uniforms.uPrimary.value);
      state.cap = th.dark ? 0.55 : 0.42;
    }

    // --- scroll timeline ---
    var state = { m1: 0, m2: 0, dim: 1, cap: 0.5 };
    var feed = document.getElementById("feed"), dig = document.getElementById("digest"), pri = document.getElementById("pricing") || dig, how = document.getElementById("how") || feed;
    if (feed) gsap.to(state, { m1: 1, ease: "none", scrollTrigger: { trigger: feed, start: "top bottom", end: "center center", scrub: 1.2 } });
    if (dig) gsap.to(state, { m2: 1, ease: "none", scrollTrigger: { trigger: dig, start: "top bottom", endTrigger: pri, end: "center center", scrub: 1.2 } });
    if (feed && how) {
      gsap.timeline({ scrollTrigger: { trigger: feed, start: "top 70%", endTrigger: how, end: "bottom 30%", scrub: 1 } })
        .to(state, { dim: 0.75, duration: 1, ease: "none" }).to(state, { dim: 0.75, duration: 3 }).to(state, { dim: 1, duration: 1, ease: "none" });
    }
    applyTheme();
    onThemeChange(applyTheme);

    // --- pointer parallax ---
    var mx = 0, my = 0, px = 0, py = 0;
    if (!reduced) addEventListener("pointermove", function (e) { mx = e.clientX / innerWidth - 0.5; my = e.clientY / innerHeight - 0.5; }, { passive: true });

    var resizeT;
    addEventListener("resize", function () {
      clearTimeout(resizeT);
      resizeT = setTimeout(function () {
        W = innerWidth; H = innerHeight; renderer.setSize(W, H, false);
        camera.aspect = W / H; camera.updateProjectionMatrix(); layoutForWidth(); ScrollTrigger.refresh();
      }, 150);
    });
    function layoutForWidth() {
      // crystal sits behind the headline column; it centres on narrower desktops
      uniforms.uOffA.value.x = W >= 1100 ? -2.4 : -1.3;
    }
    layoutForWidth();
    addEventListener("load", function () { ScrollTrigger.refresh(); });

    var clock = new THREE.Clock(), time = 0, rotY = 0.6, rotX = 0.35;
    function frame() {
      var dt = Math.min(clock.getDelta(), 0.05);
      if (!reduced) { time += dt; rotY += dt * 0.18; rotX += dt * 0.07; }
      var m1 = state.m1, m2 = state.m2;
      uniforms.uTime.value = time; uniforms.uM1.value = m1; uniforms.uM2.value = m2;
      uniforms.uRot.value.set(rotX, rotY);
      uniforms.uMixP.value = lerp(lerp(0.85, 0.7, m1), 0.15, m2);
      uniforms.uOpacity.value = state.cap * state.dim;
      wire.material.opacity = 0.2 * (1 - smooth(m1 * 1.4)) * state.dim * (state.cap / 0.55);
      wire.visible = wire.material.opacity > 0.005;
      wire.position.copy(uniforms.uOffA.value);
      wire.rotation.set(rotX, rotY, 0, "XYZ");   // same order as the shader: Y first, then X

      // camera: hero -> slightly closer for the stream -> pulled back and tilted over the grid
      px += (mx - px) * 0.04; py += (my - py) * 0.04;
      camera.position.x = px * 0.6;
      camera.position.y = -py * 0.4 + lerp(0, 2.4, smooth(m2));
      camera.position.z = lerp(lerp(8, 7.2, smooth(m1)), 10.5, smooth(m2));
      camera.lookAt(0, lerp(0, -0.6, smooth(m2)), 0);
      world.rotation.x = lerp(0, -0.62, smooth(m2));

      renderer.render(scene, camera);
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
    canvas.setAttribute("data-mode", "gl");
  }

  // =====================================================================
  // Phones / no WebGL: Canvas2D, ~140 dots, same three stages
  // =====================================================================
  function startLite() {
    var ctx = canvas.getContext("2d");
    if (!ctx) return;
    var dpr = Math.min(window.devicePixelRatio || 1, 2), W, H;
    var N = 140, dots = [], theme = readTheme(), i;
    // unit icosahedron vertices for the crystal outline
    var g = (1 + Math.sqrt(5)) / 2, V = [[-1, g, 0], [1, g, 0], [-1, -g, 0], [1, -g, 0], [0, -1, g], [0, 1, g], [0, -1, -g], [0, 1, -g], [g, 0, -1], [g, 0, 1], [-g, 0, -1], [-g, 0, 1]];
    var E = [];
    for (i = 0; i < 12; i++) for (var j = i + 1; j < 12; j++) {
      var dx = V[i][0] - V[j][0], dy = V[i][1] - V[j][1], dz = V[i][2] - V[j][2];
      if (Math.abs(dx * dx + dy * dy + dz * dz - 4) < 0.01) E.push([i, j]);
    }
    for (i = 0; i < N; i++) dots.push({ e: E[i % E.length], t: Math.random(), ph: Math.random(), sp: 0.04 + Math.random() * 0.05, s: i % 10, r: 0.8 + Math.random() * 0.7 });
    var cols = 10, rows = Math.ceil(N / cols), clusters = [[0.25, 0.3], [0.7, 0.55], [0.4, 0.8]];

    function size() {
      W = innerWidth; H = innerHeight;
      canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    size();
    addEventListener("resize", function () { size(); kick(); });

    var time = 0, last = 0, rot = 0.6, until = 0, running = false;
    function draw(now) {
      var dt = last ? Math.min((now - last) / 1000, 0.1) : 0; last = now;
      if (!reduced) { time += dt; rot += dt * 0.25; }
      var st = scrollStages(), m1 = smooth(st.m1), m2 = smooth(st.m2);
      ctx.clearRect(0, 0, W, H);
      var cap = theme.dark ? 0.5 : 0.35, s = Math.min(W, H) * 0.2;
      var cxA = W * 0.5, cyA = H * 0.3, cr = Math.cos(rot), sr = Math.sin(rot), cr2 = Math.cos(rot * 0.4), sr2 = Math.sin(rot * 0.4);
      for (var n = 0; n < N; n++) {
        var d = dots[n];
        // A: point on an icosahedron edge, rotated and projected
        var a = V[d.e[0]], b = V[d.e[1]];
        var x = lerp(a[0], b[0], d.t), y = lerp(a[1], b[1], d.t), z = lerp(a[2], b[2], d.t);
        var x1 = x * cr + z * sr, z1 = -x * sr + z * cr, y1 = y * cr2 - z1 * sr2;
        var ax = cxA + x1 * s / 1.9, ay = cyA + y1 * s / 1.9;
        // B: stream spiralling into the focal point
        var ft = (d.ph + time * d.sp) % 1, ang = (d.s / 10) * 6.283 + (1 - ft) * 2.6, rad = Math.max(W, H) * 0.55 * Math.pow(1 - ft, 1.25);
        var bx = W * 0.5 + Math.cos(ang) * rad, by = H * 0.5 + Math.sin(ang) * rad * 0.7;
        // C: grid with pulsing clusters
        var gx = (n % cols + 0.5) / cols, gy = (Math.floor(n / cols) + 0.5) / rows, hot = 0;
        for (var c = 0; c < clusters.length; c++) {
          var dd = Math.hypot(gx - clusters[c][0], (gy - clusters[c][1]) * 0.8);
          hot = Math.max(hot, smooth(1 - dd / 0.18) * (0.6 + 0.4 * Math.sin(time * 1.5 + c * 2)));
        }
        hot *= m2;
        var px = lerp(lerp(ax, bx, m1), gx * W, m2), py = lerp(lerp(ay, by, m1), gy * H, m2);
        var col = hot > 0.05 || m2 < 0.5 ? theme.primary : (theme.dark ? theme.ink : theme.mute);
        ctx.fillStyle = "rgba(" + col[0] + "," + col[1] + "," + col[2] + "," + (cap * (0.65 + hot * 0.8)).toFixed(3) + ")";
        ctx.beginPath(); ctx.arc(px, py, d.r * (1.4 + hot * 1.6), 0, 6.283); ctx.fill();
      }
      if (!reduced && now < until) requestAnimationFrame(draw); else { running = false; last = 0; }
    }
    // animate for a few seconds after load and after each scroll/touch, then go idle
    function kick() {
      until = performance.now() + (reduced ? 0 : 6000);
      if (!running) { running = true; requestAnimationFrame(draw); }
    }
    addEventListener("scroll", kick, { passive: true });
    addEventListener("touchstart", kick, { passive: true });
    onThemeChange(function () { theme = readTheme(); kick(); });
    kick();
    canvas.setAttribute("data-mode", "lite");
  }
})();
