/* ==========================================================================
   Taskit — camera
   window.TaskitCamera.capture({ title, hint }) → Promise<Blob | File | null>
   window.TaskitCamera.pick()                   → Promise<File | null>

   capture() opens a live camera sheet (getUserMedia) when the page is on a
   secure origin (https or localhost). Otherwise — e.g. a phone opening the
   dev server over plain http on the LAN — it opens the phone's own camera
   through <input type="file" capture>. Resolves null if the person cancels.

   Call these straight from a click handler (no await first): browsers only
   open file pickers during a user gesture.
   ========================================================================== */
(function () {
  'use strict';

  const q = (key) => document.querySelector(`[data-cam="${key}"]`);
  const el = {
    root: q('root'), close: q('close'), title: q('title'), hint: q('hint'),
    video: q('video'), still: q('still'), msg: q('msg'), msgText: q('msg-text'), msgPick: q('msg-pick'),
    live: q('live-controls'), review: q('review-controls'),
    library: q('library'), shutter: q('shutter'), retake: q('retake'), use: q('use'),
    nativeCapture: q('native-capture'), nativePick: q('native-pick')
  };

  const canUseLiveCamera = () => window.isSecureContext && !!navigator.mediaDevices?.getUserMedia;

  /* ---------------- Native pickers ---------------- */

  // One pending pick per input, so an unanswered pick (browsers without the
  // 'cancel' event) can't resolve later alongside a newer one.
  const pendingPick = new Map();

  function chooseFile(input) {
    pendingPick.get(input)?.(null);
    return new Promise((resolve) => {
      const finish = (file) => {
        input.removeEventListener('change', onChange);
        input.removeEventListener('cancel', onCancel);
        pendingPick.delete(input);
        input.value = '';
        resolve(file);
      };
      const onChange = () => finish(input.files[0] || null);
      const onCancel = () => finish(null);
      input.addEventListener('change', onChange);
      input.addEventListener('cancel', onCancel);
      pendingPick.set(input, finish);
      input.click();
    });
  }

  /* ---------------- Live camera sheet ---------------- */

  let stream = null;
  let openToken = 0;
  let settle = null;
  let snapped = null;
  let stillUrl = null;
  let returnFocus = null;

  function stopStream() {
    stream?.getTracks().forEach((t) => t.stop());
    stream = null;
    el.video.srcObject = null;
  }

  function clearStill() {
    if (stillUrl) URL.revokeObjectURL(stillUrl);
    stillUrl = null;
    snapped = null;
    el.still.removeAttribute('src');
    el.still.hidden = true;
  }

  function showLive() {
    clearStill();
    el.video.hidden = false;
    el.msg.hidden = true;
    el.live.hidden = false;
    el.review.hidden = true;
    el.shutter.disabled = true;
  }

  function showMessage(text) {
    stopStream();
    el.video.hidden = true;
    el.msgText.textContent = text;
    el.msg.hidden = false;
    el.shutter.disabled = true;
    el.msgPick.focus();
  }

  async function startStream() {
    const token = ++openToken;
    try {
      const s = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1440 } },
        audio: false
      });
      if (token !== openToken || el.root.hidden) { s.getTracks().forEach((t) => t.stop()); return; }
      stream = s;
      el.video.srcObject = s;
      await el.video.play().catch(() => {});
      el.shutter.disabled = false;
    } catch (err) {
      if (token !== openToken) return;
      showMessage(err?.name === 'NotAllowedError'
        ? 'Camera access is turned off for Taskit. You can allow it in your browser settings, or choose a photo from your library.'
        : 'The camera isn’t available right now. You can choose a photo from your library instead.');
    }
  }

  function openSheet(title, hint) {
    returnFocus = document.activeElement;
    el.title.textContent = title;
    el.hint.textContent = hint;
    el.root.hidden = false;
    showLive();
    el.close.focus();
    startStream();
  }

  function closeSheet() {
    openToken++;
    stopStream();
    clearStill();
    el.root.hidden = true;
    returnFocus?.focus?.();
    returnFocus = null;
  }

  function snap() {
    const v = el.video;
    if (!v.videoWidth) return;
    const canvas = document.createElement('canvas');
    canvas.width = v.videoWidth;
    canvas.height = v.videoHeight;
    canvas.getContext('2d').drawImage(v, 0, 0);
    canvas.toBlob((blob) => {
      if (!blob || el.root.hidden) return;
      stopStream();
      snapped = blob;
      stillUrl = URL.createObjectURL(blob);
      el.still.src = stillUrl;
      el.still.hidden = false;
      el.video.hidden = true;
      el.live.hidden = true;
      el.review.hidden = false;
      el.use.focus();
    }, 'image/jpeg', 0.92);
  }

  function pickInsideSheet() {
    chooseFile(el.nativePick).then((file) => { if (file && settle) settle(file); });
  }

  el.shutter.addEventListener('click', snap);
  el.retake.addEventListener('click', () => { showLive(); startStream(); });
  el.use.addEventListener('click', () => settle?.(snapped));
  el.close.addEventListener('click', () => settle?.(null));
  el.library.addEventListener('click', pickInsideSheet);
  el.msgPick.addEventListener('click', pickInsideSheet);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !el.root.hidden) settle?.(null); });

  function capture({ title = 'Take a photo', hint = 'One area at a time is plenty.' } = {}) {
    if (!canUseLiveCamera()) return chooseFile(el.nativeCapture);
    settle?.(null);
    return new Promise((resolve) => {
      settle = (result) => { settle = null; closeSheet(); resolve(result); };
      openSheet(title, hint);
    });
  }

  window.TaskitCamera = {
    capture,
    pick: () => chooseFile(el.nativePick)
  };
})();
