/* Cooking Clipper — frontend SPA */
(function () {
  "use strict";

  // ── State ────────────────────────────────────────────
  let currentBucket = "";
  let videos = [];
  let jobs = [];

  // ── DOM refs ─────────────────────────────────────────
  const bucketSelect = document.getElementById("bucket-select");
  const refreshBtn = document.getElementById("refresh-btn");
  const mainEl = document.getElementById("main");
  const videoGrid = document.getElementById("video-grid");
  const batchBar = document.getElementById("batch-bar");
  const jobsSection = document.getElementById("jobs-section");
  const jobList = document.getElementById("job-list");
  const toast = document.getElementById("toast");

  // Batch param inputs
  const batchClip = document.getElementById("batch-clip");
  const batchMotion = document.getElementById("batch-motion");
  const batchChange = document.getElementById("batch-change");
  const batchClipVal = document.getElementById("batch-clip-val");
  const batchMotionVal = document.getElementById("batch-motion-val");
  const batchChangeVal = document.getElementById("batch-change-val");

  // ── Helpers ──────────────────────────────────────────

  function showToast(msg, type = "") {
    toast.textContent = msg;
    toast.className = type;
    toast.classList.remove("hidden");
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => toast.classList.add("hidden"), 4000);
  }

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function formatDate(iso) {
    return new Date(iso).toLocaleString();
  }

  function statusClass(s) {
    return "status status-" + (s || "unprocessed");
  }

  // ── API calls ────────────────────────────────────────

  async function apiGet(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }

  async function apiPost(path, body) {
    const r = await fetch(path, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || r.statusText);
    return {status: r.status, data};
  }

  // ── Load buckets ─────────────────────────────────────

  async function loadBuckets() {
    try {
      const resp = await apiGet("/api/buckets");
      const buckets = resp.buckets || [];
      bucketSelect.innerHTML =
        '<option value="">— Select —</option>' +
        buckets
          .map((b) => `<option value="${b.name}">${b.name}</option>`)
          .join("");
      if (currentBucket) bucketSelect.value = currentBucket;
    } catch (e) {
      showToast("Failed to load buckets: " + e.message, "error");
    }
  }

  // ── Load videos + jobs ───────────────────────────────

  async function loadVideos() {
    if (!currentBucket) {
      mainEl.innerHTML =
        '<div class="placeholder">Select a project to see videos</div>';
      videoGrid.classList.add("hidden");
      batchBar.classList.add("hidden");
      jobsSection.classList.add("hidden");
      return;
    }

    // Snapshot current local slider values before fetching
    const localParams = {};
    videos.forEach((v, i) => {
      if (
        v.clip_duration !== undefined ||
        v.motion_threshold !== undefined ||
        v.change_threshold !== undefined
      ) {
        localParams[v.key] = {
          clip_duration: v.clip_duration,
          motion_threshold: v.motion_threshold,
          change_threshold: v.change_threshold,
        };
      }
    });

    try {
      const [vResp, jResp] = await Promise.all([
        apiGet(`/api/buckets/${encodeURIComponent(currentBucket)}/videos`),
        apiGet(`/api/buckets/${encodeURIComponent(currentBucket)}/jobs`),
      ]);
      videos = vResp.videos || [];
      jobs = jResp.jobs || [];

      // Restore local slider values that may differ from server defaults.
      // Also load stored config from S3 (inlined by the API) when available.
      videos.forEach((v) => {
        const saved = localParams[v.key];
        if (saved) {
          if (saved.clip_duration !== undefined)
            v.clip_duration = saved.clip_duration;
          if (saved.motion_threshold !== undefined)
            v.motion_threshold = saved.motion_threshold;
          if (saved.change_threshold !== undefined)
            v.change_threshold = saved.change_threshold;
        } else if (v.config) {
          // Stored config from S3 — use it as slider defaults
          if (v.config.CLIP_DURATION !== undefined)
            v.clip_duration = v.config.CLIP_DURATION;
          if (v.config.MOTION_THRESHOLD !== undefined)
            v.motion_threshold = v.config.MOTION_THRESHOLD;
          if (v.config.CHANGE_THRESHOLD !== undefined)
            v.change_threshold = v.config.CHANGE_THRESHOLD;
        }
      });

      renderVideos();
      renderJobs();
      batchBar.classList.remove("hidden");
      jobsSection.classList.remove("hidden");
      mainEl.innerHTML = "";
      videoGrid.classList.remove("hidden");
    } catch (e) {
      showToast("Failed to load videos: " + e.message, "error");
    }
  }

  // ── Render videos ────────────────────────────────────

  function renderVideos() {
    if (!videos.length) {
      videoGrid.innerHTML = '<div class="placeholder">No videos found</div>';
      return;
    }

    videoGrid.innerHTML = videos
      .map((v, idx) => {
        const status = v.status || "unprocessed";
        const disabled = status === "running" || status === "pending";
        return `
          <div class="video-card" data-idx="${idx}">
            <div class="name">${escHtml(v.key)}</div>
            <div class="meta">
              <span>${formatSize(v.size)}</span>
              <span>${formatDate(v.last_modified)}</span>
              <span class="${statusClass(status)}">${status}</span>
            </div>
            <div class="params">
              <label>
                Clip ${clipSlider("clip", idx, v.clip_duration || 2.5, 0.5, 10, 0.5)}
                <span class="val" id="clip-val-${idx}">${v.clip_duration || 2.5}</span>s
              </label>
              <label>
                Motion ${clipSlider("motion", idx, v.motion_threshold || 0.15, 0.01, 1.0, 0.01)}
                <span class="val" id="motion-val-${idx}">${v.motion_threshold || 0.15}</span>
              </label>
              <label>
                Change ${clipSlider("change", idx, v.change_threshold || 20, 5, 100, 5)}
                <span class="val" id="change-val-${idx}">${v.change_threshold || 20}</span>
              </label>
            </div>
            <div class="actions">
              <button class="preview-btn preview-original" data-idx="${idx}">
                View Original
              </button>
              <button class="preview-btn preview-processed" data-idx="${idx}"
                ${status !== "done" ? "disabled" : ""}
                title="${status !== "done" ? "Video not yet processed" : "View processed video"}">
                View Processed
              </button>
              <button class="process-btn" data-idx="${idx}" ${disabled ? "disabled" : ""}>
                ${disabled ? "Processing…" : "Process"}
              </button>
            </div>
          </div>`;
      })
      .join("");

    // Attach slider events
    document.querySelectorAll(".param-slider").forEach((sl) => {
      sl.addEventListener("input", onSliderChange);
    });

    // Attach preview buttons
    document.querySelectorAll(".preview-original").forEach((btn) => {
      btn.addEventListener("click", () =>
        openModal("original", btn.dataset.idx),
      );
    });
    document.querySelectorAll(".preview-processed").forEach((btn) => {
      btn.addEventListener("click", () =>
        openModal("processed", btn.dataset.idx),
      );
    });

    // Attach process buttons
    document.querySelectorAll(".process-btn").forEach((btn) => {
      btn.addEventListener("click", onProcessClick);
    });
  }

  function clipSlider(name, idx, val, min, max, step) {
    return `<input type="range" class="param-slider" data-idx="${idx}" data-param="${name}"
      min="${min}" max="${max}" step="${step}" value="${val}">`;
  }

  function escHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  // ── Slider change ────────────────────────────────────

  function onSliderChange(e) {
    const sl = e.target;
    const idx = sl.dataset.idx;
    const param = sl.dataset.param;
    const valEl = document.getElementById(`${param}-val-${idx}`);
    if (valEl) valEl.textContent = sl.value;
    // Store on the video object
    if (videos[idx]) {
      const key =
        param === "clip"
          ? "clip_duration"
          : param === "motion"
            ? "motion_threshold"
            : "change_threshold";
      videos[idx][key] = parseFloat(sl.value);
    }
  }

  // ── Process button ───────────────────────────────────

  async function onProcessClick(e) {
    const idx = e.target.dataset.idx;
    const v = videos[idx];
    if (!v) return;

    e.target.disabled = true;
    e.target.textContent = "Starting…";

    try {
      const result = await apiPost(
        `/api/buckets/${encodeURIComponent(currentBucket)}/process`,
        {
          key: v.key,
          clip_duration: v.clip_duration || undefined,
          motion_threshold: v.motion_threshold || undefined,
          change_threshold: v.change_threshold || undefined,
        },
      );
      showToast(`Started: ${v.key}`, "success");
      // Refresh after a moment
      setTimeout(loadVideos, 1000);
    } catch (e) {
      showToast("Error: " + e.message, "error");
      e.target.disabled = false;
      e.target.textContent = "Process";
    }
  }

  // ── Render jobs ──────────────────────────────────────

  function renderJobs() {
    if (!jobs.length) {
      jobList.innerHTML =
        "<div style='color:var(--text-dim)'>No recent jobs</div>";
      return;
    }
    jobList.innerHTML = jobs
      .map(
        (j) => `
        <div class="job-row">
          <span class="${statusClass(j.status)}">${j.status}</span>
          <span class="job-name">${escHtml(j.name)}</span>
          <span class="job-key">${escHtml(j.video_key)}</span>
        </div>`,
      )
      .join("");
  }

  // ── Apply all ────────────────────────────────────────

  document.getElementById("apply-all-btn").addEventListener("click", () => {
    const clip = parseFloat(batchClip.value);
    const motion = parseFloat(batchMotion.value);
    const change = parseInt(batchChange.value, 10);

    // Update video objects and re-render
    videos.forEach((v) => {
      v.clip_duration = clip;
      v.motion_threshold = motion;
      v.change_threshold = change;
    });
    // Update the display values in sliders
    document.querySelectorAll(".param-slider").forEach((sl) => {
      const idx = sl.dataset.idx;
      const param = sl.dataset.param;
      let val;
      if (param === "clip") val = clip;
      else if (param === "motion") val = motion;
      else val = change;
      sl.value = val;
      const valEl = document.getElementById(`${param}-val-${idx}`);
      if (valEl) valEl.textContent = val;
    });
    showToast("Applied batch params to all videos", "");
  });

  // ── Process all unprocessed ──────────────────────────

  document
    .getElementById("process-all-btn")
    .addEventListener("click", async () => {
      const unprocessed = videos.filter((v) => v.status === "unprocessed");
      if (!unprocessed.length) {
        showToast("No unprocessed videos", "");
        return;
      }
      showToast(`Starting ${unprocessed.length} jobs…`, "");

      const results = await Promise.allSettled(
        unprocessed.map((v) =>
          apiPost(`/api/buckets/${encodeURIComponent(currentBucket)}/process`, {
            key: v.key,
            clip_duration: v.clip_duration || undefined,
            motion_threshold: v.motion_threshold || undefined,
            change_threshold: v.change_threshold || undefined,
          }),
        ),
      );
      const started = results.filter((r) => r.status === "fulfilled").length;
      showToast(`Started ${started}/${unprocessed.length} jobs`, "success");
      setTimeout(loadVideos, 1500);
    });

  // ── Batch slider display ─────────────────────────────

  batchClip.addEventListener("input", () => {
    batchClipVal.textContent = batchClip.value;
  });
  batchMotion.addEventListener("input", () => {
    batchMotionVal.textContent = batchMotion.value;
  });
  batchChange.addEventListener("input", () => {
    batchChangeVal.textContent = batchChange.value;
  });

  // ── Bucket selection ─────────────────────────────────

  bucketSelect.addEventListener("change", () => {
    currentBucket = bucketSelect.value;
    loadVideos();
  });

  refreshBtn.addEventListener("click", () => {
    if (currentBucket) loadVideos();
    else loadBuckets();
  });

  // ── Auto-refresh every 10s ───────────────────────────
  setInterval(() => {
    if (currentBucket) loadVideos();
  }, 10000);

  // ── Modal ─────────────────────────────────────────────
  const modal = document.getElementById("video-modal");
  const modalVideo = document.getElementById("modal-video");
  const modalClose = document.getElementById("modal-close");
  const modalChartCanvas = document.getElementById("modal-chart");
  const modalPlaceholder = document.getElementById("modal-placeholder");
  const modalStats = document.getElementById("modal-stats");

  let modalScoresData = null;
  let modalPeaks = [];
  let modalPlaying = false;
  let modalRafId = null;

  function openModal(type, idx) {
    const v = videos[idx];
    if (!v) return;

    const isProcessed = type === "processed";
    modal.classList.remove("hidden");

    // Hide chart initially, show placeholder
    modalChartCanvas.parentElement.style.display = "none";
    modalPlaceholder.style.display = "block";
    modalStats.innerHTML = "";

    if (isProcessed && v.status === "done") {
      // Fetch scores data and render chart
      modalPlaceholder.textContent = "Loading scores…";
      fetch(v.scores_url)
        .then((r) => {
          if (!r.ok) throw new Error("Scores not found");
          return r.json();
        })
        .then((data) => {
          modalScoresData = data;
          modalPlaceholder.style.display = "none";
          modalChartCanvas.parentElement.style.display = "block";
          renderModalChart();
          renderModalStats();
        })
        .catch(() => {
          modalPlaceholder.textContent = "Video still not processed";
          modalPlaceholder.style.display = "block";
          modalChartCanvas.parentElement.style.display = "none";
        });
      modalVideo.src = v.processed_url;
    } else {
      // Original video or unprocessed — no chart
      modalPlaceholder.textContent = "Video still not processed";
      modalVideo.src = v.video_url;
    }

    modalVideo.load();
    modalVideo.play().catch(() => {});
  }

  function closeModal() {
    modal.classList.add("hidden");
    modalVideo.pause();
    modalVideo.removeAttribute("src");
    modalVideo.load();
    modalScoresData = null;
    modalPeaks = [];
    modalPlaying = false;
    if (modalRafId) {
      cancelAnimationFrame(modalRafId);
      modalRafId = null;
    }
  }

  modalClose.addEventListener("click", closeModal);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.classList.contains("hidden")) closeModal();
  });

  // ── Chart (vanilla Canvas 2D, mirrors frontend/index.html) ──

  const CHART_HEIGHT = 240;
  const PAD = {top: 12, right: 16, bottom: 28, left: 52};
  const DPR = window.devicePixelRatio || 1;

  function dprScale(canvas) {
    const rect = canvas.getBoundingClientRect();
    const w = rect.width,
      h = CHART_HEIGHT;
    if (
      canvas.width !== Math.round(w * DPR) ||
      canvas.height !== Math.round(h * DPR)
    ) {
      canvas.width = Math.round(w * DPR);
      canvas.height = Math.round(h * DPR);
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    return {ctx, w, h};
  }

  function getBounds(canvas) {
    const {ctx, w, h} = dprScale(canvas);
    return {
      ctx,
      w,
      h,
      left: PAD.left,
      right: w - PAD.right,
      top: PAD.top,
      bottom: h - PAD.bottom,
      width: w - PAD.left - PAD.right,
      height: h - PAD.top - PAD.bottom,
    };
  }

  function renderModalChart() {
    if (!modalScoresData) return;
    const scores = modalScoresData.scores;
    if (!scores || !scores.length) return;

    const rawPeaks = modalScoresData.peaks || [];
    modalPeaks = rawPeaks.map((p) => {
      const startF = Array.isArray(p) ? p[0] : p.start_frame;
      const endF = Array.isArray(p) ? p[1] : p.end_frame;
      const score = Array.isArray(p) ? p[2] : p.score || 0;
      return {
        start: startF,
        end: endF,
        score,
        startSec: startF / modalScoresData.fps,
        endSec: endF / modalScoresData.fps,
      };
    });

    drawModalChart();

    // Video playback sync
    modalVideo.removeEventListener("play", onModalPlay);
    modalVideo.removeEventListener("pause", onModalPause);
    modalVideo.removeEventListener("ended", onModalPause);
    modalVideo.removeEventListener("seeked", onModalSeeked);
    modalVideo.addEventListener("play", onModalPlay);
    modalVideo.addEventListener("pause", onModalPause);
    modalVideo.addEventListener("ended", onModalPause);
    modalVideo.addEventListener("seeked", onModalSeeked);
  }

  function onModalPlay() {
    modalPlaying = true;
    modalCursorLoop();
  }
  function onModalPause() {
    modalPlaying = false;
    if (modalRafId) {
      cancelAnimationFrame(modalRafId);
      modalRafId = null;
    }
  }
  function onModalSeeked() {
    drawModalChart();
  }

  function modalCursorLoop() {
    if (!modalPlaying) return;
    drawModalChart();
    modalRafId = requestAnimationFrame(modalCursorLoop);
  }

  function drawModalChart() {
    if (!modalScoresData || !modalScoresData.scores) return;
    const scores = modalScoresData.scores;
    const total = scores.length;
    const maxSc = Math.max(...scores, 1);
    const b = getBounds(modalChartCanvas);
    const {ctx} = b;

    ctx.clearRect(0, 0, b.w, b.h);

    // Grid
    ctx.strokeStyle = "#21262d";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = b.top + (i / 4) * b.height;
      ctx.beginPath();
      ctx.moveTo(b.left, y);
      ctx.lineTo(b.right, y);
      ctx.stroke();
    }

    // Clip regions
    for (const p of modalPeaks) {
      const x1 = frameToX(p.start, total, b);
      const x2 = frameToX(p.end, total, b);
      ctx.fillStyle = "rgba(56,139,253,0.12)";
      ctx.strokeStyle = "rgba(56,139,253,0.35)";
      ctx.lineWidth = 1;
      ctx.fillRect(x1, b.top, x2 - x1, b.height);
      ctx.strokeRect(x1, b.top, x2 - x1, b.height);
    }

    // Score line
    ctx.strokeStyle = "#58a6ff";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    const step = Math.max(1, Math.floor(total / 2000));
    for (let i = 0; i < total; i += step) {
      const x = frameToX(i, total, b);
      const y = scoreToY(scores[i], maxSc, b);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    if (total > 0 && (total - 1) % step !== 0) {
      const x = frameToX(total - 1, total, b);
      const y = scoreToY(scores[total - 1], maxSc, b);
      ctx.lineTo(x, y);
    }
    ctx.stroke();

    // X labels
    ctx.fillStyle = "rgba(139,148,158,0.6)";
    ctx.font = "10px sans-serif";
    ctx.textAlign = "center";
    const duration = modalScoresData.duration || total / modalScoresData.fps;
    const numLabels = Math.max(2, Math.floor(b.width / 80));
    for (let i = 0; i <= numLabels; i++) {
      ctx.fillText(
        ((i / numLabels) * duration).toFixed(1) + "s",
        b.left + (i / numLabels) * b.width,
        b.h - 4,
      );
    }

    // Y labels
    ctx.fillStyle = "rgba(139,148,158,0.6)";
    ctx.font = "10px sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (let i = 0; i <= 4; i++) {
      ctx.fillText(
        (maxSc * (1 - i / 4)).toFixed(1),
        b.left - 6,
        b.top + (i / 4) * b.height,
      );
    }

    // Playback cursor
    const curSec = modalVideo.currentTime || 0;
    const curFrame = curSec * modalScoresData.fps;
    const cx = frameToX(curFrame, total, b);
    ctx.strokeStyle = "#f0f6fc";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(cx, b.top);
    ctx.lineTo(cx, b.bottom);
    ctx.stroke();
  }

  function frameToX(frame, total, b) {
    return total > 1 ? b.left + (frame / (total - 1)) * b.width : b.left;
  }

  function scoreToY(score, maxSc, b) {
    return b.bottom - (score / maxSc) * b.height;
  }

  // Click-to-seek on chart
  modalChartCanvas.addEventListener("click", (e) => {
    if (!modalScoresData) return;
    const rect = modalChartCanvas.getBoundingClientRect();
    const b = getBounds(modalChartCanvas);
    const relX = (e.clientX - rect.left - b.left) / b.width;
    const frame = Math.round(
      Math.max(0, Math.min(1, relX)) * (modalScoresData.num_frames - 1),
    );
    modalVideo.currentTime = frame / modalScoresData.fps;
  });

  function renderModalStats() {
    if (!modalScoresData) return;
    const d = modalScoresData;
    const peaks = modalPeaks || [];
    let html = `
      <span>Frames: <strong>${(d.num_frames || d.scores.length).toLocaleString()}</strong></span>
      <span>FPS: <strong>${d.fps.toFixed(2)}</strong></span>
      <span>Duration: <strong>${(d.duration || d.scores.length / d.fps).toFixed(1)}s</strong></span>
      <span>Clips: <strong>${peaks.length}</strong></span>`;
    if (peaks.length) {
      const totalClipSec = peaks.reduce(
        (s, p) => s + (p.endSec - p.startSec),
        0,
      );
      html += `<span>Clips total: <strong>${totalClipSec.toFixed(1)}s</strong></span>`;
    }
    modalStats.innerHTML = html;
  }

  // ── Init ─────────────────────────────────────────────
  loadBuckets();
})();
