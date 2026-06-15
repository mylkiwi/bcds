(function () {
  const RED_MAX = 33;
  const BLUE_MAX = 16;
  const BLUE_BASE_PROBABILITY = 1 / BLUE_MAX;
  const BLUE_SIGNAL_MIN = 0.25;
  const BLUE_STAR_Z = 2;
  const TOTAL_SINGLE = comb(33, 6) * 16;
  const MODEL_WEIGHTS = {
    dispersion: 0.4,
    shape: 0.25,
    crowd: 0.15,
    blue: 0.1,
    history: 0.1
  };
  const history = normalizeHistory(window.SSQ_HISTORY || []);

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
    const scope = getScopeHistory();
    const stats = buildStats(scope, history);
    const strategy = els.strategySelect.value;
    const mode = els.modeSelect.value;
    const scores = buildScores(stats, strategy);
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
    renderNumberReasons(scheme, stats);
    renderPortfolio(buildPortfolio(mode, scores, strategy, options, params, scheme));
    renderHeatmaps(stats, scheme);
    renderHistoryAnalysis(stats, scope);
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
      for (let i = 0; i < 180; i++) {
        const candidate = buildScheme(mode, scores, strategy, options, params);
        if (schemes.some((scheme) => sameScheme(scheme, candidate))) continue;
        const overlap = Math.max(...schemes.map((scheme) => redOverlap(scheme.red, candidate.red)));
        const allowedBonus = overlap <= maxOverlap ? 0.03 : 0;
        const score = schemeQualityScore(candidate, scores, options, schemes) + allowedBonus;
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

  function buildStats(scope, allRows) {
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
      redOmit[n] = omission(allRows, (row) => row.red.includes(n));
    }

    for (let n = 1; n <= BLUE_MAX; n++) {
      blueOmit[n] = omission(allRows, (row) => row.blue === n);
    }

    return { redFreq, blueFreq, redRecent, blueRecent, redOmit, blueOmit, scopeSize: scope.length, recentSize: recentRows.length };
  }

  function buildScores(stats, strategy) {
    const red = scoreRange(RED_MAX, strategy, stats.redFreq, stats.redRecent, stats.redOmit);
    const blueSignals = buildBlueSignals(stats);
    const blue = scoreBlueRange(stats, strategy, blueSignals);
    const latest = history[history.length - 1];
    const meta = {
      hotRed: topEntries(stats.redFreq, 8, "desc").map(([n]) => n),
      omitRed: topEntries(stats.redOmit, 8, "desc").map(([n]) => n),
      latestRed: latest ? latest.red : [],
      hotBlue: topEntries(stats.blueFreq, 4, "desc").map(([n]) => n),
      omitBlue: topEntries(stats.blueOmit, 4, "desc").map(([n]) => n),
      signalBlue: topBlueSignals(blueSignals, 4).map(([n]) => n),
      starBlue: starBlueSignals(blueSignals),
      blueSignals,
      latestBlue: latest ? latest.blue : null
    };
    red.__meta = meta;
    blue.__meta = meta;
    return { red, blue, meta };
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
      const jitter = Math.random();
      let score;

      if (strategy === "random") {
        score = jitter;
      } else if (strategy === "hot") {
        score = 0.58 + signal.hotEvidence * 0.18 + Math.max(0, signal.recentZ) / 3 * 0.06 + jitter * 0.02;
      } else if (strategy === "cold") {
        score = 0.58 + signal.coldEvidence * 0.08 + signal.omissionTail * 0.02 + jitter * 0.02;
      } else if (strategy === "omission") {
        score = 0.58 + signal.hotEvidence * 0.08 + signal.omissionTail * 0.02 + jitter * 0.02;
      } else if (strategy === "mixed") {
        score = 0.56 + signal.hotEvidence * 0.08 + signal.coldEvidence * 0.04 + jitter * 0.05;
      } else {
        score = 0.58 + signal.hotEvidence * 0.08 + Math.max(0, signal.recentZ) / 3 * 0.04 + jitter * 0.02;
      }

      result[n] = clamp01(score);
    }

    return result;
  }

  function scoreRange(max, strategy, freq, recent, omit) {
    const freqNorm = normalizeMap(freq, max);
    const recentNorm = normalizeMap(recent, max);
    const omitNorm = normalizeMap(omit, max);
    const result = {};

    for (let n = 1; n <= max; n++) {
      const f = freqNorm[n];
      const r = recentNorm[n];
      const o = omitNorm[n];
      let score;

      if (strategy === "hot") {
        score = f * 0.65 + r * 0.25 + (1 - o) * 0.1;
      } else if (strategy === "omission") {
        score = o * 0.55 + f * 0.25 + r * 0.2;
      } else if (strategy === "cold") {
        score = (1 - f) * 0.55 + o * 0.35 + (1 - r) * 0.1;
      } else if (strategy === "mixed") {
        score = f * 0.32 + r * 0.18 + o * 0.34 + Math.random() * 0.16;
      } else if (strategy === "random") {
        score = Math.random();
      } else {
        score = f * 0.34 + r * 0.22 + o * 0.28 + Math.random() * 0.16;
      }

      result[n] = score;
    }

    return result;
  }

  function buildComplexScheme(scores, redCount, blueCount, strategy, options) {
    const red = chooseRedSet(scores.red, redCount, strategy, options);
    const blue = chooseBlueSet(scores.blue, blueCount);
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
    const blue = chooseBlueSet(scores.blue, blueCount);
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

  function chooseRedSet(scoreMap, count, strategy, options) {
    let best = null;
    let bestScore = -Infinity;
    const attempts = strategy === "random" ? 60 : 420;

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

  function chooseBlueSet(scoreMap, count) {
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

      let roll = Math.random() * total;
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
      balanced: "红球按反推区间，蓝球按统计证据弱加权，不追长期遗漏",
      hot: "红球高频倾斜；蓝球只在频率偏差有证据时轻微倾斜",
      omission: "红球遗漏回补；蓝球长期遗漏只作展示和极弱扰动",
      cold: "红球冷号补位；蓝球冷门仅作分散覆盖，不视为更该出",
      mixed: "红球冷热混合；蓝球接近均匀底池，叠加少量统计扰动",
      random: "随机底池：随机生成候选，再按反推规则和形态筛选"
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
    const meta = scores.meta || {};
    const hot = countOverlap(scheme.red, meta.hotRed || []);
    const omit = countOverlap(scheme.red, meta.omitRed || []);
    const repeat = countOverlap(scheme.red, meta.latestRed || []);
    const blueSignal = countOverlap(scheme.blue, meta.signalBlue || []);
    const blueStar = countOverlap(scheme.blue, meta.starBlue || []);
    const blueRepeat = meta.latestBlue && scheme.blue.includes(meta.latestBlue) ? 1 : 0;

    els.strategyCompare.innerHTML = `
      <div class="subhead"><h3>新旧策略对比</h3><span>基于逐期反推后的规则评分</span></div>
      <div class="compare-grid">
        <div class="compare-card">
          <strong>旧策略</strong>
          <span>频次、近期、遗漏混合打分，蓝球会被长期遗漏明显拉高，容易形成追冷。</span>
        </div>
        <div class="compare-card">
          <strong>新策略</strong>
          <span>红球 ${hot} 个高频、${omit} 个久未出、${repeat} 个上期重号；蓝球 ${blueSignal} 个统计信号、${blueStar} 个星标，${blueRepeat ? "含上期蓝" : "未重复上期蓝"}。</span>
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

  function renderNumberReasons(scheme, stats) {
    const redRoles = scheme.type === "dantuo"
      ? Object.fromEntries([
          ...scheme.dantuo.dan.map((n) => [n, "胆码"]),
          ...scheme.dantuo.tuo.map((n) => [n, "拖码"])
        ])
      : Object.fromEntries(scheme.red.map((n) => [n, "红球"]));
    const redRows = scheme.red.map((n) => reasonRow(pad(n), redRoles[n], stats.redFreq[n], stats.redRecent[n], stats.redOmit[n], numberReason(stats.redFreq[n], stats.redRecent[n], stats.redOmit[n])));
    const blueSignals = buildBlueSignals(stats);
    const blueRows = scheme.blue.map((n) => reasonRow(pad(n), "蓝球", stats.blueFreq[n], stats.blueRecent[n], stats.blueOmit[n], blueNumberReason(n, stats, blueSignals[n])));

    els.numberReasons.innerHTML = `
      <div class="subhead"><h3>号码解释</h3><span>频次/近 20 期/遗漏</span></div>
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

    els.portfolioPanel.innerHTML = `
      <div class="subhead"><h3>低重叠组合池</h3><span>多组投注时优先降低重复覆盖</span></div>
      <div class="portfolio-list">${cards}</div>
    `;
  }

  function initPurchasePanel() {
    const savedToken = localStorage.getItem("ssqAdminToken") || "";
    els.adminToken.value = savedToken;
    els.purchaseIssue.value = nextIssue();
    togglePurchaseMode();
    if (savedToken) {
      loadPurchaseState();
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
    if (!response.ok) throw new Error(data.error || `请求失败 ${response.status}`);
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
    const rows = history.slice(-20).reverse();
    const redHeads = Array.from({ length: RED_MAX }, (_, i) => `<th>${pad(i + 1)}</th>`).join("");
    const body = rows
      .map((row) => {
        const redSet = new Set(row.red);
        const cells = Array.from({ length: RED_MAX }, (_, i) => {
          const n = i + 1;
          return `<td>${redSet.has(n) ? `<span class="hit-red">${pad(n)}</span>` : "<span class='empty-cell'>·</span>"}</td>`;
        }).join("");
        return `<tr><td>${row.issue}</td><td>${row.date}</td>${cells}<td><span class="hit-blue">${pad(row.blue)}</span></td></tr>`;
      })
      .join("");
    els.trendTable.innerHTML = `<table><thead><tr><th>期号</th><th>日期</th>${redHeads}<th>蓝</th></tr></thead><tbody>${body}</tbody></table>`;
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
      `蓝球默认按 1/16 均匀概率处理；统计信号参考 ${blueSignals || "无"}，长期遗漏不作为回补依据。`,
      `形态优先靠近历史主流：奇偶 ${shape.oddEven}，大小 ${shape.smallBig}，和值集中在 ${shape.sumBand} 附近。`,
      "多组投注时优先降低组间重号，比把资金堆在高度相似的几组号码上更有效。",
      "如果没有非常确定的胆码，优先用 7+2 或 8+2 复式；只有强看好 1-2 个红球时再用胆拖。"
    ];
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
