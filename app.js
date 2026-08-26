(function () {
  const RED_MAX = 33;
  const BLUE_MAX = 16;
  const BLUE_BASE_PROBABILITY = 1 / BLUE_MAX;
  const BLUE_SIGNAL_MIN = 0.25;
  const BLUE_STAR_Z = 2;
  const RED_BASE_PROBABILITY = 6 / RED_MAX;
  const RED_SIGNAL_MIN = 0.18;
  const TOTAL_SINGLE = comb(33, 6) * 16;
  const MODEL_WEIGHTS = {
    shape: 0.36,
    crowd: 0.22,
    history: 0.18,
    blue: 0.1,
    dispersion: 0.14
  };
  const AI3_WEIGHTS = {
    history: 0.2,
    omission: 0.2,
    conversion: 0.15,
    probability: 0.15,
    machine: 0.2,
    simulation: 0.1
  };
  const AI3_MODEL_LABELS = [
    "历史频率/滑动窗口/移动平均",
    "遗漏周期/冷热转换/指数平滑",
    "Bayesian/Poisson/Markov/Monte Carlo",
    "KMeans/关联/熵值/相关性弱特征",
    "和值/跨度/连号/断区/同尾/012路/AC值"
  ];
  const TREND_WINDOW = 80;
  const AI_TASK_STORAGE_KEY = "ssqAiTaskId";
  const AI_REQUEST_STORAGE_KEY = "ssqAiClientRequestId";
  const AI_TASK_TIMEOUT_MS = 10 * 60 * 1000;
  const history = normalizeHistory(window.SSQ_HISTORY || []);
  let rng = Math.random;

  const els = {
    dataStatus: document.getElementById("dataStatus"),
    scopeSelect: document.getElementById("scopeSelect"),
    strategySelect: document.getElementById("strategySelect"),
    modeSelect: document.getElementById("modeSelect"),
    redCount: document.getElementById("redCount"),
    blueCount: document.getElementById("blueCount"),
    danCount: document.getElementById("danCount"),
    tuoCount: document.getElementById("tuoCount"),
    dtBlueCount: document.getElementById("dtBlueCount"),
    dantuoHelp: document.getElementById("dantuoHelp"),
    shapeFilter: document.getElementById("shapeFilter"),
    avoidPopular: document.getElementById("avoidPopular"),
    portfolioCount: document.getElementById("portfolioCount"),
    maxOverlap: document.getElementById("maxOverlap"),
    complexControls: document.getElementById("complexControls"),
    dantuoControls: document.getElementById("dantuoControls"),
    generateBtn: document.getElementById("generateBtn"),
    copyBtn: document.getElementById("copyBtn"),
    recommendation: document.getElementById("recommendation"),
    metrics: document.getElementById("metrics"),
    strategyCompare: document.getElementById("strategyCompare"),
    strategyResearch: document.getElementById("strategyResearch"),
    aiStatus: document.getElementById("aiStatus"),
    aiAnalyzeBtn: document.getElementById("aiAnalyzeBtn"),
    fillAiBtn: document.getElementById("fillAiBtn"),
    aiRecommendation: document.getElementById("aiRecommendation"),
    qualityPanel: document.getElementById("qualityPanel"),
    numberReasons: document.getElementById("numberReasons"),
    portfolioPanel: document.getElementById("portfolioPanel"),
    historyAnalysis: document.getElementById("historyAnalysis"),
    strategyNote: document.getElementById("strategyNote"),
    redHeatmap: document.getElementById("redHeatmap"),
    blueHeatmap: document.getElementById("blueHeatmap"),
    trendTable: document.getElementById("trendTable"),
    drawList: document.getElementById("drawList"),
    latestInfo: document.getElementById("latestInfo"),
    adminToken: document.getElementById("adminToken"),
    purchaseIssue: document.getElementById("purchaseIssue"),
    purchaseMode: document.getElementById("purchaseMode"),
    purchaseRed: document.getElementById("purchaseRed"),
    purchaseBlue: document.getElementById("purchaseBlue"),
    purchaseDan: document.getElementById("purchaseDan"),
    purchaseTuo: document.getElementById("purchaseTuo"),
    purchaseDtBlue: document.getElementById("purchaseDtBlue"),
    purchaseNote: document.getElementById("purchaseNote"),
    purchaseNormalFields: document.getElementById("purchaseNormalFields"),
    purchaseDantuoFields: document.getElementById("purchaseDantuoFields"),
    purchaseStatus: document.getElementById("purchaseStatus"),
    purchaseList: document.getElementById("purchaseList"),
    fillCurrentBtn: document.getElementById("fillCurrentBtn"),
    savePurchaseBtn: document.getElementById("savePurchaseBtn"),
    refreshPurchasesBtn: document.getElementById("refreshPurchasesBtn"),
    checkNowBtn: document.getElementById("checkNowBtn")
  };

  let currentSchemeText = "";
  let currentScheme = null;
  let currentAiResult = null;

  init();

  function init() {
    if (!history.length) {
      els.dataStatus.textContent = "没有读取到开奖数据";
      els.recommendation.innerHTML = "<p class='scheme-text'>请先运行 python3 fetch_history.py --start 2026001 --end 最新期号。</p>";
      return;
    }

    const latest = history[history.length - 1];
    els.dataStatus.textContent = `${history.length} 期数据，最新 ${latest.issue}`;
    els.latestInfo.textContent = `${latest.issue} / ${latest.date}`;

    bindEvents();
    renderStaticViews();
    generate();
    initPurchasePanel();
  }

  function bindEvents() {
    [els.scopeSelect, els.strategySelect, els.modeSelect, els.redCount, els.blueCount, els.danCount, els.tuoCount, els.dtBlueCount, els.shapeFilter, els.avoidPopular, els.portfolioCount, els.maxOverlap].forEach((el) => {
      el.addEventListener("change", generate);
    });

    els.modeSelect.addEventListener("change", () => {
      const mode = els.modeSelect.value;
      els.complexControls.classList.toggle("hidden", mode !== "complex");
      els.dantuoControls.classList.toggle("hidden", mode !== "dantuo");
      els.dantuoHelp.classList.toggle("hidden", mode !== "dantuo");
      generate();
    });

    els.generateBtn.addEventListener("click", generate);
    els.copyBtn.addEventListener("click", async () => {
      if (!currentSchemeText) return;
      await navigator.clipboard.writeText(currentSchemeText);
      els.copyBtn.textContent = "已复制";
      window.setTimeout(() => (els.copyBtn.textContent = "复制号码"), 1200);
    });

    els.purchaseMode.addEventListener("change", togglePurchaseMode);
    els.fillCurrentBtn.addEventListener("click", fillCurrentPurchase);
    els.savePurchaseBtn.addEventListener("click", savePurchase);
    els.refreshPurchasesBtn.addEventListener("click", loadPurchaseState);
    els.checkNowBtn.addEventListener("click", checkNow);
    els.aiAnalyzeBtn.addEventListener("click", analyzeWithAi);
    els.fillAiBtn.addEventListener("click", fillAiPurchase);
    els.adminToken.addEventListener("change", () => {
      localStorage.setItem("ssqAdminToken", els.adminToken.value.trim());
      loadPurchaseState();
    });
  }

  function renderStaticViews() {
    renderTrendTable();
    renderDrawList();
  }

  function generate() {
    rng = createRng(`${recommendationSeed()}|${randomEntropy()}`);
    const scope = getScopeHistory();
    const stats = buildStats(scope);
    const strategy = els.strategySelect.value;
    const mode = els.modeSelect.value;
    const scores = buildScores(stats, strategy, scope);
    const options = {
      shapeFilter: els.shapeFilter.checked,
      avoidPopular: els.avoidPopular.checked
    };
    const params = readModeParams();
    let scheme;

    scheme = buildScheme(mode, scores, strategy, options, params);

    renderRecommendation(scheme);
    renderMetrics(scheme);
    renderStrategyCompare(scheme, scores);
    renderQuality(scheme);
    renderNumberReasons(scheme, stats, scores);
    renderPortfolio(buildPortfolio(mode, scores, strategy, options, params, scheme));
    renderHeatmaps(stats, scheme);
    renderHistoryAnalysis(stats, scope);
    renderStrategyResearch();
  }

  function readModeParams() {
    const mode = els.modeSelect.value;
    if (mode === "single") {
      return { redCount: 6, blueCount: 1 };
    }
    if (mode === "dantuo") {
      const danCount = clampNumber(els.danCount.value, 1, 5);
      return {
        danCount,
        tuoCount: clampNumber(els.tuoCount.value, Math.max(6 - danCount, 4), 15),
        blueCount: clampNumber(els.dtBlueCount.value, 1, 6)
      };
    }
    return {
      redCount: clampNumber(els.redCount.value, 6, 12),
      blueCount: clampNumber(els.blueCount.value, 1, 6)
    };
  }

  function buildScheme(mode, scores, strategy, options, params) {
    if (strategy === "official") {
      return buildOfficialMachineScheme(mode, params);
    }
    if (mode === "single") {
      return buildComplexScheme(scores, 6, 1, strategy, options);
    }
    if (mode === "dantuo") {
      return buildDantuoScheme(scores, params.danCount, params.tuoCount, params.blueCount, strategy, options);
    }
    return buildComplexScheme(scores, params.redCount, params.blueCount, strategy, options);
  }

  function buildPortfolio(mode, scores, strategy, options, params, primary) {
    const targetCount = clampNumber(els.portfolioCount.value, 1, 8);
    const maxOverlap = clampNumber(els.maxOverlap.value, 0, 5);
    const schemes = [primary];

    while (schemes.length < targetCount) {
      let best = null;
      let bestScore = -Infinity;
      const attempts = strategy === "official" ? 1200 : 240;
      for (let i = 0; i < attempts; i++) {
        const candidate = buildScheme(mode, scores, strategy, options, params);
        if (schemes.some((scheme) => sameScheme(scheme, candidate))) continue;
        const overlap = Math.max(...schemes.map((scheme) => redOverlap(scheme.red, candidate.red)));
        if (overlap > maxOverlap) continue;
        if (strategy === "official") {
          best = candidate;
          break;
        }
        const score = schemeQualityScore(candidate, scores, options, schemes);
        if (score > bestScore) {
          best = candidate;
          bestScore = score;
        }
      }
      if (!best) break;
      schemes.push(best);
    }

    return schemes;
  }

  function getScopeHistory() {
    const value = els.scopeSelect.value;
    if (value === "all") return history.slice();
    return history.slice(-Number(value));
  }

  function normalizeHistory(rows) {
    return rows
      .map((row) => ({
        issue: String(row.issue),
        date: row.date || "",
        red: (row.red || []).map(Number).sort((a, b) => a - b),
        blue: Number(row.blue)
      }))
      .filter((row) => row.red.length === 6 && row.blue)
      .sort((a, b) => Number(a.issue) - Number(b.issue));
  }

  function buildStats(scope) {
    const redFreq = countRange(RED_MAX);
    const blueFreq = countRange(BLUE_MAX);
    const recentRows = scope.slice(-20);
    const redRecent = countRange(RED_MAX);
    const blueRecent = countRange(BLUE_MAX);
    const redOmit = {};
    const blueOmit = {};

    scope.forEach((row) => {
      row.red.forEach((n) => redFreq[n]++);
      blueFreq[row.blue]++;
    });

    recentRows.forEach((row) => {
      row.red.forEach((n) => redRecent[n]++);
      blueRecent[row.blue]++;
    });

    for (let n = 1; n <= RED_MAX; n++) {
      redOmit[n] = omission(scope, (row) => row.red.includes(n));
    }

    for (let n = 1; n <= BLUE_MAX; n++) {
      blueOmit[n] = omission(scope, (row) => row.blue === n);
    }

    return { redFreq, blueFreq, redRecent, blueRecent, redOmit, blueOmit, scopeSize: scope.length, recentSize: recentRows.length };
  }

  function buildScores(stats, strategy, rows) {
    const redSignals = buildRedSignals(stats);
    applyAi3Signals(redSignals, stats, "red", rows);
    const red = scoreRedRange(stats, strategy, redSignals);
    const blueSignals = buildBlueSignals(stats);
    applyAi3Signals(blueSignals, stats, "blue", rows);
    const blue = scoreBlueRange(stats, strategy, blueSignals);
    const latest = rows[rows.length - 1];
    const redStars = ai3Buckets(redSignals);
    const blueStars = ai3Buckets(blueSignals);
    const meta = {
      hotRed: topEntries(stats.redFreq, 8, "desc").map(([n]) => n),
      omitRed: topEntries(stats.redOmit, 8, "desc").map(([n]) => n),
      signalRed: topRedSignals(redSignals, 10).map(([n]) => n),
      latestRed: latest ? latest.red : [],
      hotBlue: topEntries(stats.blueFreq, 4, "desc").map(([n]) => n),
      omitBlue: topEntries(stats.blueOmit, 4, "desc").map(([n]) => n),
      signalBlue: topBlueSignals(blueSignals, 4).map(([n]) => n),
      starBlue: blueStars.five,
      starRed: redStars.five,
      fourRed: redStars.four,
      threeRed: redStars.three,
      fourBlue: blueStars.four,
      threeBlue: blueStars.three,
      ai3Weights: AI3_WEIGHTS,
      ai3Labels: AI3_MODEL_LABELS,
      redSignals,
      blueSignals,
      latestBlue: latest ? latest.blue : null
    };
    red.__meta = meta;
    blue.__meta = meta;
    return { red, blue, meta };
  }

  function applyAi3Signals(signals, stats, kind, rows) {
    const max = kind === "red" ? RED_MAX : BLUE_MAX;
    const baseProbability = kind === "red" ? RED_BASE_PROBABILITY : BLUE_BASE_PROBABILITY;
    const expectedGap = 1 / baseProbability;
    const raw = {};

    for (let n = 1; n <= max; n++) {
      const frequency = kind === "red" ? stats.redFreq[n] || 0 : stats.blueFreq[n] || 0;
      const recent20 = kind === "red" ? stats.redRecent[n] || 0 : stats.blueRecent[n] || 0;
      const recent5 = windowHitCount(n, 5, kind, rows);
      const recent15 = windowHitCount(n, 15, kind, rows);
      const recent30 = windowHitCount(n, 30, kind, rows);
      const gap = kind === "red" ? stats.redOmit[n] || 0 : stats.blueOmit[n] || 0;
      const middleGap = Math.exp(-Math.abs(gap - expectedGap) / (expectedGap * 1.25));
      const ewma = ewmaHitScore(n, kind, 0.16, rows);
      const bayes = bayesMean(n, kind, rows);
      const markov = markovNextScore(n, kind, rows);
      const poisson = middleGap;
      const hotCold = hotColdTurnScore(recent5, recent15, recent30);
      const cluster = numberClusterShapeScore(n, kind, rows);
      const relation = relationScore(n, kind, rows);
      const entropy = tailEntropyScore(n, kind, rows);
      const route012 = route012Score(n, kind, rows);
      const prime = primeCompositeScore(n, kind, rows);
      const golden = goldenFibonacciScore(n, kind);

      raw[n] = {
        history: frequency * 0.45 + recent20 * 0.25 + recent15 * 0.2 + ewma * 10,
        omission: middleGap * 0.7 + Math.min(gap / (expectedGap * 2.5), 1) * 0.3,
        conversion: hotCold,
        probability: bayes * 0.4 + markov * 0.25 + poisson * 0.25 + relation * 0.1,
        machine: ewma * 0.25 + cluster * 0.2 + relation * 0.2 + entropy * 0.15 + route012 * 0.08 + prime * 0.06 + golden * 0.06,
        gap,
        recent5,
        recent15,
        recent30
      };
    }

    const simulation = ai3Simulation(raw, kind);
    const normalized = {};
    ["history", "omission", "conversion", "probability", "machine"].forEach((name) => {
      normalized[name] = normalizeMetric(raw, name, max);
    });

    for (let n = 1; n <= max; n++) {
      const components = {
        history: normalized.history[n],
        omission: normalized.omission[n],
        conversion: normalized.conversion[n],
        probability: normalized.probability[n],
        machine: normalized.machine[n],
        simulation: simulation[n] || 0
      };
      const score =
        components.history * AI3_WEIGHTS.history +
        components.omission * AI3_WEIGHTS.omission +
        components.conversion * AI3_WEIGHTS.conversion +
        components.probability * AI3_WEIGHTS.probability +
        components.machine * AI3_WEIGHTS.machine +
        components.simulation * AI3_WEIGHTS.simulation;

      signals[n].ai3 = {
        score,
        components,
        gap: raw[n].gap,
        recent5: raw[n].recent5,
        recent15: raw[n].recent15,
        recent30: raw[n].recent30
      };
      signals[n].starred = signals[n].starred || score >= 0.72;
    }
  }

  function normalizeMetric(raw, field, max) {
    let min = Infinity;
    let high = -Infinity;
    for (let n = 1; n <= max; n++) {
      min = Math.min(min, raw[n][field]);
      high = Math.max(high, raw[n][field]);
    }
    const span = high - min || 1;
    const result = {};
    for (let n = 1; n <= max; n++) {
      result[n] = clamp01((raw[n][field] - min) / span);
    }
    return result;
  }

  function ai3Simulation(raw, kind) {
    const max = kind === "red" ? RED_MAX : BLUE_MAX;
    const count = kind === "red" ? 6 : 2;
    const trials = kind === "red" ? 2600 : 1600;
    const weights = {};
    const include = countRange(max);
    const localRandom = createRng(`${recommendationSeed()}-${kind}-ai3`);

    for (let n = 1; n <= max; n++) {
      weights[n] = Math.max(0.02, raw[n].history * 0.42 + raw[n].omission * 0.24 + raw[n].conversion * 0.18 + raw[n].probability * 0.16);
    }

    for (let i = 0; i < trials; i++) {
      const picked = weightedPickSet(weights, count, max, localRandom);
      if (kind === "red") {
        const sum = picked.reduce((total, n) => total + n, 0);
        const zones = zoneCounts(picked);
        const odd = picked.filter((n) => n % 2 === 1).length;
        const ac = acValue(picked);
        const shapeOk = sum >= 70 && sum <= 145 && Math.max(...zones) <= 4 && odd >= 1 && odd <= 5 && ac >= 4;
        if (!shapeOk) continue;
      }
      picked.forEach((n) => include[n]++);
    }

    const maxInclude = Math.max(...Object.values(include), 1);
    const result = {};
    for (let n = 1; n <= max; n++) {
      result[n] = include[n] / maxInclude;
    }
    return result;
  }

  function weightedPickSet(weights, count, max, randomFn) {
    const picked = new Set();
    while (picked.size < count) {
      let total = 0;
      for (let n = 1; n <= max; n++) {
        if (!picked.has(n)) total += weights[n] || 0.01;
      }
      let roll = randomFn() * total;
      for (let n = 1; n <= max; n++) {
        if (picked.has(n)) continue;
        roll -= weights[n] || 0.01;
        if (roll <= 0) {
          picked.add(n);
          break;
        }
      }
    }
    return Array.from(picked).sort((a, b) => a - b);
  }

  function windowHitCount(n, size, kind, rows) {
    return rows.slice(-size).reduce((sum, row) => {
      if (kind === "red") return sum + (row.red.includes(n) ? 1 : 0);
      return sum + (row.blue === n ? 1 : 0);
    }, 0);
  }

  function ewmaHitScore(n, kind, alpha, rows) {
    let value = 0;
    rows.forEach((row) => {
      const hit = kind === "red" ? row.red.includes(n) : row.blue === n;
      value = alpha * (hit ? 1 : 0) + (1 - alpha) * value;
    });
    return value;
  }

  function bayesMean(n, kind, rows) {
    const probability = kind === "red" ? RED_BASE_PROBABILITY : BLUE_BASE_PROBABILITY;
    const hits = rows.reduce((sum, row) => {
      if (kind === "red") return sum + (row.red.includes(n) ? 1 : 0);
      return sum + (row.blue === n ? 1 : 0);
    }, 0);
    const strength = kind === "red" ? 10 : 8;
    return (probability * strength + hits) / (strength + Math.max(1, rows.length));
  }

  function markovNextScore(n, kind, rows) {
    const latest = rows[rows.length - 1];
    if (!latest || rows.length < 3) return 0;
    let matched = 0;
    let hits = 0;
    for (let i = 0; i < rows.length - 1; i++) {
      const prior = rows[i];
      const next = rows[i + 1];
      const related = redOverlap(prior.red, latest.red) >= 1 || Math.abs(prior.blue - latest.blue) <= 1;
      if (!related) continue;
      matched++;
      if (kind === "red" && next.red.includes(n)) hits++;
      if (kind === "blue" && next.blue === n) hits++;
    }
    return matched ? hits / matched : 0;
  }

  function hotColdTurnScore(recent5, recent15, recent30) {
    const early15 = Math.max(0, recent15 - recent5) / 10;
    const early30 = Math.max(0, recent30 - recent15) / 15;
    const near = recent5 / 5;
    const warming = Math.max(0, near - early15);
    const rebound = recent5 === 0 && recent15 <= 1 && recent30 >= 1 ? 0.25 : 0;
    return near * 0.45 + early15 * 0.25 + early30 * 0.15 + warming * 0.15 + rebound;
  }

  function numberClusterShapeScore(n, kind, rows) {
    if (kind === "blue") return 0.5 + (n <= 8 ? 0.05 : -0.02);
    const latest = rows[rows.length - 1];
    const zone = n <= 11 ? 0 : n <= 22 ? 1 : 2;
    const latestZones = latest ? zoneCounts(latest.red) : [2, 2, 2];
    const zoneNeed = 1 - latestZones[zone] / 6;
    const centerScore = 1 - Math.abs(n - 17) / 17;
    return clamp01(zoneNeed * 0.55 + centerScore * 0.45);
  }

  function relationScore(n, kind, rows) {
    const latest = rows[rows.length - 1];
    if (!latest) return 0;
    if (kind === "blue") {
      return 1 - Math.min(Math.abs(n - latest.blue), 8) / 8;
    }
    let coHit = 0;
    let base = 0;
    rows.forEach((row) => {
      if (!row.red.includes(n)) return;
      base++;
      coHit += redOverlap(row.red, latest.red);
    });
    return base ? clamp01(coHit / (base * 2.2)) : 0;
  }

  function tailEntropyScore(n, kind, rows) {
    if (kind === "blue") return 1 - Math.abs((n % 4) - 1.5) / 2.5;
    const tail = n % 10;
    const recent = rows.slice(-20).flatMap((row) => row.red.map((value) => value % 10));
    const count = recent.filter((value) => value === tail).length;
    return clamp01(1 - Math.abs(count - 12) / 12);
  }

  function route012Score(n, kind, rows) {
    if (kind === "blue") return 1 - Math.abs((n % 3) - 1) / 2;
    const route = n % 3;
    const recentRoutes = rows.slice(-20).flatMap((row) => row.red.map((value) => value % 3));
    const count = recentRoutes.filter((value) => value === route).length;
    return clamp01(1 - Math.abs(count - 40) / 40);
  }

  function primeCompositeScore(n, kind, rows) {
    if (kind === "blue") return isPrime(n) ? 0.58 : 0.48;
    const recentPrimes = rows.slice(-20).reduce((sum, row) => sum + row.red.filter(isPrime).length, 0);
    const target = 20 * 2.3;
    return isPrime(n) ? clamp01(1 - Math.max(0, recentPrimes - target) / target) : clamp01(1 - Math.max(0, target - recentPrimes) / target);
  }

  function goldenFibonacciScore(n, kind) {
    const fibs = kind === "red" ? [1, 2, 3, 5, 8, 13, 21, 34] : [1, 2, 3, 5, 8, 13];
    const nearest = Math.min(...fibs.map((value) => Math.abs(value - n)));
    const goldenCenter = kind === "red" ? 20 : 10;
    return clamp01((1 - Math.min(nearest, 5) / 5) * 0.45 + (1 - Math.abs(n - goldenCenter) / goldenCenter) * 0.55);
  }

  function acValue(nums) {
    const sorted = nums.slice().sort((a, b) => a - b);
    const diffs = new Set();
    for (let i = 0; i < sorted.length; i++) {
      for (let j = i + 1; j < sorted.length; j++) {
        diffs.add(sorted[j] - sorted[i]);
      }
    }
    return diffs.size - (sorted.length - 1);
  }

  function isPrime(n) {
    if (n < 2) return false;
    for (let i = 2; i * i <= n; i++) {
      if (n % i === 0) return false;
    }
    return true;
  }

  function ai3Buckets(signals) {
    const entries = Object.entries(signals)
      .map(([n, signal]) => [Number(n), signal.ai3 ? signal.ai3.score : 0])
      .sort((a, b) => b[1] - a[1] || a[0] - b[0]);
    return {
      five: entries.slice(0, 7).map(([n]) => n),
      four: entries.slice(7, 18).map(([n]) => n),
      three: entries.slice(18, 28).map(([n]) => n)
    };
  }

  function buildRedSignals(stats) {
    const result = {};
    const scopeSize = Math.max(1, stats.scopeSize || 0);
    const recentSize = Math.max(1, stats.recentSize || 0);

    for (let n = 1; n <= RED_MAX; n++) {
      const freqZ = binomialZ(stats.redFreq[n] || 0, scopeSize, RED_BASE_PROBABILITY);
      const recentZ = binomialZ(stats.redRecent[n] || 0, recentSize, RED_BASE_PROBABILITY);
      const hotEvidence = clamp01(Math.max(0, freqZ) / 3 * 0.6 + Math.max(0, recentZ) / 3 * 0.4);
      const coldEvidence = clamp01(Math.max(0, -freqZ) / 3 * 0.55 + Math.max(0, -recentZ) / 3 * 0.45);
      const omissionTail = clamp01(1 - Math.pow(1 - RED_BASE_PROBABILITY, stats.redOmit[n] || 0));

      result[n] = {
        freqZ,
        recentZ,
        hotEvidence,
        coldEvidence,
        omissionTail,
        starred: freqZ >= 1.8 || (freqZ >= 1.2 && recentZ >= 1.2)
      };
    }

    return result;
  }

  function buildBlueSignals(stats) {
    const result = {};
    const scopeSize = Math.max(1, stats.scopeSize || 0);
    const recentSize = Math.max(1, stats.recentSize || 0);

    for (let n = 1; n <= BLUE_MAX; n++) {
      const freqZ = binomialZ(stats.blueFreq[n] || 0, scopeSize, BLUE_BASE_PROBABILITY);
      const recentZ = binomialZ(stats.blueRecent[n] || 0, recentSize, BLUE_BASE_PROBABILITY);
      const hotEvidence = clamp01(Math.max(0, freqZ) / 3 * 0.65 + Math.max(0, recentZ) / 3 * 0.35);
      const coldEvidence = clamp01(Math.max(0, -freqZ) / 3 * 0.65 + Math.max(0, -recentZ) / 3 * 0.35);
      const omissionTail = clamp01(1 - Math.pow(1 - BLUE_BASE_PROBABILITY, stats.blueOmit[n] || 0));

      result[n] = {
        freqZ,
        recentZ,
        hotEvidence,
        coldEvidence,
        omissionTail,
        starred: freqZ >= BLUE_STAR_Z || (freqZ >= 1.5 && recentZ >= 1.5)
      };
    }

    return result;
  }

  function scoreBlueRange(stats, strategy, signals) {
    const result = {};

    for (let n = 1; n <= BLUE_MAX; n++) {
      const signal = signals[n];
      const jitter = random01();
      let score;

      if (strategy === "fair" || strategy === "random") {
        score = jitter;
      } else if (strategy === "hot") {
        score = ai3StrategyScore(signal, strategy, jitter);
      } else if (strategy === "cold") {
        score = ai3StrategyScore(signal, strategy, jitter);
      } else if (strategy === "omission") {
        score = ai3StrategyScore(signal, strategy, jitter);
      } else if (strategy === "mixed") {
        score = ai3StrategyScore(signal, strategy, jitter);
      } else {
        score = ai3StrategyScore(signal, strategy, jitter);
      }

      result[n] = clamp01(score);
    }

    return result;
  }

  function scoreRedRange(stats, strategy, signals) {
    const result = {};

    for (let n = 1; n <= RED_MAX; n++) {
      const signal = signals[n];
      const jitter = random01();
      let score;

      if (strategy === "fair" || strategy === "random") {
        score = jitter;
      } else if (strategy === "balanced") {
        score = ai3StrategyScore(signal, strategy, jitter);
      } else
      if (strategy === "hot") {
        score = ai3StrategyScore(signal, strategy, jitter);
      } else if (strategy === "omission") {
        score = ai3StrategyScore(signal, strategy, jitter);
      } else if (strategy === "cold") {
        score = ai3StrategyScore(signal, strategy, jitter);
      } else if (strategy === "mixed") {
        score = ai3StrategyScore(signal, strategy, jitter);
      } else {
        score = ai3StrategyScore(signal, strategy, jitter);
      }

      result[n] = clamp(score, 0.05, 1.0);
    }

    return result;
  }

  function ai3StrategyScore(signal, strategy, jitter) {
    const ai = signal.ai3 || { score: 0.5, components: {} };
    const c = ai.components || {};
    let score = ai.score;

    if (strategy === "hot") {
      score = score * 0.82 + (c.history || 0) * 0.12 + (c.machine || 0) * 0.06;
    } else if (strategy === "omission") {
      score = score * 0.78 + (c.omission || 0) * 0.16 + (c.probability || 0) * 0.06;
    } else if (strategy === "cold") {
      score = score * 0.76 + (1 - signal.hotEvidence) * 0.12 + (c.omission || 0) * 0.12;
    } else if (strategy === "mixed") {
      score = score * 0.86 + (c.conversion || 0) * 0.08 + (c.simulation || 0) * 0.06;
    } else {
      score = score * 0.9 + (c.probability || 0) * 0.05 + (c.simulation || 0) * 0.05;
    }

    return clamp(score + jitter * 0.035, 0.05, 1);
  }

  function buildComplexScheme(scores, redCount, blueCount, strategy, options) {
    const red = chooseRedSet(scores.red, redCount, strategy, options);
    const blue = chooseBlueSet(scores.blue, blueCount, strategy);
    return {
      type: redCount === 6 && blueCount === 1 ? "single" : "complex",
      red,
      blue,
      blueStars: blue.filter((n) => (scores.meta.starBlue || []).includes(n)),
      redCount,
      blueCount,
      betCount: comb(redCount, 6) * blueCount,
      dantuo: null
    };
  }

  function buildDantuoScheme(scores, danCount, tuoCount, blueCount, strategy, options) {
    const totalRed = Math.min(RED_MAX, danCount + tuoCount);
    const selected = chooseRedSet(scores.red, totalRed, strategy, options);
    const confidence = selected
      .map((n) => ({ n, score: scores.red[n] + (n <= 16 ? 0.02 : 0) }))
      .sort((a, b) => b.score - a.score || a.n - b.n);
    const dan = confidence.slice(0, danCount).map((item) => item.n).sort((a, b) => a - b);
    const tuo = selected.filter((n) => !dan.includes(n)).sort((a, b) => a - b);
    const blue = chooseBlueSet(scores.blue, blueCount, strategy);
    return {
      type: "dantuo",
      red: selected,
      blue,
      blueStars: blue.filter((n) => (scores.meta.starBlue || []).includes(n)),
      redCount: selected.length,
      blueCount,
      betCount: comb(tuo.length, 6 - dan.length) * blueCount,
      dantuo: { dan, tuo }
    };
  }

  function buildOfficialMachineScheme(mode, params) {
    if (mode === "dantuo") {
      const totalRed = Math.min(RED_MAX, params.danCount + params.tuoCount);
      const selected = chooseOfficialRedSet(totalRed);
      const shuffled = shuffle(selected);
      const dan = shuffled.slice(0, params.danCount).sort((a, b) => a - b);
      const tuo = shuffled.slice(params.danCount).sort((a, b) => a - b);
      const blue = chooseUniformSet(params.blueCount, BLUE_MAX);
      return {
        type: "dantuo",
        red: selected,
        blue,
        blueStars: [],
        redCount: selected.length,
        blueCount: blue.length,
        betCount: comb(tuo.length, 6 - dan.length) * blue.length,
        dantuo: { dan, tuo }
      };
    }

    const redCount = mode === "single" ? 6 : params.redCount;
    const blueCount = mode === "single" ? 1 : params.blueCount;
    const red = chooseOfficialRedSet(redCount);
    const blue = chooseUniformSet(blueCount, BLUE_MAX);
    return {
      type: redCount === 6 && blueCount === 1 ? "single" : "complex",
      red,
      blue,
      blueStars: [],
      redCount,
      blueCount,
      betCount: comb(redCount, 6) * blueCount,
      dantuo: null
    };
  }

  function chooseRedSet(scoreMap, count, strategy, options) {
    if (strategy === "fair" || strategy === "random" || strategy === "official") {
      return chooseFairRedSet(count, options).sort((a, b) => a - b);
    }

    let best = null;
    let bestScore = -Infinity;
    const attempts = 420;

    for (let i = 0; i < attempts; i++) {
      const picked = chooseNumberSet(scoreMap, count, RED_MAX);
      const score = redQualityScore(picked, scoreMap, options);
      if (score > bestScore) {
        best = picked;
        bestScore = score;
      }
    }

    return best.sort((a, b) => a - b);
  }

  function chooseBlueSet(scoreMap, count, strategy) {
    if (strategy === "fair" || strategy === "random" || strategy === "official") {
      return chooseUniformSet(count, BLUE_MAX);
    }
    let best = null;
    let bestScore = -Infinity;
    for (let i = 0; i < 100; i++) {
      const picked = chooseNumberSet(scoreMap, count, BLUE_MAX);
      const score = blueQualityScore(picked, scoreMap);
      if (score > bestScore) {
        best = picked;
        bestScore = score;
      }
    }
    return best.sort((a, b) => a - b);
  }

  function chooseFairRedSet(count, options) {
    let picked = chooseUniformSet(count, RED_MAX);
    if (!options.shapeFilter && !options.avoidPopular) return picked;

    for (let i = 0; i < 80; i++) {
      const candidate = chooseUniformSet(count, RED_MAX);
      const shapeOk = !options.shapeFilter || shapeQualityScore(candidate) >= 0.45;
      const crowdOk = !options.avoidPopular || staticCrowdRiskScore(candidate) < 1.8;
      if (shapeOk && crowdOk) {
        picked = candidate;
        break;
      }
    }

    return picked;
  }

  function chooseOfficialRedSet(count) {
    let picked = chooseUniformSet(count, RED_MAX);
    if (!els.shapeFilter.checked) return picked;

    for (let i = 0; i < 120; i++) {
      const candidate = chooseUniformSet(count, RED_MAX);
      if (officialShapeOk(candidate)) return candidate;
      picked = candidate;
    }

    return picked;
  }

  function officialShapeOk(nums) {
    const zones = zoneCounts(nums);
    if (zones.some((count) => count === 0)) return false;

    const odd = nums.filter((n) => n % 2 === 1).length;
    const small = nums.filter((n) => n <= 16).length;
    const maxOddSkew = nums.length <= 6 ? 5 : nums.length - 1;
    if (odd === 0 || odd === nums.length || odd >= maxOddSkew + 1 || nums.length - odd >= maxOddSkew + 1) return false;
    if (small === 0 || small === nums.length) return false;

    return true;
  }

  function zoneCounts(nums) {
    return [
      nums.filter((n) => n <= 11).length,
      nums.filter((n) => n >= 12 && n <= 22).length,
      nums.filter((n) => n >= 23).length
    ];
  }

  function chooseUniformSet(count, max) {
    const picked = new Set();
    while (picked.size < count) {
      picked.add(1 + Math.floor(random01() * max));
    }
    return Array.from(picked).sort((a, b) => a - b);
  }

  function shuffle(nums) {
    const copy = nums.slice();
    for (let i = copy.length - 1; i > 0; i--) {
      const j = Math.floor(random01() * (i + 1));
      [copy[i], copy[j]] = [copy[j], copy[i]];
    }
    return copy;
  }

  function chooseNumberSet(scoreMap, count, max) {
    const picked = new Set();
    const floor = 0.04;

    while (picked.size < count) {
      const pool = [];
      let total = 0;
      for (let n = 1; n <= max; n++) {
        if (picked.has(n)) continue;
        const weight = Math.max(floor, scoreMap[n] || floor);
        pool.push({ n, weight });
        total += weight;
      }

      let roll = random01() * total;
      for (const item of pool) {
        roll -= item.weight;
        if (roll <= 0) {
          picked.add(item.n);
          break;
        }
      }
    }

    return Array.from(picked).sort((a, b) => a - b);
  }

  function shapeScore(nums) {
    const count = nums.length;
    const odd = nums.filter((n) => n % 2 === 1).length;
    const small = nums.filter((n) => n <= 16).length;
    const zones = [
      nums.filter((n) => n <= 11).length,
      nums.filter((n) => n >= 12 && n <= 22).length,
      nums.filter((n) => n >= 23).length
    ];
    const sum = nums.reduce((a, b) => a + b, 0);
    const targetSum = count * 17;
    let score = 0;

    score += 1 - Math.abs(odd - count / 2) / count;
    score += 1 - Math.abs(small - count / 2) / count;
    score += zones.every(Boolean) ? 0.6 : -0.4;
    score += Math.max(0, 1 - Math.abs(sum - targetSum) / targetSum);

    return score;
  }

  function shapeQualityScore(nums) {
    const count = nums.length;
    const odd = nums.filter((n) => n % 2 === 1).length;
    const small = nums.filter((n) => n <= 16).length;
    const zones = [
      nums.filter((n) => n <= 11).length,
      nums.filter((n) => n >= 12 && n <= 22).length,
      nums.filter((n) => n >= 23).length
    ];
    const sum = nums.reduce((a, b) => a + b, 0);
    const targetSum = count * 17;
    const oddScore = 1 - Math.abs(odd - count / 2) / count;
    const sizeScore = 1 - Math.abs(small - count / 2) / count;
    const zoneScore = zones.filter(Boolean).length / 3;
    const sumScore = Math.max(0, 1 - Math.abs(sum - targetSum) / targetSum);
    const runPenalty = Math.max(0, maxConsecutiveRun(nums) - 2) * 0.18;
    return clamp01((oddScore + sizeScore + zoneScore + sumScore) / 4 - runPenalty);
  }

  function redQualityScore(nums, scoreMap, options) {
    const meta = scoreMap.__meta || {};
    const historyScore = averageScore(nums, scoreMap) * 0.35 + redRuleScore(nums, meta) * 0.65;
    const shapeScoreValue = options.shapeFilter ? shapeQualityScore(nums) : 0.5;
    const crowdScore = options.avoidPopular ? 1 - Math.min(staticCrowdRiskScore(nums) / 2.5, 1) : 0.5;
    return (
      MODEL_WEIGHTS.history * historyScore +
      MODEL_WEIGHTS.shape * shapeScoreValue +
      MODEL_WEIGHTS.crowd * crowdScore
    );
  }

  function redRuleScore(nums, meta) {
    const hot = countOverlap(nums, meta.hotRed || []);
    const omit = countOverlap(nums, meta.omitRed || []);
    const repeat = countOverlap(nums, meta.latestRed || []);
    const hotScore = rangeScore(hot, 1, 2, 4);
    const omitScore = rangeScore(omit, 1, 2, 4);
    const repeatScore = rangeScore(repeat, 1, 2, 4);
    return clamp01(hotScore * 0.38 + omitScore * 0.38 + repeatScore * 0.24);
  }

  function blueQualityScore(nums, scoreMap) {
    const meta = scoreMap.__meta || {};
    const historyScore = averageScore(nums, scoreMap);
    const splitScore = nums.length > 1 ? blueSpreadScore(nums) : historyScore;
    const repeatPenalty = latestBluePenalty(nums);
    const ruleScore = blueRuleScore(nums, meta);
    return clamp01(historyScore * 0.35 + splitScore * 0.25 + repeatPenalty * 0.1 + ruleScore * 0.3);
  }

  function blueRuleScore(nums, meta) {
    const signal = countOverlap(nums, meta.signalBlue || []);
    const latestRepeat = meta.latestBlue && nums.includes(meta.latestBlue) ? 1 : 0;
    const signalScore = clamp01(0.5 + signal / Math.max(1, nums.length) * 0.5);
    return clamp01(signalScore * 0.55 + (latestRepeat ? 0.85 : 1) * 0.45);
  }

  function latestBluePenalty(nums) {
    const latest = history[history.length - 1];
    if (!latest) return 0.5;
    return nums.includes(latest.blue) ? 0.85 : 1;
  }

  function blueSpreadScore(nums) {
    if (nums.length <= 1) return 0.5;
    const sorted = nums.slice().sort((a, b) => a - b);
    const span = sorted[sorted.length - 1] - sorted[0];
    return clamp01(span / 15);
  }

  function schemeQualityScore(scheme, scores, options, existingSchemes) {
    const intrinsic =
      redQualityScore(scheme.red, scores.red, options) +
      MODEL_WEIGHTS.blue * blueQualityScore(scheme.blue, scores.blue);
    const dispersion = existingSchemes && existingSchemes.length
      ? dispersionQuality(scheme, existingSchemes)
      : 0.5;
    const blueDispersion = existingSchemes && existingSchemes.length
      ? blueDispersionQuality(scheme, existingSchemes)
      : 0.5;
    return intrinsic + MODEL_WEIGHTS.dispersion * (dispersion * 0.8 + blueDispersion * 0.2);
  }

  function dispersionQuality(candidate, existingSchemes) {
    const maxOverlap = Math.max(...existingSchemes.map((scheme) => redOverlap(scheme.red, candidate.red)));
    const base = Math.max(6, Math.min(candidate.red.length, ...existingSchemes.map((scheme) => scheme.red.length)));
    return clamp01(1 - maxOverlap / base);
  }

  function blueDispersionQuality(candidate, existingSchemes) {
    const used = new Set(existingSchemes.flatMap((scheme) => scheme.blue));
    const repeats = candidate.blue.filter((n) => used.has(n)).length;
    return clamp01(1 - repeats / Math.max(1, candidate.blue.length));
  }

  function popularRiskScore(nums) {
    const sorted = nums.slice().sort((a, b) => a - b);
    const latest = history[history.length - 1];
    const latestSet = new Set(latest ? latest.red : []);
    const birthdayOnly = sorted.every((n) => n <= 31);
    const overlapLatest = sorted.filter((n) => latestSet.has(n)).length;
    const tailCounts = {};
    let maxTail = 0;
    let maxRun = 1;
    let currentRun = 1;
    let risk = 0;

    for (let i = 0; i < sorted.length; i++) {
      const tail = sorted[i] % 10;
      tailCounts[tail] = (tailCounts[tail] || 0) + 1;
      maxTail = Math.max(maxTail, tailCounts[tail]);
      if (i > 0 && sorted[i] === sorted[i - 1] + 1) {
        currentRun++;
        maxRun = Math.max(maxRun, currentRun);
      } else {
        currentRun = 1;
      }
    }

    if (birthdayOnly) risk += 0.8;
    if (maxRun >= 3) risk += (maxRun - 2) * 0.7;
    if (maxTail >= 3) risk += (maxTail - 2) * 0.45;
    if (overlapLatest >= 4) risk += (overlapLatest - 3) * 0.6;
    if (sorted.every((n) => n % 2 === 0) || sorted.every((n) => n % 2 === 1)) risk += 1.2;
    if (sorted.every((n) => n <= 16) || sorted.every((n) => n >= 17)) risk += 1.2;

    return risk;
  }

  function renderRecommendation(scheme) {
    currentScheme = scheme;
    const typeName = scheme.type === "dantuo" ? "胆拖" : scheme.type === "single" ? "单式" : "复式";
    const strategyNames = {
      official: "官方机选模拟：随机生成，不看历史；勾选形态过滤时控制三区/奇偶/大小极端",
      fair: "均匀机选：完全按随机抽样，不引入历史偏置",
      balanced: "AI 3.0 综合评分：50+统计指标、概率模型、机器学习弱特征和随机模拟集成",
      hot: "AI 3.0 热号偏向：综合评分上调历史走势和滑动窗口信号",
      omission: "AI 3.0 遗漏回补：综合评分上调遗漏周期和概率回补信号",
      cold: "AI 3.0 冷号逆向：综合评分保留冷转热和遗漏尾部信号",
      mixed: "AI 3.0 冷热混合：综合评分强调冷热转换和模拟分散",
      random: "纯随机底池：与机选等价"
    };
    els.strategyNote.textContent = strategyNames[els.strategySelect.value];

    const redHtml = scheme.type === "dantuo"
      ? `<div class="ball-row"><span class="tag">胆码</span>${ballsHtml(scheme.dantuo.dan, "red")}</div>
         <div class="ball-row"><span class="tag">拖码</span>${ballsHtml(scheme.dantuo.tuo, "red")}</div>`
      : `<div class="ball-row"><span class="tag">红球</span>${ballsHtml(scheme.red, "red")}</div>`;

    const blueHtml = `<div class="ball-row"><span class="tag">蓝球</span>${ballsHtml(scheme.blue, "blue", new Set(scheme.blueStars || []))}</div>`;
    const text = scheme.type === "dantuo"
      ? `${typeName} 胆:${formatNums(scheme.dantuo.dan)} 拖:${formatNums(scheme.dantuo.tuo)} 蓝:${formatNums(scheme.blue)}`
      : `${typeName} 红:${formatNums(scheme.red)} 蓝:${formatNums(scheme.blue)}`;

    currentSchemeText = text;
    els.recommendation.innerHTML = `${redHtml}${blueHtml}<p class="scheme-text">${escapeHtml(text)}</p>`;
  }

  function renderMetrics(scheme) {
    const jackpot = scheme.betCount / TOTAL_SINGLE;
    const anyPrize = anyPrizeProbability(scheme);
    const cost = scheme.betCount * 2;
    els.metrics.innerHTML = [
      metricHtml("覆盖注数", `${scheme.betCount} 注`, "复式展开后的单注数量"),
      metricHtml("参考成本", `${cost} 元`, "按每注 2 元计算"),
      metricHtml("头奖概率", oneIn(jackpot), "只表示覆盖概率"),
      metricHtml("任意奖概率", `${(anyPrize * 100).toFixed(2)}%`, oneIn(anyPrize)),
      metricHtml("分奖风险", crowdRiskLabel(popularRiskScore(scheme.red)), "大众号码形态估计")
    ].join("");
  }

  function renderStrategyCompare(scheme, scores) {
    if (els.strategySelect.value === "official") {
      els.strategyCompare.innerHTML = `
        <div class="subhead"><h3>官方机选口径</h3><span>按公开规则做等概率模拟</span></div>
        <div class="compare-grid">
          <div class="compare-card">
            <strong>公开口径</strong>
            <span>官方规则只说明机选由投注机随机产生投注号码，没有公开热号、遗漏、和值或形态过滤算法。</span>
          </div>
          <div class="compare-card">
            <strong>当前模拟</strong>
            <span>红球从 1-33 随机抽取且不重复，蓝球从 1-16 随机抽取；勾选形态过滤时要求低/中/高三区都有覆盖，并剔除奇偶、大小极端组合。</span>
          </div>
        </div>
      `;
      return;
    }

    const meta = scores.meta || {};
    const hot = countOverlap(scheme.red, meta.hotRed || []);
    const omit = countOverlap(scheme.red, meta.omitRed || []);
    const redSignal = countOverlap(scheme.red, meta.starRed || []);
    const repeat = countOverlap(scheme.red, meta.latestRed || []);
    const blueSignal = countOverlap(scheme.blue, meta.starBlue || []);
    const blueStar = countOverlap(scheme.blue, meta.starBlue || []);
    const blueRepeat = meta.latestBlue && scheme.blue.includes(meta.latestBlue) ? 1 : 0;
    const weights = meta.ai3Weights || AI3_WEIGHTS;
    const starRed = (meta.starRed || []).map(pad).join(" ");
    const starBlue = (meta.starBlue || []).map(pad).join(" ");

    els.strategyCompare.innerHTML = `
      <div class="subhead"><h3>AI 3.0 评分报告</h3><span>统计指标 + 概率模型 + 机器学习弱特征 + 随机模拟</span></div>
      <div class="compare-grid">
        <div class="compare-card">
          <strong>模型权重</strong>
          <span>历史走势 ${(weights.history * 100).toFixed(0)}%，遗漏周期 ${(weights.omission * 100).toFixed(0)}%，冷热转换 ${(weights.conversion * 100).toFixed(0)}%，概率模型 ${(weights.probability * 100).toFixed(0)}%，机器学习 ${(weights.machine * 100).toFixed(0)}%，随机模拟 ${(weights.simulation * 100).toFixed(0)}%。</span>
        </div>
        <div class="compare-card">
          <strong>五星池</strong>
          <span>红球 ${starRed || "无"}；蓝球 ${starBlue || "无"}。当前方案含红球五星 ${redSignal} 个、蓝球五星 ${blueSignal} 个。</span>
        </div>
        <div class="compare-card">
          <strong>票面校验</strong>
          <span>当前红球含高频 ${hot} 个、遗漏信号 ${omit} 个、上期重号 ${repeat} 个；蓝球 ${blueStar} 个星标，${blueRepeat ? "含上期蓝" : "未重复上期蓝"}。</span>
        </div>
        <div class="compare-card">
          <strong>模型边界</strong>
          <span>机器学习层采用小样本弱特征集成，不把 XGBoost/LSTM 包装成确定预测；评分只用于生成更可解释的号码池。</span>
        </div>
      </div>
    `;
  }

  function renderQuality(scheme) {
    const red = scheme.red;
    const odd = red.filter((n) => n % 2 === 1).length;
    const small = red.filter((n) => n <= 16).length;
    const zones = [
      red.filter((n) => n <= 11).length,
      red.filter((n) => n >= 12 && n <= 22).length,
      red.filter((n) => n >= 23).length
    ];
    const sum = red.reduce((a, b) => a + b, 0);
    const maxRun = maxConsecutiveRun(red);
    const latest = history[history.length - 1];
    const latestOverlap = latest ? redOverlap(red, latest.red) : 0;
    const hitSummary = historicalHitSummary(scheme);

    els.qualityPanel.innerHTML = `
      <div class="subhead"><h3>组合质量体检</h3><span>用于排除极端形态和高分奖风险</span></div>
      <div class="quality-grid">
        ${qualityItem("奇偶", `${odd}:${red.length - odd}`, "优先接近均衡")}
        ${qualityItem("大小", `${small}:${red.length - small}`, "01-16 / 17-33")}
        ${qualityItem("三区", zones.join(":"), "低/中/高区覆盖")}
        ${qualityItem("和值", String(sum), "过低过高都降权")}
        ${qualityItem("最长连号", `${maxRun} 连`, "3 连以上提高分奖风险")}
        ${qualityItem("上期重号", `${latestOverlap} 个`, "过高会降低分散度")}
        ${qualityItem("历史命中", hitSummary, "仅检查历史覆盖，不预测未来")}
      </div>
    `;
  }

  function renderNumberReasons(scheme, stats, scores) {
    const meta = scores.meta || {};
    const redRoles = scheme.type === "dantuo"
      ? Object.fromEntries([
          ...scheme.dantuo.dan.map((n) => [n, "胆码"]),
          ...scheme.dantuo.tuo.map((n) => [n, "拖码"])
        ])
      : Object.fromEntries(scheme.red.map((n) => [n, "红球"]));
    const redRows = scheme.red.map((n) => reasonRow(pad(n), redRoles[n], stats.redFreq[n], stats.redRecent[n], stats.redOmit[n], ai3NumberReason(n, "red", meta.redSignals && meta.redSignals[n], meta)));
    const blueRows = scheme.blue.map((n) => reasonRow(pad(n), "蓝球", stats.blueFreq[n], stats.blueRecent[n], stats.blueOmit[n], ai3NumberReason(n, "blue", meta.blueSignals && meta.blueSignals[n], meta)));

    els.numberReasons.innerHTML = `
      <div class="subhead"><h3>号码解释</h3><span>AI 3.0 综合分 / 频次 / 近 20 期 / 遗漏</span></div>
      <div class="reason-table">
        <table>
          <thead><tr><th>号码</th><th>类型</th><th>频次</th><th>近期</th><th>遗漏</th><th>入选原因</th></tr></thead>
          <tbody>${[...redRows, ...blueRows].join("")}</tbody>
        </table>
      </div>
    `;
  }

  function renderPortfolio(schemes) {
    const cards = schemes.map((scheme, index) => {
      const overlap = index === 0 ? "主推" : `与主推重 ${redOverlap(schemes[0].red, scheme.red)} 红`;
      const text = scheme.type === "dantuo"
        ? `胆:${formatNums(scheme.dantuo.dan)} 拖:${formatNums(scheme.dantuo.tuo)} 蓝:${formatNums(scheme.blue)}`
        : `红:${formatNums(scheme.red)} 蓝:${formatNums(scheme.blue)}`;
      return `
        <div class="portfolio-card">
          <div class="ball-row"><span class="tag">方案 ${index + 1}</span><span class="tag">${overlap}</span><span class="tag">${scheme.betCount} 注</span></div>
          <p class="scheme-text">${escapeHtml(text)}</p>
        </div>
      `;
    }).join("");

    const requested = clampNumber(els.portfolioCount.value, 1, 8);
    const portfolioNote = schemes.length < requested
      ? `最大重号约束下生成 ${schemes.length}/${requested} 组`
      : "多组投注时限制重复覆盖";
    els.portfolioPanel.innerHTML = `
      <div class="subhead"><h3>低重叠组合池</h3><span>${escapeHtml(portfolioNote)}</span></div>
      <div class="portfolio-list">${cards}</div>
    `;
  }

  function aiRecommendationCounts() {
    if (els.modeSelect.value === "single") return { redCount: 6, blueCount: 1 };
    if (els.modeSelect.value === "complex") {
      return {
        redCount: clampNumber(els.redCount.value, 6, 12),
        blueCount: clampNumber(els.blueCount.value, 1, 6)
      };
    }
    return { redCount: 7, blueCount: 2 };
  }

  async function analyzeWithAi() {
    currentAiResult = null;
    els.fillAiBtn.disabled = true;
    setAiBusy(true);
    els.aiStatus.textContent = "正在执行先分析、冻结规则、再选号的两阶段 DeepSeek 请求";
    els.aiRecommendation.innerHTML = '<div class="ai-loading">正在分析历史统计、最近走势与滚动回测...</div>';

    try {
      const token = requireAdminToken();
      const activeTaskId = sessionStorage.getItem(AI_TASK_STORAGE_KEY) || "";
      let task;
      if (activeTaskId) {
        task = await apiFetch(`/api/ai/tasks/${encodeURIComponent(activeTaskId)}`, { token });
      } else {
        const counts = aiRecommendationCounts();
        const clientRequestId = currentAiClientRequestId();
        task = await apiFetch("/api/ai/tasks", {
          method: "POST",
          token,
          body: JSON.stringify({
            scope: els.scopeSelect.value,
            red_count: counts.redCount,
            blue_count: counts.blueCount,
            shape_filter: els.shapeFilter.checked,
            avoid_popular: els.avoidPopular.checked,
            client_request_id: clientRequestId
          })
        });
        sessionStorage.setItem(AI_TASK_STORAGE_KEY, task.task_id);
      }
      const data = await waitForAiTask(task, token);
      currentAiResult = data;
      renderAiRecommendation(data);
      els.fillAiBtn.disabled = false;
    } catch (error) {
      if (error.status === 404 || error.taskFailed) {
        clearAiTaskStorage();
      }
      els.aiStatus.textContent = "AI 分析未完成";
      els.aiRecommendation.innerHTML = `<div class="purchase-empty">${escapeHtml(error.message)}</div>`;
    } finally {
      setAiBusy(false);
    }
  }

  function setAiBusy(busy) {
    els.aiAnalyzeBtn.disabled = busy;
    els.aiAnalyzeBtn.textContent = busy ? "AI 分析中..." : "AI 分析并推荐";
    if (busy) els.aiAnalyzeBtn.setAttribute("aria-busy", "true");
    else els.aiAnalyzeBtn.removeAttribute("aria-busy");
  }

  function currentAiClientRequestId() {
    const existing = sessionStorage.getItem(AI_REQUEST_STORAGE_KEY) || "";
    if (existing) return existing;
    const value = typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : Array.from(crypto.getRandomValues(new Uint32Array(4)), (item) => item.toString(16).padStart(8, "0")).join("");
    sessionStorage.setItem(AI_REQUEST_STORAGE_KEY, value);
    return value;
  }

  function clearAiTaskStorage() {
    sessionStorage.removeItem(AI_TASK_STORAGE_KEY);
    sessionStorage.removeItem(AI_REQUEST_STORAGE_KEY);
  }

  async function waitForAiTask(initialTask, token) {
    let task = initialTask || {};
    const taskId = String(task.task_id || "");
    if (!/^[-_A-Za-z0-9]{20,64}$/.test(taskId)) {
      throw new Error("AI 任务返回格式错误");
    }
    sessionStorage.setItem(AI_TASK_STORAGE_KEY, taskId);
    const statusUrl = `/api/ai/tasks/${encodeURIComponent(taskId)}`;
    const pollAfterMs = Math.max(1000, Math.min(10000, Number(task.poll_after_ms) || 3000));
    const deadline = Date.now() + AI_TASK_TIMEOUT_MS;
    let networkFailures = 0;

    while (Date.now() < deadline) {
      if (task.status === "succeeded") {
        clearAiTaskStorage();
        if (!task.result || typeof task.result !== "object") {
          throw new Error("AI 任务缺少结果");
        }
        return task.result;
      }
      if (task.status === "failed") {
        clearAiTaskStorage();
        const error = new Error(task.error?.message || "AI 分析失败");
        error.taskFailed = true;
        throw error;
      }
      if (task.status !== "running") {
        throw new Error("AI 任务状态异常");
      }

      els.aiStatus.textContent = "AI 两阶段分析正在后台运行";
      await new Promise((resolve) => window.setTimeout(resolve, pollAfterMs));
      try {
        task = await apiFetch(statusUrl, { token });
        networkFailures = 0;
      } catch (error) {
        if (error.status === 401 || error.status === 404) throw error;
        networkFailures += 1;
        if (networkFailures >= 3) {
          throw new Error("AI 任务查询暂时失败，稍后可继续查询");
        }
      }
    }
    throw new Error("AI 任务仍在后台运行，稍后可继续查询");
  }

  function renderAiRecommendation(data) {
    const recommendation = data.recommendation || {};
    const research = data.research || {};
    const researchData = research.data || {};
    const pipeline = data.pipeline || {};
    const structure = recommendation.structure || {};
    const dynamicProfile = recommendation.dynamic_profile || {};
    const shapeHistory = research.shape_history?.selected_scope || {};
    const mostCommon = (items) => (items || []).reduce((best, item) => {
      if (!best || Number(item.count || 0) > Number(best.count || 0)) return item;
      return best;
    }, null);
    const commonOdd = mostCommon(shapeHistory.odd_counts);
    const commonSmall = mostCommon(shapeHistory.small_counts);
    const commonZone = (shapeHistory.top_zone_patterns || [])[0];
    const sumBand = shapeHistory.sum_band || {};
    const shapeReport = shapeHistory.window
      ? `${shapeHistory.window} 期单期开奖（6红）中，常见奇数个数 ${commonOdd?.value ?? "-"}、小号个数 ${commonSmall?.value ?? "-"}、三区形态 ${commonZone?.pattern || "-"}；和值中间 50% 为 ${sumBand.p25 ?? "-"}-${sumBand.p75 ?? "-"}`
      : "暂无可用的历史形态分布";
    const selectionRules = (recommendation.selection_rules || [])
      .map((item) => `<li>${escapeHtml(item)}</li>`)
      .join("");
    const profileEvidence = (recommendation.profile_evidence || [])
      .map((item) => {
        const value = Array.isArray(item.value) ? item.value.join("-") : String(item.value ?? "-");
        return `<li><strong>${escapeHtml(item.label || item.id || "历史依据")}（${escapeHtml(value)}）</strong>：${escapeHtml(item.reason || "")}</li>`;
      })
      .join("");
    const profileRange = (value) => Array.isArray(value) && value.length === 2 ? `${value[0]}-${value[1]}` : "-";
    const dynamicProfileText = [
      `奇数 ${profileRange(dynamicProfile.odd_range)} 个`,
      `小号 ${profileRange(dynamicProfile.small_range)} 个`,
      `三区下限 ${(dynamicProfile.zone_minimums || []).join(":") || "-"}`,
      `和值 ${profileRange(dynamicProfile.sum_range)}`,
      `最长连号 ${dynamicProfile.max_consecutive_run ?? "-"}`
    ].join("；");
    const betCount = comb((recommendation.red || []).length, 6) * (recommendation.blue || []).length;
    const reasonCards = [
      ...(recommendation.red_reasons || []).map((item) => aiReasonCard(item, "red")),
      ...(recommendation.blue_reasons || []).map((item) => aiReasonCard(item, "blue"))
    ].join("");
    const backtests = (research.backtests || []).map((item) => {
      const delta = Number(item.delta_from_random || 0);
      const deltaText = `${delta >= 0 ? "+" : ""}${delta.toFixed(3)}`;
      return `
        <div class="ai-backtest-item">
          <strong>${escapeHtml(aiBacktestName(item.name))}</strong>
          <span>前 ${escapeHtml(String(item.window))} 期 · ${escapeHtml(String(item.samples))} 个样本</span>
          <span>均值 ${escapeHtml(Number(item.average_hits || 0).toFixed(3))} · 随机期望 ${escapeHtml(Number(item.random_expectation || 0).toFixed(3))} · 差 ${escapeHtml(deltaText)}</span>
        </div>
      `;
    }).join("");

    const pipelineLabel = pipeline.analysis_frozen_before_selection ? "先分析后选号 · 规则已冻结" : "动态研究";
    els.aiStatus.textContent = `${data.model || "DeepSeek"} · ${pipelineLabel} · 数据截至 ${researchData.latest_issue || "-"}`;
    els.aiRecommendation.innerHTML = `
      <div class="ai-result-head">
        <div>
          <div class="ball-row"><span class="tag">红球</span>${ballsHtml(recommendation.red || [], "red")}</div>
          <div class="ball-row"><span class="tag">蓝球</span>${ballsHtml(recommendation.blue || [], "blue")}</div>
        </div>
        <div class="ai-meta">
          <strong>${escapeHtml(String(betCount))} 注 · ${escapeHtml(String(betCount * 2))} 元</strong>
          <span>${escapeHtml(String(researchData.scope_issues || 0))} 期统计 · ${escapeHtml(String(researchData.available_issues || 0))} 期回测数据</span>
        </div>
      </div>
      <p class="ai-summary">${escapeHtml(recommendation.summary || "AI 已完成历史研究并给出结构化组合。")}</p>
      <div class="subhead"><h3>本期动态规则</h3><span>本次分析生成，不是固定模板</span></div>
      <div class="ai-dynamic-rules">
        <ul class="ai-rule-list">${selectionRules || "<li>AI 未单列规则，以逐号分析和形态依据为准。</li>"}</ul>
        <p><strong>历史形态报告：</strong>${escapeHtml(shapeReport)}</p>
        <p><strong>AI 动态口径：</strong>${escapeHtml(dynamicProfileText)}</p>
        <p><strong>动态口径依据：</strong></p>
        <ul class="ai-rule-list">${profileEvidence || "<li>等待服务端核对 AI 引用的历史依据。</li>"}</ul>
        <p><strong>AI 本期取舍：</strong>${escapeHtml(recommendation.model_structure_rationale || "等待 AI 返回本期形态取舍。")}</p>
        <p><strong>服务端结构核对：</strong>${escapeHtml(recommendation.structure_rationale || "等待服务端核对最终号码结构。")}</p>
      </div>
      <div class="ai-structure">
        ${metricHtml("奇偶", structure.odd_even || "-", "红球奇数 / 偶数")}
        ${metricHtml("大小", structure.small_large || "-", "01-16 / 17-33")}
        ${metricHtml("三区", structure.zones || "-", "01-11 / 12-22 / 23-33")}
        ${metricHtml("和值", String(structure.sum ?? "-"), `跨度 ${structure.span ?? "-"} · 最长连号 ${structure.max_consecutive ?? "-"}`)}
      </div>
      <div class="subhead"><h3>逐号分析</h3><span>AI 理由 + 服务端真实统计</span></div>
      <div class="ai-reason-grid">${reasonCards}</div>
      <div class="subhead"><h3>滚动回测</h3><span>每一期只使用此前数据</span></div>
      <div class="ai-backtest-grid">${backtests}</div>
      <div class="ai-conclusion">
        <strong>AI 回测结论</strong>
        <p>${escapeHtml(recommendation.backtest_conclusion || "历史标签没有显示稳定预测优势。")}</p>
        <strong>风险边界</strong>
        <p>${escapeHtml(recommendation.risk_note || data.disclaimer || "推荐不保证中奖。")}</p>
      </div>
    `;
  }

  function aiReasonCard(item, kind) {
    return `
      <div class="ai-reason-card">
        <div class="ball-row">
          <span class="ball ${kind}">${pad(Number(item.number))}</span>
          <strong>${kind === "red" ? "红球" : "蓝球"} ${pad(Number(item.number))}</strong>
        </div>
        <p>${escapeHtml(item.reason || "用于组合分散。")}</p>
        <span>统计 ${escapeHtml(String(item.frequency ?? "-"))} · 近20期 ${escapeHtml(String(item.recent20 ?? "-"))} · 遗漏 ${escapeHtml(String(item.omission ?? "-"))}</span>
      </div>
    `;
  }

  function aiBacktestName(name) {
    return {
      red_hot_top8: "红球热号 Top8",
      red_omission_top8: "红球遗漏 Top8",
      red_cold_top8: "红球冷号 Top8",
      previous_draw_repeat: "上期重号",
      blue_hot_top4: "蓝球热号 Top4"
    }[name] || name;
  }

  function fillAiPurchase() {
    const recommendation = currentAiResult && currentAiResult.recommendation;
    if (!recommendation) return;
    els.purchaseIssue.value = nextIssue();
    els.purchaseMode.value = "complex";
    togglePurchaseMode();
    els.purchaseRed.value = formatNums(recommendation.red || []);
    els.purchaseBlue.value = formatNums(recommendation.blue || []);
    els.purchaseNote.value = `AI历史研究 红:${formatNums(recommendation.red || [])} 蓝:${formatNums(recommendation.blue || [])}`;
    els.purchaseStatus.textContent = "已填入 AI 历史研究推荐";
  }

  function initPurchasePanel() {
    const savedToken = localStorage.getItem("ssqAdminToken") || "";
    els.adminToken.value = savedToken;
    els.purchaseIssue.value = nextIssue();
    togglePurchaseMode();
    if (savedToken) {
      loadPurchaseState();
      if (sessionStorage.getItem(AI_TASK_STORAGE_KEY)) {
        analyzeWithAi();
      }
    } else {
      els.purchaseList.innerHTML = emptyPurchaseHtml("输入管理密钥后读取服务器购买记录");
    }
  }

  function togglePurchaseMode() {
    const dantuo = els.purchaseMode.value === "dantuo";
    els.purchaseNormalFields.classList.toggle("hidden", dantuo);
    els.purchaseDantuoFields.classList.toggle("hidden", !dantuo);
  }

  function fillCurrentPurchase() {
    if (!currentScheme) return;
    els.purchaseIssue.value = nextIssue();
    if (currentScheme.type === "dantuo") {
      els.purchaseMode.value = "dantuo";
      togglePurchaseMode();
      els.purchaseDan.value = formatNums(currentScheme.dantuo.dan);
      els.purchaseTuo.value = formatNums(currentScheme.dantuo.tuo);
      els.purchaseDtBlue.value = formatNums(currentScheme.blue);
    } else {
      els.purchaseMode.value = "complex";
      togglePurchaseMode();
      els.purchaseRed.value = formatNums(currentScheme.red);
      els.purchaseBlue.value = formatNums(currentScheme.blue);
    }
    els.purchaseNote.value = currentSchemeText;
  }

  async function savePurchase() {
    try {
      const token = requireAdminToken();
      const payload = buildPurchasePayload();
      setPurchaseStatus("保存中...");
      const result = await apiFetch("/api/purchases", {
        method: "POST",
        token,
        body: JSON.stringify(payload)
      });
      await loadPurchaseState();
      const notifyText = result.notification && result.notification.message
        ? `；${result.notification.message}`
        : "";
      setPurchaseStatus(`已保存，等待开奖后自动核验${notifyText}`);
    } catch (error) {
      setPurchaseStatus(error.message);
    }
  }

  async function loadPurchaseState() {
    try {
      const token = requireAdminToken();
      setPurchaseStatus("读取服务器记录...");
      const state = await apiFetch("/api/state", { token });
      renderPurchases(state.purchases || [], state.results || [], state.latest || null);
      setPurchaseStatus(state.latest ? `服务器最新开奖 ${state.latest.issue}` : "已读取记录");
    } catch (error) {
      els.purchaseList.innerHTML = emptyPurchaseHtml("无法读取服务器购买记录");
      setPurchaseStatus(error.message);
    }
  }

  async function checkNow() {
    try {
      const token = requireAdminToken();
      setPurchaseStatus("正在核奖...");
      const result = await apiFetch("/api/check-now", { method: "POST", token });
      if (!result.ok) {
        throw new Error(result.stderr || result.stdout || "核奖失败");
      }
      setPurchaseStatus(result.stdout || "核奖完成");
      await loadPurchaseState();
    } catch (error) {
      setPurchaseStatus(error.message);
    }
  }

  async function deletePurchase(id) {
    try {
      const token = requireAdminToken();
      await apiFetch(`/api/purchases/${encodeURIComponent(id)}`, { method: "DELETE", token });
      setPurchaseStatus("已删除");
      await loadPurchaseState();
    } catch (error) {
      setPurchaseStatus(error.message);
    }
  }

  function buildPurchasePayload() {
    const issue = els.purchaseIssue.value.trim();
    const note = els.purchaseNote.value.trim();
    if (!/^\d{7}$/.test(issue)) throw new Error("期号应为 7 位数字，例如 2026066");

    if (els.purchaseMode.value === "dantuo") {
      return {
        issue,
        type: "dantuo",
        dan: parseNums(els.purchaseDan.value, 1, 33, "胆码"),
        tuo: parseNums(els.purchaseTuo.value, 1, 33, "拖码"),
        blue: parseNums(els.purchaseDtBlue.value, 1, 16, "蓝球"),
        note
      };
    }

    return {
      issue,
      type: "complex",
      red: parseNums(els.purchaseRed.value, 1, 33, "红球"),
      blue: parseNums(els.purchaseBlue.value, 1, 16, "蓝球"),
      note
    };
  }

  function renderPurchases(purchases, results, latest) {
    if (!purchases.length) {
      els.purchaseList.innerHTML = emptyPurchaseHtml("还没有保存过购买记录");
      return;
    }

    const resultMap = new Map(results.map((item) => [`${item.purchase_id}:${item.issue}`, item]));
    const cards = purchases.slice().reverse().map((purchase) => {
      const result = resultMap.get(`${purchase.id}:${purchase.issue}`);
      const status = purchaseStatusText(purchase, result, latest);
      const numbers = purchase.type === "dantuo"
        ? `${labelHtml("红球胆码", "red")} ${escapeHtml(formatNums(purchase.dan || []))} ${labelHtml("红球拖码", "red")} ${escapeHtml(formatNums(purchase.tuo || []))} ${labelHtml("蓝球", "blue")} ${escapeHtml(formatNums(purchase.blue || []))}`
        : `${labelHtml("红球", "red")} ${escapeHtml(formatNums(purchase.red || []))} ${labelHtml("蓝球", "blue")} ${escapeHtml(formatNums(purchase.blue || []))}`;
      const resultLine = result
        ? `${labelHtml("开奖号码", "neutral")} ${labelHtml("红球", "red")} ${escapeHtml(formatNums(result.draw.red))} ${labelHtml("蓝球", "blue")} ${escapeHtml(pad(result.draw.blue))} ｜ ${escapeHtml(resultSummary(result))}`
        : "未产生核奖结果";
      return `
        <div class="purchase-card">
          <div class="purchase-card-head">
            <strong>${escapeHtml(purchase.issue)} · ${purchase.type === "dantuo" ? "胆拖" : "复式"}</strong>
            <span class="purchase-state ${result && result.won ? "won" : ""}">${escapeHtml(status)}</span>
          </div>
          <p>${numbers}</p>
          <p>${resultLine}</p>
          ${purchase.note ? `<p class="purchase-note-text"><span class="blessing-label">祝福</span>${escapeHtml(purchase.note)}</p>` : ""}
          <button type="button" class="link-btn" data-delete-purchase="${escapeHtml(purchase.id)}">删除</button>
        </div>
      `;
    }).join("");

    els.purchaseList.innerHTML = cards;
    els.purchaseList.querySelectorAll("[data-delete-purchase]").forEach((btn) => {
      btn.addEventListener("click", () => deletePurchase(btn.dataset.deletePurchase));
    });
  }

  function labelHtml(text, tone) {
    const klass = tone === "red" ? "inline-label red-text" : tone === "blue" ? "inline-label blue-text" : "inline-label";
    return `<span class="${klass}">${escapeHtml(text)}：</span>`;
  }

  function purchaseStatusText(purchase, result, latest) {
    if (result) {
      if (!result.won) return "已核验，未中奖";
      const floatingAmount = Number(result.floating_amount || 0);
      const totalAmount = Number(result.total_amount || (Number(result.fixed_amount || 0) + floatingAmount));
      return floatingAmount
        ? `中奖，总奖金约 ${totalAmount} 元`
        : `中奖，固定奖金约 ${result.fixed_amount} 元`;
    }
    if (latest && Number(latest.issue) >= Number(purchase.issue)) return "已开奖，待核验";
    return "待开奖";
  }

  function resultSummary(result) {
    const hits = Object.entries(result.counts || {})
      .filter(([, count]) => count)
      .map(([name, count]) => `${name}${count}注`);
    if (!hits.length) return "未中奖";
    const floatingAmount = Number(result.floating_amount || 0);
    const totalAmount = Number(result.total_amount || (Number(result.fixed_amount || 0) + floatingAmount));
    return floatingAmount
      ? `${hits.join("，")}，总奖金约 ${totalAmount} 元（固定 ${result.fixed_amount} + 浮动 ${floatingAmount}）`
      : `${hits.join("，")}，固定奖金约 ${result.fixed_amount} 元`;
  }

  async function apiFetch(path, options = {}) {
    const headers = {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${options.token}`
    };
    const response = await fetch(path, {
      method: options.method || "GET",
      headers,
      body: options.body
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.error || `请求失败 ${response.status}`);
      error.status = response.status;
      error.data = data;
      throw error;
    }
    return data;
  }

  function requireAdminToken() {
    const token = els.adminToken.value.trim();
    if (!token) throw new Error("请先输入管理密钥");
    localStorage.setItem("ssqAdminToken", token);
    return token;
  }

  function setPurchaseStatus(text) {
    els.purchaseStatus.textContent = text;
  }

  function emptyPurchaseHtml(text) {
    return `<div class="purchase-empty">${escapeHtml(text)}</div>`;
  }

  function parseNums(value, min, max, label) {
    const nums = (value.match(/\d+/g) || []).map(Number).sort((a, b) => a - b);
    if (!nums.length) throw new Error(`${label}不能为空`);
    if (new Set(nums).size !== nums.length) throw new Error(`${label}不能重复`);
    if (nums.some((n) => n < min || n > max)) throw new Error(`${label}范围应为 ${min}-${max}`);
    return nums;
  }

  function nextIssue() {
    const latest = history[history.length - 1];
    return latest ? String(Number(latest.issue) + 1) : "";
  }

  function renderHistoryAnalysis(stats, scope) {
    const hotRed = topEntries(stats.redFreq, 8, "desc");
    const coldRed = topEntries(stats.redFreq, 8, "asc");
    const omitRed = topEntries(stats.redOmit, 8, "desc");
    const hotBlue = topEntries(stats.blueFreq, 6, "desc");
    const omitBlue = topEntries(stats.blueOmit, 6, "desc");
    const blueSignals = buildBlueSignals(stats);
    const signalBlue = topBlueSignals(blueSignals, 3);
    const review = latestDrawReview();
    const shape = historyShapeSummary(scope);
    const points = strategyPoints(stats, shape);

    els.historyAnalysis.innerHTML = `
      <div class="analysis-grid">
        ${analysisCard("红球热号", pillList(hotRed.map(([n, v]) => `${pad(n)} · ${v}次`)))}
        ${analysisCard("红球冷号", pillList(coldRed.map(([n, v]) => `${pad(n)} · ${v}次`)))}
        ${analysisCard("红球长遗漏", pillList(omitRed.map(([n, v]) => `${pad(n)} · 漏${v}`)))}
        ${analysisCard("蓝球统计", pillList([
          ...signalBlue.map(([n, signal]) => `${pad(n)} 信号${signal.hotEvidence.toFixed(2)}`),
          ...hotBlue.slice(0, 3).map(([n, v]) => `${pad(n)}频${v}`),
          ...omitBlue.slice(0, 3).map(([n, v]) => `${pad(n)}漏${v}仅参考`)
        ]))}
        ${analysisCard("最新复盘", review)}
        ${analysisCard("常见形态", `
          <div class="pill-list">
            <span class="pill">奇偶 ${shape.oddEven}</span>
            <span class="pill">大小 ${shape.smallBig}</span>
            <span class="pill">和值 ${shape.sumBand}</span>
            <span class="pill">均值 ${shape.avgSum}</span>
          </div>
        `)}
        ${analysisCard("策略结论", `<ul class="strategy-points">${points.map((point) => `<li>${escapeHtml(point)}</li>`).join("")}</ul>`)}
      </div>
    `;
  }

  function renderStrategyResearch() {
    const rows = buildStrategyResearchRows();
    els.strategyResearch.innerHTML = `
      <div class="research-table">
        <table>
          <thead>
            <tr>
              <th>方向</th>
              <th>窗口</th>
              <th>样本</th>
              <th>平均命中</th>
              <th>中位数</th>
              <th>90 分位</th>
              <th>结论</th>
            </tr>
          </thead>
          <tbody>
            ${rows.map((row) => `
              <tr>
                <td>${escapeHtml(row.name)}</td>
                <td>${escapeHtml(row.window)}</td>
                <td>${row.n}</td>
                <td>${row.avg}</td>
                <td>${row.p50}</td>
                <td>${row.p90}</td>
                <td>${escapeHtml(row.note)}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  function renderHeatmaps(stats, scheme) {
    els.redHeatmap.innerHTML = heatmapHtml(RED_MAX, stats.redFreq, stats.redOmit, "red", scheme.red);
    els.blueHeatmap.innerHTML = heatmapHtml(BLUE_MAX, stats.blueFreq, stats.blueOmit, "blue", scheme.blue);
  }

  function heatmapHtml(max, freq, omit, type, selected) {
    const maxFreq = Math.max(...Object.values(freq), 1);
    const selectedSet = new Set(selected);
    const cells = [];
    for (let n = 1; n <= max; n++) {
      const alpha = 0.08 + (freq[n] / maxFreq) * 0.26;
      const background = type === "red" ? `rgba(215, 59, 62, ${alpha})` : `rgba(36, 103, 214, ${alpha})`;
      const border = selectedSet.has(n) ? "2px solid #17202a" : "1px solid var(--line)";
      cells.push(`
        <div class="number-cell ${type}-cell" style="background:${background};border:${border}">
          <span class="num">${pad(n)}</span>
          <div class="cell-meta">
            <span>频 ${freq[n] || 0}</span>
            <span>漏 ${omit[n]}</span>
          </div>
        </div>
      `);
    }
    return cells.join("");
  }

  function renderTrendTable() {
    const rows = history.slice(-TREND_WINDOW);
    const tableRows = rows.slice().reverse();
    const redHeads = Array.from({ length: RED_MAX }, (_, i) => `<th>${pad(i + 1)}</th>`).join("");
    const body = tableRows
      .map((row) => {
        const redSet = new Set(row.red);
        const cells = Array.from({ length: RED_MAX }, (_, i) => {
          const n = i + 1;
          return `<td>${redSet.has(n) ? `<span class="hit-red">${pad(n)}</span>` : "<span class='empty-cell'>·</span>"}</td>`;
        }).join("");
        return `<tr><td>${row.issue}</td><td>${row.date}</td>${cells}<td><span class="hit-blue">${pad(row.blue)}</span></td></tr>`;
      })
      .join("");
    els.trendTable.innerHTML = `
      <div class="trend-local-scroll">
        <div class="trend-charts">
          ${trendLineChartHtml(rows, "red")}
          ${trendLineChartHtml(rows, "blue")}
        </div>
        <table><thead><tr><th>期号</th><th>日期</th>${redHeads}<th>蓝</th></tr></thead><tbody>${body}</tbody></table>
      </div>
    `;
  }

  function trendLineChartHtml(rows, type) {
    const isRed = type === "red";
    const max = isRed ? RED_MAX : BLUE_MAX;
    const lanes = isRed ? 6 : 1;
    const title = isRed ? "红球点位走势" : "蓝球走势";
    const subtitle = isRed ? `最近 ${rows.length} 期，只显示点位` : `最近 ${rows.length} 期，按蓝球连线`;
    const width = 1040;
    const rowGap = 18;
    const top = 34;
    const left = 96;
    const right = 28;
    const bottom = 16;
    const chartWidth = width - left - right;
    const height = top + bottom + Math.max(1, rows.length - 1) * rowGap;
    const yFor = (index) => top + index * rowGap;
    const xFor = (n) => left + ((n - 1) / (max - 1)) * chartWidth;
    const laneColors = isRed
      ? ["#b91c1c", "#dc2626", "#ef4444", "#f97316", "#fb7185", "#991b1b"]
      : ["#2563eb"];
    const heads = Array.from({ length: max }, (_, i) => {
      const n = i + 1;
      const x = xFor(n);
      return `<text class="trend-axis-label" x="${x.toFixed(2)}" y="22">${pad(n)}</text>`;
    }).join("");
    const rowLines = rows.map((row, index) => {
      const y = yFor(index);
      return `
        <line class="trend-row-line" x1="${left}" y1="${y}" x2="${width - right}" y2="${y}" />
        <text class="trend-issue-label" x="8" y="${y + 4}">${escapeHtml(row.issue)}</text>
      `;
    }).join("");
    const columnLines = Array.from({ length: max }, (_, i) => {
      const n = i + 1;
      const x = xFor(n);
      const strong = isRed ? n % 5 === 0 || n === 1 || n === RED_MAX : n % 4 === 0 || n === 1 || n === BLUE_MAX;
      return `<line class="trend-column-line ${strong ? "strong" : ""}" x1="${x.toFixed(2)}" y1="${top - 14}" x2="${x.toFixed(2)}" y2="${height - bottom + 4}" />`;
    }).join("");
    const polylines = isRed ? "" : Array.from({ length: lanes }, (_, lane) => {
      const points = rows.map((row, index) => {
        const value = isRed ? row.red[lane] : row.blue;
        return `${xFor(value).toFixed(2)},${yFor(index).toFixed(2)}`;
      }).join(" ");
      return `<polyline class="trend-polyline ${isRed ? "red-line" : "blue-line"}" points="${points}" style="--line-color:${laneColors[lane]}" />`;
    }).join("");
    const points = rows.map((row, index) => {
      const y = yFor(index);
      const values = isRed ? row.red : [row.blue];
      return values.map((value, lane) => {
        const x = xFor(value);
        return `
          <g class="trend-point ${isRed ? "red-point" : "blue-point"}">
            <circle cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="${isRed ? 6.5 : 7.5}" />
            <text x="${x.toFixed(2)}" y="${y + 2.6}">${pad(value)}</text>
          </g>
        `;
      }).join("");
    }).join("");

    return `
      <div class="trend-chart ${isRed ? "trend-red-chart" : "trend-blue-chart"}">
        <div class="trend-chart-head">
          <strong>${title}</strong>
          <span>${subtitle}</span>
        </div>
        <div class="trend-svg-scroll">
          <svg class="trend-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${title}">
            <rect class="trend-bg" x="0" y="0" width="${width}" height="${height}" />
            ${heads}
            ${columnLines}
            ${rowLines}
            ${polylines}
            ${points}
          </svg>
        </div>
      </div>
    `;
  }

  function renderDrawList() {
    const rows = history
      .map((row, index) => ({ row, index }))
      .reverse()
      .map(({ row, index }) => `
        <tr>
          <td>${row.issue}</td>
          <td>${row.date}</td>
          <td>${formatNums(row.red)}</td>
          <td>${pad(row.blue)}</td>
          <td>${drawQualityCell(index)}</td>
          <td>${previousRepeatCell(index)}</td>
          <td>${windowRedHitCell(index, 30, "hot")}</td>
          <td>${windowRedHitCell(index, 30, "omission")}</td>
          <td>${windowRedHitCell(index, 50, "hot")}</td>
          <td>${windowRedHitCell(index, 50, "omission")}</td>
          <td>${blueStatusCell(index)}</td>
        </tr>
      `)
      .join("");
    els.drawList.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>期号</th>
            <th>日期</th>
            <th>红球</th>
            <th>蓝球</th>
            <th>组合质量</th>
            <th>上期重复</th>
            <th>前30高频</th>
            <th>前30久未出</th>
            <th>前50高频</th>
            <th>前50久未出</th>
            <th>蓝球状态</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  }

  function anyPrizeProbability(scheme) {
    const blueHit = scheme.blueCount / 16;
    const redPrize = scheme.type === "dantuo"
      ? dantuoRedPrizeProbability(scheme.dantuo.dan.length, scheme.dantuo.tuo.length)
      : complexRedPrizeProbability(scheme.redCount);
    return blueHit + (1 - blueHit) * redPrize;
  }

  function complexRedPrizeProbability(selectedRedCount) {
    let p = 0;
    for (let hit = 4; hit <= 6; hit++) {
      p += (comb(selectedRedCount, hit) * comb(33 - selectedRedCount, 6 - hit)) / comb(33, 6);
    }
    return p;
  }

  function dantuoRedPrizeProbability(danCount, tuoCount) {
    let favorable = 0;
    const other = 33 - danCount - tuoCount;
    const needFromTuo = 6 - danCount;

    for (let danHit = 0; danHit <= danCount; danHit++) {
      for (let tuoHit = 0; tuoHit <= tuoCount; tuoHit++) {
        const otherHit = 6 - danHit - tuoHit;
        if (otherHit < 0 || otherHit > other) continue;
        const maxMatched = danHit + Math.min(tuoHit, needFromTuo);
        if (maxMatched >= 4) {
          favorable += comb(danCount, danHit) * comb(tuoCount, tuoHit) * comb(other, otherHit);
        }
      }
    }

    return favorable / comb(33, 6);
  }

  function countRange(max) {
    const map = {};
    for (let i = 1; i <= max; i++) map[i] = 0;
    return map;
  }

  function omission(rows, predicate) {
    for (let i = rows.length - 1; i >= 0; i--) {
      if (predicate(rows[i])) return rows.length - 1 - i;
    }
    return rows.length;
  }

  function normalizeMap(map, max) {
    const values = [];
    for (let n = 1; n <= max; n++) values.push(map[n] || 0);
    const min = Math.min(...values);
    const maxValue = Math.max(...values);
    const result = {};
    for (let n = 1; n <= max; n++) {
      result[n] = maxValue === min ? 0.5 : ((map[n] || 0) - min) / (maxValue - min);
    }
    return result;
  }

  function binomialZ(hitCount, sampleSize, probability) {
    const variance = sampleSize * probability * (1 - probability);
    if (!variance) return 0;
    return (hitCount - sampleSize * probability) / Math.sqrt(variance);
  }

  function averageScore(nums, scoreMap) {
    if (!nums.length) return 0;
    return clamp01(nums.reduce((sum, n) => sum + (scoreMap[n] || 0), 0) / nums.length);
  }

  function countOverlap(a, b) {
    const set = new Set(b);
    return a.filter((n) => set.has(n)).length;
  }

  function rangeScore(value, min, max, hardMax) {
    if (value >= min && value <= max) return 1;
    if (value < min) return clamp01(value / Math.max(1, min));
    return clamp01(1 - (value - max) / Math.max(1, hardMax - max));
  }

  function clamp01(value) {
    return Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, Number.isFinite(value) ? value : min));
  }

  function ballsHtml(nums, type, stars = new Set()) {
    return nums.map((n) => {
      const starHtml = stars.has(n) ? `<sup class="ball-star" title="统计信号星标">★</sup>` : "";
      return `<span class="ball ${type}${stars.has(n) ? " starred" : ""}">${pad(n)}${starHtml}</span>`;
    }).join("");
  }

  function metricHtml(label, value, hint) {
    return `<div class="metric"><strong>${value}</strong><span>${label} · ${hint}</span></div>`;
  }

  function formatNums(nums) {
    return nums.map(pad).join(" ");
  }

  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function comb(n, k) {
    if (k < 0 || k > n) return 0;
    let result = 1;
    for (let i = 1; i <= k; i++) {
      result = (result * (n - k + i)) / i;
    }
    return result;
  }

  function clampNumber(value, min, max) {
    const n = Number(value);
    return Math.max(min, Math.min(max, Number.isFinite(n) ? Math.floor(n) : min));
  }

  function oneIn(p) {
    if (!p) return "无";
    return `约 1 / ${Math.round(1 / p).toLocaleString("zh-CN")}`;
  }

  function crowdRiskLabel(score) {
    if (score < 0.8) return "低";
    if (score < 1.8) return "中";
    return "高";
  }

  function qualityItem(label, value, hint) {
    return `<div class="quality-item"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)} · ${escapeHtml(hint)}</span></div>`;
  }

  function reasonRow(num, type, freq, recent, omit, reason) {
    return `<tr><td>${num}</td><td>${type}</td><td>${freq}</td><td>${recent}</td><td>${omit}</td><td>${reason}</td></tr>`;
  }

  function numberReason(freq, recent, omit) {
    const parts = [];
    if (freq >= 7) parts.push("高频");
    if (recent >= 3) parts.push("近期活跃");
    if (omit >= 10) parts.push("长遗漏");
    if (!parts.length) parts.push("形态补位");
    return parts.join(" / ");
  }

  function ai3NumberReason(n, kind, signal, meta) {
    if (!signal || !signal.ai3) {
      return kind === "blue" ? "均匀底池" : "形态补位";
    }

    const score = Math.round(signal.ai3.score * 100);
    const parts = [`综合${score}`];
    const starList = kind === "blue" ? meta.starBlue || [] : meta.starRed || [];
    const fourList = kind === "blue" ? meta.fourBlue || [] : meta.fourRed || [];
    const threeList = kind === "blue" ? meta.threeBlue || [] : meta.threeRed || [];
    const componentLabels = [
      ["history", "历史"],
      ["omission", "遗漏"],
      ["conversion", "冷热"],
      ["probability", "概率"],
      ["machine", "机器"],
      ["simulation", "模拟"]
    ];
    const topComponents = componentLabels
      .map(([key, label]) => [label, signal.ai3.components[key] || 0])
      .sort((a, b) => b[1] - a[1])
      .slice(0, 2)
      .map(([label]) => label);

    if (starList.includes(n)) parts.push("★★★★★");
    else if (fourList.includes(n)) parts.push("★★★★");
    else if (threeList.includes(n)) parts.push("三星");
    if (topComponents.length) parts.push(`强项:${topComponents.join("+")}`);
    if (signal.ai3.recent15 >= 3) parts.push("近窗活跃");
    if (signal.ai3.gap >= 10) parts.push("遗漏观察");
    return parts.join(" / ");
  }

  function blueNumberReason(n, stats, signal) {
    const parts = [];
    if (signal && signal.starred) parts.push("统计星标");
    if (signal && signal.hotEvidence >= 0.35) parts.push("频率偏差信号");
    if ((stats.blueRecent[n] || 0) >= 2) parts.push("近期覆盖");
    if ((stats.blueOmit[n] || 0) >= 10) parts.push("遗漏仅展示");
    if (!parts.length) parts.push("均匀底池");
    return parts.join(" / ");
  }

  function maxConsecutiveRun(nums) {
    const sorted = nums.slice().sort((a, b) => a - b);
    let best = 1;
    let current = 1;
    for (let i = 1; i < sorted.length; i++) {
      if (sorted[i] === sorted[i - 1] + 1) {
        current++;
        best = Math.max(best, current);
      } else {
        current = 1;
      }
    }
    return best;
  }

  function redOverlap(a, b) {
    const set = new Set(a);
    return b.filter((n) => set.has(n)).length;
  }

  function sameScheme(a, b) {
    return formatNums(a.red) === formatNums(b.red) && formatNums(a.blue) === formatNums(b.blue);
  }

  function historicalHitSummary(scheme) {
    const tiers = { high: 0, small: 0 };
    history.forEach((row) => {
      const redHit = redOverlap(scheme.red, row.red);
      const blueHit = scheme.blue.includes(row.blue);
      if ((redHit === 6 && blueHit) || redHit === 6 || (redHit === 5 && blueHit)) {
        tiers.high++;
      } else if (blueHit || redHit >= 4) {
        tiers.small++;
      }
    });
    return `${tiers.high} 次高奖形态 / ${tiers.small} 次小奖形态`;
  }

  function previousRepeatCell(index) {
    if (index <= 0) return simpleCell("无上期");
    const row = history[index];
    const prev = history[index - 1];
    const repeatRed = row.red.filter((n) => prev.red.includes(n));
    const blueRepeat = row.blue === prev.blue;
    const parts = [];
    if (repeatRed.length) parts.push(`红 ${formatNums(repeatRed)}`);
    if (blueRepeat) parts.push(`蓝 ${pad(row.blue)}`);
    return simpleCell(parts.length ? parts.join("；") : "无");
  }

  function drawQualityCell(index) {
    const red = history[index].red;
    const odd = red.filter((n) => n % 2 === 1).length;
    const small = red.filter((n) => n <= 16).length;
    const zones = [
      red.filter((n) => n <= 11).length,
      red.filter((n) => n >= 12 && n <= 22).length,
      red.filter((n) => n >= 23).length
    ];
    const sum = red.reduce((a, b) => a + b, 0);
    const run = maxConsecutiveRun(red);
    const risk = staticCrowdRiskLabel(red);
    return `
      <div class="history-quality">
        <span>奇偶 ${odd}:${red.length - odd} ｜ 大小 ${small}:${red.length - small}</span>
        <span>三区 ${zones.join(":")} ｜ 和值 ${sum}</span>
        <span>最长连号 ${run} ｜ 分奖风险 ${risk}</span>
      </div>
    `;
  }

  function windowRedHitCell(index, size, kind) {
    if (index <= 0) return simpleCell("无数据");
    const row = history[index];
    const prior = history.slice(Math.max(0, index - size), index);
    const stats = buildStats(prior, prior);
    const set = new Set(topEntries(kind === "hot" ? stats.redFreq : stats.redOmit, 8, "desc").map(([n]) => n));
    const hits = row.red.filter((n) => set.has(n));
    return simpleCell(hits.length ? formatNums(hits) : "无");
  }

  function blueStatusCell(index) {
    if (index <= 0) return simpleCell("无数据");
    return simpleCell(`30期${blueStatus(index, 30)}；50期${blueStatus(index, 50)}`);
  }

  function blueStatus(index, size) {
    const row = history[index];
    const prior = history.slice(Math.max(0, index - size), index);
    const stats = buildStats(prior, prior);
    const hotBlue = new Set(topEntries(stats.blueFreq, 4, "desc").map(([n]) => n));
    const omitBlue = new Set(topEntries(stats.blueOmit, 4, "desc").map(([n]) => n));
    const tags = [];
    if (hotBlue.has(row.blue)) tags.push("高频");
    if (omitBlue.has(row.blue)) tags.push("久未出");
    return tags.length ? tags.join("/") : "普通";
  }

  function simpleCell(text) {
    return `<span class="history-value">${escapeHtml(text)}</span>`;
  }

  function staticCrowdRiskLabel(nums) {
    return crowdRiskLabel(staticCrowdRiskScore(nums));
  }

  function staticCrowdRiskScore(nums) {
    const sorted = nums.slice().sort((a, b) => a - b);
    const birthdayOnly = sorted.every((n) => n <= 31);
    const tailCounts = {};
    let maxTail = 0;
    let score = 0;

    sorted.forEach((n) => {
      const tail = n % 10;
      tailCounts[tail] = (tailCounts[tail] || 0) + 1;
      maxTail = Math.max(maxTail, tailCounts[tail]);
    });

    if (birthdayOnly) score += 0.8;
    if (maxConsecutiveRun(sorted) >= 3) score += (maxConsecutiveRun(sorted) - 2) * 0.7;
    if (maxTail >= 3) score += (maxTail - 2) * 0.45;
    if (sorted.every((n) => n % 2 === 0) || sorted.every((n) => n % 2 === 1)) score += 1.2;
    if (sorted.every((n) => n <= 16) || sorted.every((n) => n >= 17)) score += 1.2;

    return score;
  }

  function topEntries(map, count, order) {
    return Object.entries(map)
      .map(([n, v]) => [Number(n), Number(v)])
      .sort((a, b) => order === "asc" ? a[1] - b[1] || a[0] - b[0] : b[1] - a[1] || a[0] - b[0])
      .slice(0, count);
  }

  function topBlueSignals(signals, count) {
    return Object.entries(signals)
      .map(([n, signal]) => [Number(n), signal])
      .filter(([, signal]) => signal.hotEvidence >= BLUE_SIGNAL_MIN || signal.starred)
      .sort((a, b) => b[1].hotEvidence - a[1].hotEvidence || b[1].freqZ - a[1].freqZ || a[0] - b[0])
      .slice(0, count);
  }

  function topRedSignals(signals, count) {
    return Object.entries(signals)
      .map(([n, signal]) => [Number(n), signal])
      .filter(([, signal]) => signal.hotEvidence >= RED_SIGNAL_MIN || signal.omissionTail >= 0.8 || signal.starred)
      .sort((a, b) => {
        const scoreA = bScore(a[1]);
        const scoreB = bScore(b[1]);
        return scoreB - scoreA || a[0] - b[0];
      })
      .slice(0, count);
  }

  function bScore(signal) {
    return signal.hotEvidence * 0.5 + signal.omissionTail * 0.3 + Math.max(0, signal.recentZ) / 3 * 0.2;
  }

  function starBlueSignals(signals) {
    return Object.entries(signals)
      .filter(([, signal]) => signal.starred)
      .map(([n]) => Number(n));
  }

  function analysisCard(title, content) {
    return `<div class="analysis-card"><h3>${escapeHtml(title)}</h3>${content}</div>`;
  }

  function pillList(items) {
    return `<div class="pill-list">${items.map((item) => `<span class="pill">${escapeHtml(item)}</span>`).join("")}</div>`;
  }

  function historyShapeSummary(rows) {
    const oddEven = {};
    const smallBig = {};
    const sumBands = {};
    let sumTotal = 0;

    rows.forEach((row) => {
      const odd = row.red.filter((n) => n % 2 === 1).length;
      const small = row.red.filter((n) => n <= 16).length;
      const sum = row.red.reduce((a, b) => a + b, 0);
      const bandStart = Math.floor(sum / 20) * 20;
      oddEven[`${odd}:${6 - odd}`] = (oddEven[`${odd}:${6 - odd}`] || 0) + 1;
      smallBig[`${small}:${6 - small}`] = (smallBig[`${small}:${6 - small}`] || 0) + 1;
      sumBands[`${bandStart}-${bandStart + 19}`] = (sumBands[`${bandStart}-${bandStart + 19}`] || 0) + 1;
      sumTotal += sum;
    });

    return {
      oddEven: mostCommonLabel(oddEven),
      smallBig: mostCommonLabel(smallBig),
      sumBand: mostCommonLabel(sumBands),
      avgSum: rows.length ? Math.round(sumTotal / rows.length) : 0
    };
  }

  function mostCommonLabel(map) {
    const entries = Object.entries(map).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    return entries.length ? `${entries[0][0]} (${entries[0][1]}期)` : "无";
  }

  function strategyPoints(stats, shape) {
    const hotRed = topEntries(stats.redFreq, 4, "desc").map(([n]) => pad(n)).join(" ");
    const omitRed = topEntries(stats.redOmit, 4, "desc").map(([n]) => pad(n)).join(" ");
    const blueSignals = topBlueSignals(buildBlueSignals(stats), 3).map(([n]) => pad(n)).join(" ");
    return [
      `红球建议用冷热混合：热号参考 ${hotRed}，长遗漏参考 ${omitRed}，不要全追单一方向。`,
      `红蓝球都按接近均匀概率处理，历史信号只做小幅加权；蓝球参考 ${blueSignals || "无"}，长期遗漏不作为回补依据。`,
      `形态优先靠近历史主流：奇偶 ${shape.oddEven}，大小 ${shape.smallBig}，和值集中在 ${shape.sumBand} 附近。`,
      "多组投注时优先降低组间重号，比把资金堆在高度相似的几组号码上更有效。",
      "如果没有非常确定的胆码，优先用 7+2 或 8+2 复式；只有强看好 1-2 个红球时再用胆拖。"
    ];
  }

  function buildStrategyResearchRows() {
    const windows = [30, 50, 100];
    const rows = [];
    const expectedRed8 = 8 * 6 / RED_MAX;
    const expectedBlue4 = 4 / BLUE_MAX;

    for (const window of windows) {
      if (history.length <= window) continue;
      const results = {
        hot: [],
        omission: [],
        cold: [],
        signal: [],
        repeat: [],
        blueHot: [],
        blueOmit: [],
        blueSignal: []
      };

      for (let i = window; i < history.length; i++) {
        const prior = history.slice(i - window, i);
        const prev = history[i - 1];
        const s = buildStats(prior, prior);
        const redHot = topEntries(s.redFreq, 8, "desc").map(([n]) => n);
        const redOmit = topEntries(s.redOmit, 8, "desc").map(([n]) => n);
        const redCold = topEntries(s.redFreq, 8, "asc").map(([n]) => n);
        const redSignal = topRedSignals(buildRedSignals(s), 8).map(([n]) => n);
        const blueHot = topEntries(s.blueFreq, 4, "desc").map(([n]) => n);
        const blueOmit = topEntries(s.blueOmit, 4, "desc").map(([n]) => n);
        const blueSignal = topBlueSignals(buildBlueSignals(s), 4).map(([n]) => n);
        const actual = history[i];

        results.hot.push(countOverlap(actual.red, redHot));
        results.omission.push(countOverlap(actual.red, redOmit));
        results.cold.push(countOverlap(actual.red, redCold));
        results.signal.push(countOverlap(actual.red, redSignal));
        results.repeat.push(countOverlap(actual.red, prev.red));
        results.blueHot.push(blueHot.includes(actual.blue) ? 1 : 0);
        results.blueOmit.push(blueOmit.includes(actual.blue) ? 1 : 0);
        results.blueSignal.push(blueSignal.includes(actual.blue) ? 1 : 0);
      }

      rows.push(
        {
          name: "红球热号 Top8",
          window: `前 ${window} 期`,
          n: results.hot.length,
          avg: mean(results.hot).toFixed(3),
          p50: quantile(results.hot, 0.5).toFixed(0),
          p90: quantile(results.hot, 0.9).toFixed(0),
          note: Math.abs(mean(results.hot) - expectedRed8) < 0.03 ? "和随机几乎一样" : "略有偏差，但不足以做重仓依据"
        },
        {
          name: "红球遗漏 Top8",
          window: `前 ${window} 期`,
          n: results.omission.length,
          avg: mean(results.omission).toFixed(3),
          p50: quantile(results.omission, 0.5).toFixed(0),
          p90: quantile(results.omission, 0.9).toFixed(0),
          note: mean(results.omission) < expectedRed8 ? "低于随机期望" : "无稳定优势"
        },
        {
          name: "红球冷号 Top8",
          window: `前 ${window} 期`,
          n: results.cold.length,
          avg: mean(results.cold).toFixed(3),
          p50: quantile(results.cold, 0.5).toFixed(0),
          p90: quantile(results.cold, 0.9).toFixed(0),
          note: mean(results.cold) < expectedRed8 ? "低于随机期望" : "无稳定优势"
        },
        {
          name: "红球弱信号 Top8",
          window: `前 ${window} 期`,
          n: results.signal.length,
          avg: mean(results.signal).toFixed(3),
          p50: quantile(results.signal, 0.5).toFixed(0),
          p90: quantile(results.signal, 0.9).toFixed(0),
          note: "只能做轻微筛选，不是预测"
        },
        {
          name: "上期重号",
          window: `前 ${window} 期`,
          n: results.repeat.length,
          avg: mean(results.repeat).toFixed(3),
          p50: quantile(results.repeat, 0.5).toFixed(0),
          p90: quantile(results.repeat, 0.9).toFixed(0),
          note: "属于自然波动"
        },
        {
          name: "蓝球热号 Top4",
          window: `前 ${window} 期`,
          n: results.blueHot.length,
          avg: mean(results.blueHot).toFixed(3),
          p50: quantile(results.blueHot, 0.5).toFixed(0),
          p90: quantile(results.blueHot, 0.9).toFixed(0),
          note: Math.abs(mean(results.blueHot) - expectedBlue4) < 0.02 ? "和均匀概率接近" : "轻微波动"
        },
        {
          name: "蓝球遗漏 Top4",
          window: `前 ${window} 期`,
          n: results.blueOmit.length,
          avg: mean(results.blueOmit).toFixed(3),
          p50: quantile(results.blueOmit, 0.5).toFixed(0),
          p90: quantile(results.blueOmit, 0.9).toFixed(0),
          note: "不建议按遗漏重仓"
        },
        {
          name: "蓝球弱信号 Top4",
          window: `前 ${window} 期`,
          n: results.blueSignal.length,
          avg: mean(results.blueSignal).toFixed(3),
          p50: quantile(results.blueSignal, 0.5).toFixed(0),
          p90: quantile(results.blueSignal, 0.9).toFixed(0),
          note: "可做展示，不宜当主依据"
        }
      );
    }

    return rows;
  }

  function mean(nums) {
    return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : 0;
  }

  function quantile(nums, q) {
    if (!nums.length) return 0;
    const sorted = nums.slice().sort((a, b) => a - b);
    const index = Math.min(sorted.length - 1, Math.max(0, Math.round((sorted.length - 1) * q)));
    return sorted[index];
  }

  function latestDrawReview() {
    if (history.length < 31) return "<span class=\"muted-text\">数据不足，无法复盘。</span>";
    const index = history.length - 1;
    const row = history[index];
    const prior30 = history.slice(Math.max(0, index - 30), index);
    const prior50 = history.slice(Math.max(0, index - 50), index);
    const stats30 = buildStats(prior30, prior30);
    const stats50 = buildStats(prior50, prior50);
    const hot30 = topEntries(stats30.redFreq, 8, "desc").map(([n]) => n);
    const omit30 = topEntries(stats30.redOmit, 8, "desc").map(([n]) => n);
    const hot50 = topEntries(stats50.redFreq, 8, "desc").map(([n]) => n);
    const omit50 = topEntries(stats50.redOmit, 8, "desc").map(([n]) => n);
    const repeat = history[index - 1] ? row.red.filter((n) => history[index - 1].red.includes(n)) : [];
    const redSignals = topRedSignals(buildRedSignals(stats30), 10).map(([n]) => n);
    const blueSignals = topBlueSignals(buildBlueSignals(stats30), 4).map(([n]) => n);

    return `
      <div class="review-lines">
        <span>${row.issue} 开出红 ${formatNums(row.red)}，蓝 ${pad(row.blue)}。</span>
        <span>前30热号命中 ${countOverlap(row.red, hot30)}，前30遗漏命中 ${countOverlap(row.red, omit30)}，弱信号命中 ${countOverlap(row.red, redSignals)}。</span>
        <span>前50热号命中 ${countOverlap(row.red, hot50)}，前50遗漏命中 ${countOverlap(row.red, omit50)}，上期重号 ${repeat.length ? formatNums(repeat) : "无"}。</span>
        <span>蓝球${blueSignals.includes(row.blue) ? "落在" : "没有落在"}前30统计信号内。结论：历史信号波动很大，应做覆盖分散，不能重仓单一解释。</span>
      </div>
    `;
  }

  function recommendationSeed() {
    const latest = history[history.length - 1];
    return [
      latest ? latest.issue : "empty",
      els.scopeSelect.value,
      els.strategySelect.value,
      els.modeSelect.value,
      els.redCount.value,
      els.blueCount.value,
      els.danCount.value,
      els.tuoCount.value,
      els.dtBlueCount.value,
      els.shapeFilter.checked ? "shape" : "no-shape",
      els.avoidPopular.checked ? "crowd" : "no-crowd",
      els.portfolioCount.value,
      els.maxOverlap.value
    ].join("|");
  }

  function randomEntropy() {
    if (globalThis.crypto && typeof globalThis.crypto.getRandomValues === "function") {
      const values = new Uint32Array(2);
      globalThis.crypto.getRandomValues(values);
      return `${values[0]}-${values[1]}`;
    }
    return `${Date.now()}-${Math.random()}`;
  }

  function createRng(seedText) {
    let seed = hashString(seedText);
    return function next() {
      seed += 0x6d2b79f5;
      let t = seed;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function hashString(text) {
    let hash = 2166136261;
    for (let i = 0; i < text.length; i++) {
      hash ^= text.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function random01() {
    return rng();
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }
})();
