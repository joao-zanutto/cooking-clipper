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

    try {
      const [vResp, jResp] = await Promise.all([
        apiGet(`/api/buckets/${encodeURIComponent(currentBucket)}/videos`),
        apiGet(`/api/buckets/${encodeURIComponent(currentBucket)}/jobs`),
      ]);
      videos = vResp.videos || [];
      jobs = jResp.jobs || [];
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
          apiPost(
            `/api/buckets/${encodeURIComponent(currentBucket)}/process`,
            {
              key: v.key,
              clip_duration: v.clip_duration || undefined,
              motion_threshold: v.motion_threshold || undefined,
              change_threshold: v.change_threshold || undefined,
            },
          ),
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

  // ── Init ─────────────────────────────────────────────
  loadBuckets();
})();
