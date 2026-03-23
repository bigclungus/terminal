/**
 * gamecube-sounds.js — GameCube OS-inspired UI sounds via Web Audio API.
 * GCSounds.hover() / GCSounds.click() / GCSounds.back()
 */
(function (global) {
  'use strict';

  var _ctx = null;
  var _unlocked = false;

  function init() {
    if (_ctx) return _ctx;
    try {
      _ctx = new (window.AudioContext || window.webkitAudioContext)();
    } catch (e) {
      console.warn('[GCSounds] Web Audio unavailable:', e);
      return null;
    }
    return _ctx;
  }

  // Unlock AudioContext on first user gesture (Chrome autoplay policy).
  // Create a silent buffer and play it — this moves the context to 'running'.
  function unlock() {
    if (_unlocked) return;
    var ctx = init();
    if (!ctx) return;
    var buf = ctx.createBuffer(1, 1, 22050);
    var src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    src.start(0);
    ctx.resume().then(function () {
      _unlocked = true;
      console.log('[GCSounds] AudioContext unlocked, state:', ctx.state);
    });
  }

  // Unlock on first click/keydown anywhere on the page
  document.addEventListener('click',   unlock, { once: false, capture: true });
  document.addEventListener('keydown', unlock, { once: false, capture: true });

  function playTone(ctx, freq, startTime, duration, peakGain, freqEnd) {
    var osc  = ctx.createOscillator();
    var gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(freq, startTime);
    if (freqEnd !== undefined && freqEnd !== freq) {
      osc.frequency.linearRampToValueAtTime(freqEnd, startTime + duration);
    }
    gain.gain.setValueAtTime(0, startTime);
    gain.gain.linearRampToValueAtTime(peakGain, startTime + 0.01);
    gain.gain.linearRampToValueAtTime(0, startTime + duration);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(startTime);
    osc.stop(startTime + duration + 0.02);
  }

  function play(fn) {
    var ctx = init();
    if (!ctx) return;
    if (ctx.state === 'suspended') {
      ctx.resume().then(function () { fn(ctx, ctx.currentTime); });
    } else {
      fn(ctx, ctx.currentTime);
    }
  }

  global.GCSounds = {
    hover: function () {
      play(function (ctx, t) { playTone(ctx, 700, t, 0.12, 0.5, 920); });
    },
    click: function () {
      play(function (ctx, t) {
        playTone(ctx, 523.25, t,        0.20, 0.7);
        playTone(ctx, 659.25, t + 0.15, 0.25, 0.6);
      });
    },
    back: function () {
      play(function (ctx, t) { playTone(ctx, 680, t, 0.15, 0.5, 460); });
    },
  };

  console.log('[GCSounds] loaded');
})(window);
