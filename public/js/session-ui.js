/* ==========================================================================
   Taskit — session UI controller
   Presentation only: no network, no camera, no AI. app.js drives it through
   window.TaskitSession and listens for what the person does via .on(...).

   Coordinates for outlines/frames are NORMALIZED to the photo (0–1),
   origin top-left: { x, y, w, h }.
   ========================================================================== */
(function () {
  'use strict';

  const q = (key, root = document) => root.querySelector(`[data-tk="${key}"]`);
  const el = {
    photo: q('photo'), stage: q('photo-stage'), soft: q('photo-soft'), crisp: q('photo-crisp'),
    outlines: q('photo-outlines'), corners: q('photo-corners'), tag: q('photo-tag'),
    pill: q('photo-pill'), pillLead: q('photo-pill-lead'), pillText: q('photo-pill-text'),
    zoom: q('photo-zoom'), zoomPlus: q('zoom-plus'), closer: q('photo-closer'),
    full: q('photo-full'), fullIcon: q('full-icon'),
    panel: q('photo-panel'), hide: q('photo-hide'), show: q('photo-show'),
    stripThumb: q('strip-thumb'), stripTitle: q('strip-title'),
    log: q('log'), quick: q('quick'), form: q('form'), input: q('input'),
    gear: q('gear'), gearLabel: q('gear-label'), pause: q('pause'),
    dots: q('progress-dots'), progressLabel: q('progress-label'), progressShort: q('progress-short'),
    timeLabel: q('time-label'), timeShort: q('time-short'), timeFill: q('time-fill'), timeFillShort: q('time-fill-short')
  };

  const SESSION_MINUTES = 15;
  const CRISP_PAD = 0.022; // how far the un-blurred window extends past the outlines
  const ZOOM = 1.8;

  const listeners = {};
  const emit = (name, detail) => (listeners[name] || []).forEach((fn) => fn(detail));

  const state = { mode: 'focus', outlines: [], frame: null, zoomTo: null, closer: false, zoomed: false, title: '' };

  /* ---------------- Photo ---------------- */

  function setAspect(w, h) {
    if (!w || !h) return;
    el.photo.style.setProperty('--ar', `${w} / ${h}`);
    el.photo.style.setProperty('--ar-n', (w / h).toFixed(4));
    el.panel.dataset.orient = w < h ? 'portrait' : 'landscape'; // phones give the portrait photo more height
  }

  /** Swap the photo. Pass width/height if known; otherwise read from the image. */
  function setPhoto(src, opts = {}) {
    [el.soft, el.crisp, el.stripThumb].forEach((img) => { img.src = src; });
    el.tag.hidden = !opts.closeup;
    state.zoomed = false;
    if (opts.width && opts.height) setAspect(opts.width, opts.height);
    else el.crisp.addEventListener('load', () => setAspect(el.crisp.naturalWidth, el.crisp.naturalHeight), { once: true });
    render();
  }

  /** Highlight this step's items. outlines: [{x,y,w,h}] normalized. */
  function showStep({ title = '', pill, outlines = [] }) {
    Object.assign(state, { mode: 'focus', outlines, frame: null, zoomTo: null, closer: false, title, pill: pill ?? title });
    render();
  }

  /** Frame an area and invite a closer photo instead of outlining items. */
  function showCloser({ title = '', pill, frame }) {
    Object.assign(state, { mode: 'closer', outlines: [], frame, zoomTo: null, closer: false, title, pill: pill ?? title });
    render();
  }

  /**
   * The photo already has the step drawn on it (the backend's focus render), so draw nothing
   * on top. zoomTo {x,y,w,h} aims the zoom button; closer shows "Take a closer photo".
   */
  function showRendered({ title = '', pill, zoomTo = null, closer = false }) {
    Object.assign(state, { mode: 'rendered', outlines: [], frame: null, zoomTo, closer, title, pill: pill ?? title });
    render();
  }

  function unionBox(boxes) {
    if (!boxes.length) return null;
    let x1 = 1, y1 = 1, x2 = 0, y2 = 0;
    boxes.forEach((b) => { x1 = Math.min(x1, b.x); y1 = Math.min(y1, b.y); x2 = Math.max(x2, b.x + b.w); y2 = Math.max(y2, b.y + b.h); });
    return { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
  }
  const pct = (n) => `${(n * 100).toFixed(3)}%`;

  function render() {
    el.photo.dataset.mode = state.mode;
    el.photo.toggleAttribute('data-closer', state.closer);
    const box = state.mode === 'closer' ? state.frame : unionBox(state.outlines);

    // Un-blurred window
    if (box) {
      const pad = state.mode === 'closer' ? 0 : CRISP_PAD;
      const t = Math.max(0, box.y - pad), l = Math.max(0, box.x - pad);
      const r = Math.max(0, 1 - (box.x + box.w + pad)), b = Math.max(0, 1 - (box.y + box.h + pad));
      el.crisp.style.clipPath = `inset(${pct(t)} ${pct(r)} ${pct(b)} ${pct(l)} round 22px)`;
    } else {
      el.crisp.style.clipPath = 'inset(0 0 0 0 round 22px)'; // nothing to highlight: show the whole photo
    }

    // Outlines (reuse nodes so they glide between steps)
    const nodes = Array.from(el.outlines.children);
    state.outlines.forEach((o, i) => {
      const n = nodes[i] || el.outlines.appendChild(Object.assign(document.createElement('div'), { className: 'tk-photo__outline' }));
      Object.assign(n.style, { left: pct(o.x), top: pct(o.y), width: pct(o.w), height: pct(o.h), opacity: 1 });
    });
    nodes.slice(state.outlines.length).forEach((n) => n.remove());

    // Closer-photo corners
    if (state.frame) {
      const f = state.frame;
      const [tl, tr, bl, br] = el.corners.children;
      Object.assign(tl.style, { left: pct(f.x), top: pct(f.y) });
      Object.assign(tr.style, { left: pct(f.x + f.w), top: pct(f.y) });
      Object.assign(bl.style, { left: pct(f.x), top: pct(f.y + f.h) });
      Object.assign(br.style, { left: pct(f.x + f.w), top: pct(f.y + f.h) });
    }

    // Labels
    el.pill.hidden = !state.pill;
    el.pillLead.textContent = state.mode === 'closer' || state.closer ? 'Closer look' : 'This step';
    el.pillText.textContent = state.pill || '';
    el.stripTitle.textContent = state.title || '';

    // Zoom
    let view = { x: 0, y: 0, w: 1, h: 1 };
    const zoomBox = state.zoomTo || box;
    if (state.zoomed && zoomBox) {
      const s = 1 / ZOOM;
      view = {
        x: Math.min(1 - s, Math.max(0, zoomBox.x + zoomBox.w / 2 - s / 2)),
        y: Math.min(1 - s, Math.max(0, zoomBox.y + zoomBox.h / 2 - s / 2)),
        w: s, h: s
      };
    }
    el.stage.style.transform = `scale(${(1 / view.w).toFixed(4)}) translate(${pct(-view.x)}, ${pct(-view.y)})`;
    el.zoom.setAttribute('aria-pressed', String(state.zoomed));
    el.zoom.setAttribute('aria-label', state.zoomed ? 'Zoom out' : 'Zoom in on this step');
    el.zoomPlus.setAttribute('d', state.zoomed ? 'M11 11' : 'M11 8.5v5');
  }

  function toggleZoom(force) {
    state.zoomed = typeof force === 'boolean' ? force : !state.zoomed;
    render();
    emit('zoom', { zoomed: state.zoomed });
  }

  const FULL_IN = 'M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5';
  const FULL_OUT = 'M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5';

  /** Photo fills the screen (one button in, same button out). Pass a boolean to force. */
  function setFullscreen(force) {
    const on = typeof force === 'boolean' ? force : !el.panel.classList.contains('is-fullscreen');
    el.panel.classList.toggle('is-fullscreen', on);
    el.full.setAttribute('aria-pressed', String(on));
    el.full.setAttribute('aria-label', on ? 'Exit full screen' : 'Show photo full screen');
    el.fullIcon.setAttribute('d', on ? FULL_OUT : FULL_IN);
    emit('fullscreen', { fullscreen: on });
  }

  function setPhotoCollapsed(collapsed) {
    el.panel.classList.toggle('is-collapsed', collapsed);
    (collapsed ? el.show : el.hide).focus?.();
  }

  /* ---------------- Chat ---------------- */

  function append(node) {
    el.log.appendChild(node);
    requestAnimationFrame(() => { el.log.scrollTop = el.log.scrollHeight; });
    return node;
  }
  function bubble(cls, text) {
    const d = document.createElement('div');
    d.className = `tk-msg ${cls}`;
    d.textContent = text;
    return append(d);
  }
  const fromTemplate = (id) => document.getElementById(id).content.firstElementChild.cloneNode(true);

  const addCoach = (text) => bubble('tk-msg--coach', text);
  const addUser = (text) => bubble('tk-msg--user', text);

  function addUserPhoto(src, caption = 'Closer photo sent') {
    const d = document.createElement('div');
    d.className = 'tk-msg tk-msg--user tk-msg--photo';
    const img = document.createElement('img');
    img.src = src; img.alt = '';
    const span = document.createElement('span');
    span.textContent = caption;
    d.append(img, span);
    return append(d);
  }

  /** kind: 'step' | 'closer' */
  function addTask({ title, body, label, kind = 'step' }) {
    const n = fromTemplate('tk-tpl-task');
    n.querySelector('[data-slot="label"]').textContent = label || (kind === 'closer' ? 'A closer photo' : 'This step');
    n.querySelector('[data-slot="title"]').textContent = title;
    n.querySelector('[data-slot="body"]').textContent = body;
    n.querySelector(`[data-icon="${kind === 'closer' ? 'focus' : 'camera'}"]`).remove();
    return append(n);
  }

  function addCelebrate(text) {
    const n = fromTemplate('tk-tpl-celebrate');
    n.querySelector('[data-slot="text"]').textContent = text;
    return append(n);
  }

  const addSupport = () => append(fromTemplate('tk-tpl-support'));

  function clearLog() { el.log.replaceChildren(); }

  /** "Coach is typing" bubble; optional text for slower work like reading a new photo. */
  let typing = null;
  function showTyping(text) {
    hideTyping();
    typing = document.createElement('div');
    typing.className = 'tk-msg tk-msg--coach tk-typing';
    typing.setAttribute('role', 'status');
    typing.innerHTML = '<span class="tk-typing__dots" aria-hidden="true"><i></i><i></i><i></i></span>';
    const label = document.createElement('span');
    label.className = text ? 'tk-typing__text' : 'tk-sr-only';
    label.textContent = text || 'Your coach is writing…';
    typing.appendChild(label);
    return append(typing);
  }
  function hideTyping() { typing?.remove(); typing = null; }

  /** Disable quick replies and sending while a reply is on its way. */
  function setBusy(busy) {
    el.quick.querySelectorAll('button').forEach((b) => { b.disabled = busy; });
    el.form.querySelector('button[type="submit"]').disabled = busy;
    el.form.dataset.busy = busy ? 'true' : '';
  }

  const ICONS = {
    check: '<svg class="tk-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    camera: '<svg class="tk-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>'
  };

  /**
   * replies: [{ id, label, variant?: 'primary'|'secondary', icon?: 'check'|'camera', href? }]
   * Clicking emits 'reply' { id, label }. With href it renders a link (e.g. pause → done.html).
   */
  function setQuickReplies(replies = []) {
    el.quick.replaceChildren();
    replies.forEach((r) => {
      const node = document.createElement(r.href ? 'a' : 'button');
      if (r.href) node.href = r.href; else node.type = 'button';
      node.className = `tk-btn tk-btn--${r.variant || 'secondary'}`;
      node.innerHTML = r.icon && ICONS[r.icon] ? ICONS[r.icon] : '';
      node.append(document.createTextNode(r.label));
      node.addEventListener('click', (e) => emit('reply', { id: r.id, label: r.label, event: e }));
      el.quick.appendChild(node);
    });
  }

  /* ---------------- Progress & gear ---------------- */

  function setProgress({ stepsDone = 0, minutes = 0 }) {
    const shown = Math.min(stepsDone, 8);
    while (el.dots.children.length < shown) {
      const d = document.createElement('span');
      d.className = 'tk-progress__dot';
      d.innerHTML = '<svg class="tk-icon tk-icon--sm" style="width:14px;height:14px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
      el.dots.appendChild(d);
    }
    while (el.dots.children.length > shown) el.dots.lastElementChild.remove();

    el.progressLabel.textContent = stepsDone === 0 ? 'Your first step' : stepsDone === 1 ? '1 step done' : `${stepsDone} steps done`;
    el.progressShort.textContent = stepsDone === 0 ? 'First step' : `${stepsDone} done`;
    const m = Math.round(minutes);
    el.timeLabel.textContent = m < 1 ? 'Just getting started' : `About ${m} min`;
    el.timeShort.textContent = m < 1 ? 'just started' : `~${m} min`;
    const w = `${Math.min(100, (minutes / SESSION_MINUTES) * 100).toFixed(1)}%`;
    el.timeFill.style.width = w;
    el.timeFillShort.style.width = w;
  }

  /** label e.g. 'Gloves & mask'; pass null to hide the chip. */
  function setGear(label) {
    el.gear.hidden = !label;
    el.gearLabel.textContent = label || '';
  }

  /* ---------------- Wiring ---------------- */

  el.zoom.addEventListener('click', () => toggleZoom());
  el.stage.addEventListener('click', () => toggleZoom());
  el.full.addEventListener('click', () => setFullscreen());
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && el.panel.classList.contains('is-fullscreen')) setFullscreen(false);
  });
  el.hide.addEventListener('click', () => setPhotoCollapsed(true));
  el.show.addEventListener('click', () => setPhotoCollapsed(false));
  el.closer.addEventListener('click', () => emit('takePhoto', { source: 'photo-panel' }));
  el.pause.addEventListener('click', (e) => emit('pause', { event: e }));
  el.form.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = el.input.value.trim();
    if (!text || el.form.dataset.busy) return;
    el.input.value = '';
    emit('message', { text });
  });

  window.TaskitSession = {
    // photo
    setPhoto, showStep, showCloser, showRendered, toggleZoom, setFullscreen, setPhotoCollapsed,
    // chat
    addCoach, addUser, addUserPhoto, addTask, addCelebrate, addSupport, clearLog, setQuickReplies,
    showTyping, hideTyping, setBusy,
    // chrome
    setProgress, setGear,
    // events: 'reply' | 'message' | 'takePhoto' | 'pause' | 'zoom' | 'fullscreen'
    on(name, fn) { (listeners[name] = listeners[name] || []).push(fn); return () => this.off(name, fn); },
    off(name, fn) { listeners[name] = (listeners[name] || []).filter((f) => f !== fn); }
  };
})();
