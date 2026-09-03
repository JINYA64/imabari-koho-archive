(() => {
  "use strict";

  const CATEGORY_ORDER = [
    "子育て・教育",
    "防災・インフラ",
    "産業・経済",
    "観光・魅力発信",
    "まちづくり・地域振興",
    "医療・福祉",
    "スポーツ（FC今治等）",
    "文化・伝統",
    "環境・SDGs",
    "市政運営・行政サービス",
    "その他",
  ];

  const els = {
    ledger: document.getElementById("ledger"),
    emptyState: document.getElementById("empty-state"),
    loadingState: document.getElementById("loading-state"),
    resultCount: document.getElementById("result-count"),
    searchInput: document.getElementById("search-input"),
    categorySelect: document.getElementById("category-select"),
    sortSelect: document.getElementById("sort-select"),
    statCount: document.getElementById("stat-count"),
    statRange: document.getElementById("stat-range"),
    statCategories: document.getElementById("stat-categories"),
    lastUpdated: document.getElementById("last-updated"),
  };

  let allVideos = [];

  function formatDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
  }

  async function loadData() {
    const [videosRes, enrichedRes] = await Promise.all([
      fetch("data/videos.json"),
      fetch("data/videos_enriched.json").catch(() => null),
    ]);

    if (!videosRes.ok) {
      throw new Error(`videos.json の取得に失敗しました (status ${videosRes.status})`);
    }
    const videosData = await videosRes.json();

    let enrichedMap = {};
    if (enrichedRes && enrichedRes.ok) {
      const enrichedData = await enrichedRes.json();
      enrichedMap = enrichedData.videos || {};
    }

    const merged = (videosData.videos || []).map((v) => {
      const e = enrichedMap[v.video_id] || {};
      return {
        ...v,
        category: e.category || null,
        summary: e.summary || "",
        plain_title: e.plain_title || v.title,
      };
    });

    els.lastUpdated.textContent = videosData.fetched_at
      ? `最終更新: ${formatDate(videosData.fetched_at)}`
      : "";

    return merged;
  }

  function populateCategoryOptions(videos) {
    const present = new Set(videos.map((v) => v.category).filter(Boolean));
    const ordered = CATEGORY_ORDER.filter((c) => present.has(c));
    for (const cat of ordered) {
      const opt = document.createElement("option");
      opt.value = cat;
      opt.textContent = cat;
      els.categorySelect.appendChild(opt);
    }
    els.statCategories.textContent = String(ordered.length);
  }

  function updateStats(videos) {
    els.statCount.textContent = String(videos.length);

    const dates = videos
      .map((v) => v.published_at)
      .filter(Boolean)
      .map((d) => new Date(d))
      .filter((d) => !Number.isNaN(d.getTime()));

    if (dates.length) {
      const min = new Date(Math.min(...dates));
      const max = new Date(Math.max(...dates));
      els.statRange.textContent = `${min.getFullYear()}–${max.getFullYear()}`;
    }
  }

  function renderList(videos) {
    els.ledger.innerHTML = "";
    const frag = document.createDocumentFragment();

    videos.forEach((v, i) => {
      const li = document.createElement("li");
      li.className = "ledger-item";

      const indexEl = document.createElement("span");
      indexEl.className = "ledger-index";
      indexEl.textContent = String(videos.length - i);
      indexEl.setAttribute("aria-hidden", "true");

      const thumb = document.createElement("img");
      thumb.className = "ledger-thumb";
      thumb.src = v.thumbnail_url || "";
      thumb.alt = "";
      thumb.loading = "lazy";

      const body = document.createElement("div");
      body.className = "ledger-body";

      const titleLink = document.createElement("a");
      titleLink.className = "ledger-title-link";
      titleLink.href = v.video_url;
      titleLink.target = "_blank";
      titleLink.rel = "noopener";
      titleLink.textContent = v.plain_title || v.title;
      body.appendChild(titleLink);

      if (v.summary) {
        const summary = document.createElement("p");
        summary.className = "ledger-summary";
        summary.textContent = v.summary;
        body.appendChild(summary);
      }

      const meta = document.createElement("div");
      meta.className = "ledger-meta";

      const date = document.createElement("span");
      date.className = "ledger-date";
      date.textContent = formatDate(v.published_at);
      meta.appendChild(date);

      if (v.category) {
        const tag = document.createElement("span");
        tag.className = "ledger-tag";
        tag.textContent = v.category;
        meta.appendChild(tag);
      }

      li.appendChild(indexEl);
      li.appendChild(thumb);
      li.appendChild(body);
      li.appendChild(meta);
      frag.appendChild(li);
    });

    els.ledger.appendChild(frag);
  }

  function applyFilters() {
    const query = els.searchInput.value.trim().toLowerCase();
    const category = els.categorySelect.value;
    const sort = els.sortSelect.value;

    let result = allVideos.filter((v) => {
      const matchesCategory = !category || v.category === category;
      if (!matchesCategory) return false;
      if (!query) return true;
      const haystack = `${v.plain_title} ${v.title} ${v.summary} ${v.description}`.toLowerCase();
      return haystack.includes(query);
    });

    result.sort((a, b) => {
      const da = new Date(a.published_at || 0).getTime();
      const db = new Date(b.published_at || 0).getTime();
      return sort === "oldest" ? da - db : db - da;
    });

    els.resultCount.textContent = `${result.length}件を表示中`;
    els.emptyState.hidden = result.length !== 0;
    renderList(result);
  }

  function debounce(fn, ms) {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), ms);
    };
  }

  async function init() {
    try {
      allVideos = await loadData();
    } catch (err) {
      els.loadingState.textContent = "データの読み込みに失敗しました。時間をおいて再度お試しください。";
      console.error(err);
      return;
    }

    els.loadingState.hidden = true;
    populateCategoryOptions(allVideos);
    updateStats(allVideos);
    applyFilters();

    els.searchInput.addEventListener("input", debounce(applyFilters, 150));
    els.categorySelect.addEventListener("change", applyFilters);
    els.sortSelect.addEventListener("change", applyFilters);
  }

  init();
})();
