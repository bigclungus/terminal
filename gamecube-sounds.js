/**
 * gamecube-sounds.js — GameCube OS-inspired UI sounds via Web Audio API.
 * GCSounds.hover() / GCSounds.click() / GCSounds.back()
 */
(function (global) {
  'use strict';

  var _ctx = null;

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
    // Schedule slightly ahead so tones play even if context is still resuming.
    // While suspended ctx.currentTime is frozen, so currentTime+0.05 is always
    // safely in the future once the context starts running.
    if (ctx.state !== 'running') {
      ctx.resume().catch(function (e) { console.warn('[GCSounds] resume failed:', e); });
    }
    fn(ctx, ctx.currentTime + 0.05);
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
