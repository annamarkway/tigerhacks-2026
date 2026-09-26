/* ==========================================================================
   Taskit — backend client
   Talks to the FastAPI coach (backend/app/main.py) through the Express proxy
   at /backend (see server.js), so the phone only needs one origin.
   ========================================================================== */
(function () {
  'use strict';

  const BASE = '/backend';

  class ApiError extends Error {
    /** status 0 means the request never got a response (offline, server down). */
    constructor(status, detail) {
      super(typeof detail === 'string' ? detail : `Request failed (${status})`);
      this.status = status;
      this.detail = detail;
    }
  }

  async function request(path, { method = 'GET', body, json, signal, keepalive } = {}) {
    let res;
    try {
      res = await fetch(BASE + path, {
        method,
        body: json ? JSON.stringify(json) : body,
        headers: json ? { 'Content-Type': 'application/json' } : undefined,
        signal,
        keepalive
      });
    } catch (err) {
      if (err.name === 'AbortError') throw err;
      throw new ApiError(0, 'network');
    }
    if (res.status === 204) return null;
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new ApiError(res.status, data?.detail || res.statusText);
    return data;
  }

  function photoForm(blob) {
    const form = new FormData();
    form.append('image', blob, blob.name || 'photo.jpg');
    return form;
  }

  const sid = (id) => encodeURIComponent(id);

  window.TaskitApi = {
    ApiError,
    /** POST /sessions → SessionView. Slow: runs vision, classify, triage and the opening coach turn. */
    startSession: (blob, { signal } = {}) =>
      request('/sessions', { method: 'POST', body: photoForm(blob), signal }),
    /** POST /sessions/{id}/messages. action: 'done' | 'skip' | 'smaller' | … (buttons); text goes to the coach. */
    sendMessage: (id, { text = null, action = null } = {}) =>
      request(`/sessions/${sid(id)}/messages`, { method: 'POST', json: { text, action } }),
    /** POST /sessions/{id}/photo: a closer photo, or a new area once the plan runs out. */
    addPhoto: (id, blob) =>
      request(`/sessions/${sid(id)}/photo`, { method: 'POST', body: photoForm(blob) }),
    /** DELETE /sessions/{id}: drop the session and its photos now. Never throws. */
    endSession: (id) =>
      request(`/sessions/${sid(id)}`, { method: 'DELETE', keepalive: true }).catch(() => {})
  };
})();
