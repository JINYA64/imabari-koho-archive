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
    jump: document.getElementById("category-jump"),
    content: document.getElementById("overview-content"),
    loadingState: document.getElementById("loading-state"),
    lastUpdated: document.getElementById("last-updated"),
  };

  function formatDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
  }

  function slugify(text) {
    return "cat-" + Array.from(text)
      .map((c) => c.codePointAt(0).toString(16))
      .join("");
  }

  async function loadData() {
    const [videosRes, overviewsRes] = await Promise.all([
      fetch("data/videos.json"),
      fetch("data/category_overviews.json"),
    ]);

    if (!videosRes.ok) throw new Error("videos.json の取得に失敗しました");
    if (!overviewsRes.ok) throw new Error("category_overviews.json の取得に失敗しました");

    const videosData = await videosRes.json();
    const overviewsData = await overviewsRes.json();

    const videoMap = {};
    for (const v of videosData.videos || []) {
      videoMap[v.video_id] = v;
    }

    els.lastUpdated.textContent = overviewsData.generated_at
      ? `最終更新: ${formatDate(overviewsData.generated_at)}`
      : "";

    return { videoMap, categories: overviewsData.categories || {} };
  }

  function renderVideoChip(video) {
    const a = document.createElement("a");
    a.className = "video-chip";
    a.href = video.video_url;
    a.target = "_blank";
    a.rel = "noopener";

    const img = document.createElement("img");
    img.src = video.thumbnail_url || "";
    img.alt = "";
    img.loading = "lazy";
    a.appendChild(img);

    const title = document.createElement("span");
    title.className = "video-chip-title";
    title.textContent = video.title || "";
    a.appendChild(title);

    const date = document.createElement("span");
    date.className = "video-chip-date";
    date.textContent = formatDate(video.published_at);
    a.appendChild(date);

    return a;
  }

  function renderTopic(topic, videoMap) {
    const block = document.createElement("div");
    block.className = "topic-block";

    const title = document.createElement("h3");
    title.className = "topic-title";
    title.textContent = topic.topic_title;
    block.appendChild(title);

    const overview = document.createElement("p");
    overview.className = "topic-overview";
    overview.textContent = topic.overview;
    block.appendChild(overview);

    const videosWrap = document.createElement("div");
    videosWrap.className = "topic-videos";
    for (const vid of topic.video_ids || []) {
      const v = videoMap[vid];
      if (!v) continue;
      videosWrap.appendChild(renderVideoChip(v));
    }
    block.appendChild(videosWrap);

    return block;
  }

  function renderCategory(catName, catData, videoMap) {
    const section = document.createElement("section");
    section.className = "category-section";
    section.id = slugify(catName);

    const heading = document.createElement("h2");
    heading.className = "category-section-title";
    heading.textContent = catName;
    section.appendChild(heading);

    for (const topic of catData.topics || []) {
      section.appendChild(renderTopic(topic, videoMap));
    }

    return section;
  }

  async function init() {
    let data;
    try {
      data = await loadData();
    } catch (err) {
      els.loadingState.textContent = "データの読み込みに失敗しました。時間をおいて再度お試しください。";
      console.error(err);
      return;
    }

    els.loadingState.hidden = true;

    const orderedCats = CATEGORY_ORDER.filter((c) => data.categories[c] && (data.categories[c].topics || []).length);

    const jumpFrag = document.createDocumentFragment();
    for (const cat of orderedCats) {
      const a = document.createElement("a");
      a.href = `#${slugify(cat)}`;
      a.textContent = cat;
      jumpFrag.appendChild(a);
    }
    els.jump.appendChild(jumpFrag);

    const contentFrag = document.createDocumentFragment();
    for (const cat of orderedCats) {
      contentFrag.appendChild(renderCategory(cat, data.categories[cat], data.videoMap));
    }
    els.content.appendChild(contentFrag);
  }

  init();
})();
