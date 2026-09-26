/* ==========================================================================
   Taskit — app controller
   Views: welcome → analyzing → session → done. Photos stay in the browser as
   object URLs; the backend keeps its copy in memory only, and we delete the
   session when the person finishes or leaves.

   Each backend reply is a SessionView (backend/app/schemas.py). render()
   turns it into coach bubbles, a task card, photo outlines and quick replies.
   ========================================================================== */
(function () {
  'use strict';

  const S = window.TaskitSession;
  const Camera = window.TaskitCamera;
  const Api = window.TaskitApi;
  const $ = (key) => document.querySelector(`[data-tk="${key}"]`);

  const MAX_SIDE = 2048; // long edge sent to the backend; plenty for detection, fast to upload

  /* ---------------- Views ---------------- */

  const views = document.querySelectorAll('[data-view]');
  function show(name) {
    views.forEach((v) => { v.hidden = v.dataset.view !== name; });
    if (name !== 'session') S.setFullscreen(false);
    window.scrollTo(0, 0);
  }

  /* ---------------- Photos ---------------- */

  /** Downscale + re-encode as JPEG (also bakes in EXIF rotation). Falls back to the original file. */
  async function prepare(file) {
    const url = URL.createObjectURL(file);
    try {
      const img = new Image();
      img.src = url;
      await img.decode();
      const scale = Math.min(1, MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(img.naturalWidth * scale);
      canvas.height = Math.round(img.naturalHeight * scale);
      canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.9));
      if (!blob) throw new Error('encode failed');
      URL.revokeObjectURL(url);
      return { blob, url: URL.createObjectURL(blob) };
    } catch {
      return { blob: file, url };
    }
  }

  /* ---------------- Copy helpers ---------------- */

  const listJoin = (xs) =>
    xs.length <= 1 ? (xs[0] || '') : xs.length === 2 ? `${xs[0]} and ${xs[1]}` : `${xs.slice(0, -1).join(', ')}, and ${xs.at(-1)}`;
  const stripArticle = (s) => s.replace(/^(the|a|an)\s+/i, '');
  const isCloser = (cur) => cur.step.action === 'take_closer_photo';
  const itemNames = (cur) => listJoin([...new Set(cur.items.map((i) => stripArticle(i.label.trim())))]);

  function stepTitle(cur) {
    if (isCloser(cur)) return cur.zone_label ? `The ${stripArticle(cur.zone_label)}` : 'This area';
    const names = itemNames(cur);
    if (names) return `The ${names}`;
    return cur.zone_label ? `Around the ${stripArticle(cur.zone_label)}` : 'This spot';
  }

  /** Short label for the pill on the photo; the task card carries the full title. */
  function stepPill(cur, title) {
    if (isCloser(cur)) return title;
    const names = [...new Set(cur.items.map((i) => stripArticle(i.label.trim())))];
    if (names.length <= 1 || title.length <= 36) return title;
    const first = names[0][0].toUpperCase() + names[0].slice(1);
    return `${first} and ${names.length - 1} more`;
  }

  const ACTION_BODY = {
    bag: 'Put the outlined things straight into a trash bag. No sorting needed.',
    recycle: 'Put the outlined things in recycling or the trash bag, whichever is easier.',
    group: 'Give each kind of thing one home:',
    set_aside: 'Move the outlined things to one side, out of the way. Nothing has to leave.',
    take_closer_photo: 'Could you take a closer photo of just this area? About an arm’s length away is perfect.'
  };

  function stepBody(cur) {
    const action = cur.step.action;
    if (action === 'take_closer_photo') return ACTION_BODY[action];
    const lead = cur.smaller ? 'Just the outlined ones for now. That’s the whole step. ' : '';
    const minutes = cur.smaller ? Math.min(cur.step.est_minutes, 2) : cur.step.est_minutes;
    const time = `About ${minutes} min.`;
    if (action === 'group' && cur.homes?.length) {
      // One line per kind of thing: where it goes, and the fallback if that home doesn't exist yet.
      const lines = [...new Map(cur.homes.map((h) => [h.kind, h])).values()].map((h) => {
        const what = listJoin(cur.homes.filter((x) => x.kind === h.kind).map((x) => stripArticle(x.label)));
        return `• ${what[0].toUpperCase() + what.slice(1)} → ${h.home} (or ${h.fallback})`;
      });
      const labels = cur.homes.map((h) => h.box_label).filter(Boolean);
      const tip = labels.length ? `\nNew box? Label it “${labels[0]}” with a marker, so more can go there later.` : '';
      return `${lead}${ACTION_BODY.group}\n${lines.join('\n')}${tip}\n${time}`;
    }
    return `${lead}${ACTION_BODY[action] || ''} ${time}`.trim();
  }

  function didLabel(cur) {
    const names = itemNames(cur) || 'things in this spot';
    switch (cur.step.action) {
      case 'take_closer_photo': return 'Took a closer photo';
      case 'bag': return `Bagged the ${names}`;
      case 'recycle': return `Cleared the ${names}`;
      case 'group': return `Gave the ${names} a home`;
      default: return `Moved the ${names} aside`;
    }
  }

  function gearLabel(assessment) {
    const ppe = (assessment?.required_ppe || []).map((p) => p.trim()).filter(Boolean);
    $('gear').title = ppe.length ? `Suggested for this space: ${ppe.join(', ')}` : '';
    if (!ppe.length) return null;
    const cap = (s) => s[0].toUpperCase() + s.slice(1);
    const two = `${cap(ppe[0])} & ${ppe[1] || ''}`;
    return ppe.length > 1 && two.length <= 28 ? two : cap(ppe[0]);
  }

  const COUNT_WORDS = ['Zero', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten'];

  function analyzeError(err) {
    switch (err?.status) {
      case 0: case 502: case 504: return 'I can’t reach your coach right now. Check your connection, then try again.';
      case 503: return 'Your coach is taking a short break. Please try again in a minute.';
      case 400: return 'I couldn’t open that photo. A regular photo from your camera works best.';
      case 422: return 'I couldn’t quite make out this photo. One area, in good light, works best.';
      default: return 'Something went wrong on my side. It’s not you. Please try again.';
    }
  }

  function turnError(err) {
    switch (err?.status) {
      case 0: case 502: case 504: return 'I couldn’t reach you just now. Could you try that again?';
      case 503: return 'I need a short breather. Could you try that again in a minute?';
      case 422: return 'I couldn’t quite make out that photo. Could you try another, in good light?';
      default: return 'Something went wrong on my side. Could you try that again?';
    }
  }

  /* ==========================================================================
     Welcome
     ========================================================================== */

  // Camera/picker calls happen synchronously inside the click so the browser allows them.
  $('take-photo').addEventListener('click', () => Camera.capture().then((file) => file && analyze(file)));
  $('choose-photo').addEventListener('click', () => Camera.pick().then((file) => file && analyze(file)));

  /* ==========================================================================
     Analyzing
     ========================================================================== */

  const LINES = [
    'There’s no rush. Take a slow breath while you wait.',
    'You don’t need to do anything right now.',
    'Whatever’s in the photo, we’ll start small.',
    'No judgment here. Every space has its own story.',
    'We’ll pick just one small thing to begin with.'
  ];
  const line = $('an-line');
  let lineTimer = null;
  let analysis = null; // { controller, photo, view }

  function stopLines() { clearInterval(lineTimer); lineTimer = null; line.classList.remove('is-fading'); }
  function startLines() {
    stopLines();
    let i = 0;
    line.textContent = LINES[0];
    lineTimer = setInterval(() => {
      line.classList.add('is-fading');
      setTimeout(() => { i = (i + 1) % LINES.length; line.textContent = LINES[i]; line.classList.remove('is-fading'); }, 600);
    }, 5000);
  }

  const LOOKING_HEADLINE = $('an-headline').textContent;  // the wording in index.html

  function setAnalyzing(stateName, text) {
    const ready = stateName === 'ready', failed = stateName === 'error';
    $('an-ready').hidden = !ready;
    $('an-retry').hidden = !failed;
    $('an-other').hidden = !failed;
    $('an-wait').hidden = ready || failed;
    if (stateName === 'looking') {
      $('an-headline').textContent = LOOKING_HEADLINE;
      startLines();
      return;
    }
    stopLines();
    $('an-headline').textContent = ready ? 'Ready when you are.' : 'Let’s try that again.';
    line.textContent = text;
    (ready ? $('an-ready') : $('an-retry')).focus();
  }

  async function analyze(file) {
    cancelAnalysis();
    runAnalysis(await prepare(file));
  }

  async function runAnalysis(photo) {
    const controller = new AbortController();
    analysis = { controller, photo, view: null };
    $('an-photo').src = photo.url;
    show('analyzing');
    setAnalyzing('looking');
    try {
      const view = await Api.startSession(photo.blob, { signal: controller.signal });
      if (analysis?.controller !== controller) { Api.endSession(view.session_id); return; }
      analysis.view = view;
      setAnalyzing('ready', view.current_step
        ? 'I found a good, small place to begin. Just one thing at a time.'
        : 'I’ve had a look. Let’s talk about what comes next.');
    } catch (err) {
      if (controller.signal.aborted) return;
      console.error('Analysis failed:', err);
      setAnalyzing('error', analyzeError(err));
    }
  }

  function cancelAnalysis({ keepPhoto = false } = {}) {
    if (!analysis) return;
    analysis.controller.abort();
    if (analysis.view) Api.endSession(analysis.view.session_id);
    if (!keepPhoto) URL.revokeObjectURL(analysis.photo.url);
    analysis = null;
    stopLines();
  }

  $('an-cancel').addEventListener('click', () => { cancelAnalysis(); show('welcome'); });
  $('an-other').addEventListener('click', () => { cancelAnalysis(); show('welcome'); });
  $('an-retry').addEventListener('click', () => {
    const photo = analysis?.photo;
    if (!photo) return show('welcome');
    analysis = null;
    runAnalysis(photo);
  });
  $('an-ready').addEventListener('click', () => {
    if (!analysis?.view) return;
    const { view, photo } = analysis;
    analysis = null; // the session owns the photo now
    stopLines();
    enterSession(view, photo);
  });

  /* ==========================================================================
     Session
     ========================================================================== */

  let session = null;

  const PAUSE = { id: 'pause', label: 'Pause for today' };
  const REPLIES = {
    normal: [{ id: 'done', label: 'Done', variant: 'primary', icon: 'check' }, { id: 'else', label: 'Something else' }],
    else: [{ id: 'swap', label: 'Try a different step' }, { id: 'toomuch', label: 'This feels like too much' },
           { id: 'where', label: 'Where do these go?' }, { id: 'back', label: 'Back to this step' }],
    closer: [{ id: 'photo', label: 'Take closer photo', variant: 'primary', icon: 'camera' }, { id: 'skip', label: 'Skip this area' }],
    support: [{ id: 'keep', label: 'Keep going, gently', variant: 'primary' }, { id: 'minute', label: 'I need a minute' }, PAUSE],
    paused: [{ id: 'pause', label: 'Finish for today', variant: 'primary' }, { id: 'resume', label: 'Actually, keep going' }],
    end: [{ id: 'photo', label: 'Photo of another area', variant: 'primary', icon: 'camera' }, { id: 'finish', label: 'Finish for today' }],
    expired: [{ id: 'restart', label: 'Start with a new photo', variant: 'primary', icon: 'camera' }]
  };

  function enterSession(view, photo) {
    endSession();
    session = {
      id: view.session_id,
      photos: [{ url: photo.url, closeup: false }], // index matches the backend's photo_index
      urls: [photo.url],                           // every object URL to revoke at the end
      shownPhoto: -1,
      step: null,
      stepKey: null,
      completed: 0,
      did: [],
      startedAt: Date.now(),
      busy: false,
      replies: 'normal'
    };
    S.clearLog();
    S.setGear(null);
    S.setQuickReplies([]);
    S.toggleZoom(false);
    $('photo-panel').classList.remove('is-collapsed');
    show('session');
    render(view);
  }

  function endSession() {
    if (!session) return;
    Api.endSession(session.id);
    session.urls.forEach((u) => URL.revokeObjectURL(u));
    session = null;
  }

  const stepMode = () => (!session.step ? 'end' : isCloser(session.step) ? 'closer' : 'normal');

  function setReplies(mode) {
    session.replies = mode;
    S.setQuickReplies(REPLIES[mode]);
    if (session.busy) S.setBusy(true);
  }

  function norm([W, H]) {
    return ([x1, y1, x2, y2]) => ({ x: x1 / W, y: y1 / H, w: (x2 - x1) / W, h: (y2 - y1) / H });
  }

  /** Resolve once the image is ready to paint, so the photo never flashes blank between steps. */
  function preload(src) {
    const img = new Image();
    img.src = src;
    return img.decode().then(() => src);
  }

  let photoToken = 0;

  /**
   * Show the step exactly as the backend renders it (render.py: blur outside, red outlines on
   * the items, a frame for closer-photo steps, people and screens blurred). The app draws
   * nothing on top; it only zooms toward the step's focus box.
   */
  function showStepPhoto(cur, title) {
    const s = session;
    const token = ++photoToken;
    const photo = s.photos[cur.photo_index] || s.photos.at(-1);
    const [width, height] = cur.image_size;
    const focusUrl = `/backend${cur.image_url}?v=${encodeURIComponent(s.stepKey)}`;
    const show = (src) => {
      if (token !== photoToken || session !== s) return;
      S.setPhoto(src, { width, height, closeup: photo.closeup });
      S.showRendered({
        title,
        pill: stepPill(cur, title),
        zoomTo: cur.focus ? norm(cur.image_size)(cur.focus.bbox_px) : null,
        closer: isCloser(cur)
      });
      s.shownPhoto = cur.photo_index;
    };
    preload(focusUrl).then(show, (err) => {
      console.warn('Step image unavailable; showing the plain photo:', err);
      show(photo.url);
    });
  }

  function showStep(cur) {
    const s = session;
    if (!cur) {
      s.step = null;
      photoToken++;
      const photo = s.photos[s.shownPhoto] || s.photos.at(-1);
      S.setPhoto(photo.url, { closeup: photo.closeup });
      S.showRendered({ title: '' });
      return;
    }

    const title = stepTitle(cur);
    const key = `${cur.step.id}:${cur.smaller}`;
    if (key !== s.stepKey) {
      S.addTask({
        title,
        body: stepBody(cur),
        label: cur.step.hazard ? 'A safety step' : undefined,
        kind: isCloser(cur) ? 'closer' : 'step'
      });
      s.stepKey = key;
      showStepPhoto(cur, title);
    }
    s.step = cur;
  }

  function render(view) {
    const s = session;
    s.id = view.session_id;

    if (view.completed > s.completed && s.step) {
      s.did.push(didLabel(s.step));
      S.addCelebrate(view.completed === 1 ? 'First step done' : `${view.completed} steps done`);
    }
    s.completed = view.completed;

    view.message.split(/\n\s*\n/).map((t) => t.trim()).filter(Boolean).forEach((t) => S.addCoach(t));
    if (view.intent === 'crisis') S.addSupport();

    S.setProgress({ stepsDone: view.completed, minutes: view.elapsed_min });
    S.setGear(gearLabel(view.assessment));
    showStep(view.current_step);

    setReplies(
      view.intent === 'crisis' ? 'support'
        : view.status === 'paused' ? 'paused'
        : stepMode()
    );
  }

  /** Run one backend turn with the typing bubble and busy state. Returns true on success. */
  async function turn(request, typingText) {
    const s = session;
    s.busy = true;
    S.setBusy(true);
    S.showTyping(typingText);
    try {
      const view = await request();
      if (session !== s) return false;
      S.hideTyping();
      render(view);
      return true;
    } catch (err) {
      if (session !== s) return false;
      console.error('Coach turn failed:', err);
      S.hideTyping();
      if (err.status === 404) {
        S.addCoach('This session timed out while we were apart, so your photo has been cleared. Whenever you’re ready, we can start fresh with a new photo.');
        setReplies('expired');
      } else {
        S.addCoach(turnError(err));
        setReplies(s.replies);
      }
      return false;
    } finally {
      if (session === s) { s.busy = false; S.setBusy(false); }
    }
  }

  function send(label, { text = label, action = null } = {}) {
    S.addUser(label);
    return turn(() => Api.sendMessage(session.id, { text, action }));
  }

  /** Replies that only change the UI; no backend turn needed. */
  function local(label, coachText, mode) {
    S.addUser(label);
    S.addCoach(coachText);
    setReplies(mode);
  }

  function takePhoto() {
    if (!session || session.busy) return;
    const closer = !!(session.step && isCloser(session.step));
    Camera.capture(closer
      ? { title: 'A closer photo', hint: 'About an arm’s length away is perfect.' }
      : { title: 'Another area', hint: 'One area at a time is plenty.' }
    ).then((file) => file && sendPhoto(file, closer));
  }

  async function sendPhoto(file, closer) {
    const s = session;
    if (!s || s.busy) return;
    s.busy = true;
    S.setBusy(true);
    const photo = await prepare(file);
    if (session !== s) { URL.revokeObjectURL(photo.url); return; }
    s.urls.push(photo.url);
    s.busy = false;
    S.addUserPhoto(photo.url, closer ? 'Closer photo sent' : 'New photo sent');
    await turn(async () => {
      const view = await Api.addPhoto(s.id, photo.blob);
      s.photos.push({ url: photo.url, closeup: closer });
      return view;
    }, 'Taking a look at your new photo…');
  }

  S.on('reply', ({ id, label }) => {
    if (!session || session.busy) return;
    switch (id) {
      case 'done': return send(label, { action: 'done' });
      case 'swap':
      case 'skip': return send(label, { action: 'skip' });
      case 'toomuch': return send(label, { action: 'smaller' });
      case 'where': return send(label);
      case 'keep': return session.step ? send(label, { action: 'smaller' }) : local(label, 'Okay. We’ll take it slow.', stepMode());
      case 'else': return local(label, 'Of course. What would help right now?', 'else');
      case 'back': return local(label, 'Okay. Take your time, and tap Done whenever you’re ready.', stepMode());
      case 'minute': return local(label, 'Take all the time you need. I’m right here whenever you’re ready.', stepMode());
      case 'resume': return local(label, 'Okay, let’s keep going. Here’s where we were.', stepMode());
      case 'photo': return takePhoto();
      case 'pause': return finish('paused');
      case 'finish': return finish('done');
      case 'restart': endSession(); return show('welcome');
    }
  });
  S.on('message', ({ text }) => { if (session && !session.busy) send(text); });
  S.on('takePhoto', takePhoto);
  S.on('pause', () => finish('paused'));

  /* ==========================================================================
     Done
     ========================================================================== */

  const CHECK = '<span class="tk-check"><svg class="tk-icon tk-icon--sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></span>';

  function finish(kind) {
    const did = session ? session.did : [];
    const minutes = session ? Math.max(1, Math.round((Date.now() - session.startedAt) / 60000)) : 1;
    endSession();

    const n = did.length;
    if (kind === 'done' && n > 0) {
      $('done-headline').textContent = 'You did something good today.';
      $('done-body').textContent =
        `${COUNT_WORDS[n] || n} small ${n === 1 ? 'step' : 'steps'} in about ${minutes} ${minutes === 1 ? 'minute' : 'minutes'}. That counts — and so does resting now.`;
    } else {
      $('done-headline').textContent = 'Stopping here is a win.';
      $('done-body').textContent = n > 0
        ? 'You showed up and took a step. That’s what matters. Resting is part of this too.'
        : 'You showed up today, and that’s what matters. Resting is part of this too.';
    }
    $('done-did').replaceChildren(...did.map((text) => {
      const li = document.createElement('li');
      li.innerHTML = CHECK;
      li.append(text);
      return li;
    }));
    $('done-card').hidden = n === 0;
    show('done');
  }

  $('done-rest').addEventListener('click', () => show('welcome'));
  $('done-restart').addEventListener('click', () => show('welcome'));

  /* ==========================================================================
     Lifecycle
     ========================================================================== */

  // Photos never outlive the page: drop the backend session when it closes or reloads.
  window.addEventListener('pagehide', () => {
    if (session) Api.endSession(session.id);
    if (analysis?.view) Api.endSession(analysis.view.session_id);
  });

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js').catch((err) => console.warn('Service worker not registered:', err));
    });
  }
})();
