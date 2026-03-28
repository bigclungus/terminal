(() => {
  // src/gamecube-sounds.ts
  ((global) => {
    let _ctx = null;
    function init() {
      if (_ctx)
        return _ctx;
      try {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        _ctx = new AudioCtx;
      } catch (e) {
        console.warn("[GCSounds] Web Audio unavailable:", e);
        return null;
      }
      return _ctx;
    }
    function playTone(ctx, freq, startTime, duration, peakGain, freqEnd) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
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
      const ctx = init();
      if (!ctx)
        return;
      if (ctx.state !== "running") {
        ctx.resume().catch((e) => {
          console.warn("[GCSounds] resume failed:", e);
        });
      }
      fn(ctx, ctx.currentTime + 0.05);
    }
    global.GCSounds = {
      hover() {
        play((ctx, t) => {
          playTone(ctx, 700, t, 0.12, 0.5, 920);
        });
      },
      click() {
        play((ctx, t) => {
          playTone(ctx, 523.25, t, 0.2, 0.7);
          playTone(ctx, 659.25, t + 0.15, 0.25, 0.6);
        });
      },
      back() {
        play((ctx, t) => {
          playTone(ctx, 680, t, 0.15, 0.5, 460);
        });
      }
    };
    console.log("[GCSounds] loaded");
  })(window);
})();
