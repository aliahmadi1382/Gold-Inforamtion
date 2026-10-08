"use strict";
const $ = (id) => document.getElementById(id);
const fa = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 3 });
const fmt = (value) => (value == null ? "ناموجود" : fa.format(value));
const names = {
  bls: "BLS",
  unchanged: "بدون تغییر",
  context_only: "فقط تغییر زمینه",
  changed: "دارای تغییر",
  unavailable: "نامعلوم",
  london_afternoon_fixing_average: "تثبیت عصر لندن؛ تا مه ۲۰۲۵",
  spot_daily_average: "میانگین نقدی؛ پس از مرز ژوئن ۲۰۲۵",
  monthly_research: "پژوهش ماهانهٔ همین گزارش",
  pearson: "ضریب Pearson",
  spearman: "ضریب Spearman",
  constant: "سری ثابت؛ ضریب تعریف‌نشده",
  estimated: "ضریب قابل گزارش",
  too_short: "کمتر از حداقل نمونه",
  currency_per_troy_ounce: "دلار/اونس تروا",
  percent: "درصد",
  contracts: "قرارداد",
  percent_sa: "درصد؛ تعدیل فصلی",
  percent_change_mom_sa: "تغییر ماهانهٔ درصدی؛ تعدیل فصلی",
  percent_change_mom_annualized_sa:
    "تغییر ماهانه با نرخ سالانه‌شده؛ درصد، تعدیل فصلی",
  BLS_CPI_U_SA_MOM: "تورم ماهانهٔ CPI در سند BLS",
  BLS_UNRATE_SA: "نرخ بیکاری در سند BLS",
  T10YIE: "تورم سربه‌سر ده‌ساله",
  WB_GOLD_MONTHLY: "میانگین ماهانهٔ طلا",
  other_reportable: "سایر گزارش‌شونده‌ها",
  producer_merchant_processor_user: "تولیدکنندگان و بازرگانان",
  swap_dealer: "معامله‌گران سوآپ",
  headline_in_document: "دورهٔ اصلی سند",
  previous_in_document: "دورهٔ قبلی در سند",
  index_jan2006_100: "شاخص؛ ژانویه ۲۰۰۶=۱۰۰",
  index_1982_1984_100_sa: "شاخص؛ ۱۹۸۲–۱۹۸۴=۱۰۰",
  alpha_vantage_gold: "قیمت مرجع طلا · Alpha Vantage",
  world_bank_pink_sheet: "مرجع ماهانه · World Bank",
  fred: "شاخص‌های کلان · FRED",
  philadelphia_fed_pcpi: "برآورد انتشار CPI · فدرال‌رزرو فیلادلفیا",
  cftc_disaggregated: "موقعیت معامله‌گران · CFTC",
  DFF: "نرخ وجوه فدرال",
  DGS10: "بازده اوراق ده‌ساله",
  DFII10: "بازده واقعی ده‌ساله",
  DTWEXBGS: "شاخص گستردهٔ دلار",
  CPIAUCSL: "شاخص قیمت مصرف‌کننده",
  PHILLY_PCPI_FIRST: "فیلادلفیا · تورم CPI · برآورد انتشار اول",
  PHILLY_PCPI_SECOND: "فیلادلفیا · تورم CPI · برآورد انتشار دوم",
  PHILLY_PCPI_THIRD: "فیلادلفیا · تورم CPI · برآورد انتشار سوم",
  PHILLY_PCPI_MOST_RECENT: "فیلادلفیا · تورم CPI · آخرین نسخهٔ فایل",
  PCEPI: "شاخص قیمت مصرف شخصی",
  UNRATE: "نرخ بیکاری",
  managed_money: "مدیریت سرمایه",
  producer_merchant: "تولیدکنندگان و بازرگانان",
  swap_dealers: "معامله‌گران سوآپ",
  other_reportables: "سایر گزارش‌شونده‌ها",
  nonreportable: "گزارش‌نشونده‌ها",
  quality: "کیفیت داده",
  price: "قیمت روزانه",
  macro: "شاخص‌های کلان",
  calendar: "تقویم انتشار",
  monthly: "روابط ماهانه",
  releases: "اسناد و مقادیر انتشار",
  revisions: "دفتر اصلاحیه",
  positioning: "موقعیت‌های COT",
  observation: "مشاهدهٔ شاخص",
  price_close: "قیمت مرجع",
  completed: "تکمیل‌شده",
  partial: "بخشی تکمیل‌شده",
  in_progress: "در حال توسعه",
  blocked: "وابسته به پیش‌نیاز",
  not_started: "شروع نشده",
  succeeded: "موفق",
  success: "موفق",
  http_error: "خطای HTTP",
  connection_error: "خطای اتصال",
  response_too_large: "پاسخ بیش از حد مجاز",
  failed: "ناموفق",
  running: "ناتمام",
  available: "در دسترس",
  limited: "دارای محدودیت",
  missing: "فاقد شاهد کافی",
  with_limits: "دارای محدودیت",
  compiled: "گردآوری‌شده",
  attention: "نیاز به بررسی",
  clear: "بدون خطای جاری در اسناد",
  no_history: "بدون سابقه",
  inspect_unfinished: "بررسی اجرای ناتمام",
  check_quota_before_manual_retry: "بررسی سهمیه پیش از تلاش دستی",
  manual_retry_after_transport_budget: "بررسی و سپس تلاش دستی",
  repair_before_retry: "رفع علت پیش از تلاش مجدد",
  inspect_before_retry: "بررسی شواهد پیش از اقدام",
  none: "—",
};
const title = (key) => names[key] || key;
const unitLabel = (identity) =>
  identity.unit === "currency_per_troy_ounce"
    ? (identity.currency || "واحد پول") + " / اونس تروا"
    : title(identity.unit);
const stamp = (value) =>
  value
    ? value
        .replace("T", " · ")
        .replace(/\.\d+(?=[+Z])/, "")
        .replace("+00:00", " UTC")
    : "ثبت نشده";
const day = (value) => (value ? value.slice(0, 10) : "ناموجود");
function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function clear(node) {
  node.replaceChildren();
}
function badge(status) {
  return el(
    "span",
    title(status),
    "pill " +
      (["completed", "succeeded", "available", "clear"].includes(status)
        ? "success"
        : ["failed", "missing"].includes(status)
          ? "danger"
          : "warning"),
  );
}
function kpi(label, value, note) {
  const n = el("article", null, "kpi");
  n.append(el("div", label, "label"), el("strong", value), el("small", note));
  return n;
}
function meta(node, values) {
  clear(node);
  values.forEach((value) => node.append(el("span", value)));
}
function table(node, headers, rows) {
  clear(node);
  const t = el("table"),
    head = el("thead"),
    tr = el("tr");
  headers.forEach((h) => tr.append(el("th", h)));
  head.append(tr);
  t.append(head);
  const body = el("tbody");
  rows.forEach((row) => {
    const r = el("tr");
    row.forEach((c) => {
      const td = el("td");
      if (c instanceof Node) td.append(c);
      else td.textContent = c == null ? "—" : c;
      r.append(td);
    });
    body.append(r);
  });
  t.append(body);
  node.append(t);
  if (!rows.length)
    node.append(el("p", "رکوردی در این دامنه وجود ندارد.", "muted"));
}
function download(name, text, mime) {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const a = el("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function get(path) {
  const r = await fetch(path, { cache: "no-store" });
  if (!r.ok)
    throw new Error("درخواست این نما معتبر نبود؛ بازه و انتخاب را بررسی کنید.");
  return r.json();
}
function error(message) {
  $("error").hidden = false;
  $("error").textContent = message;
}
let data,
  selectedSeries,
  selectedReport,
  requestNumber = 0;
const viewTitles = {
  overview: "نمای کلی پژوهش",
  explore: "کاوش تاریخچهٔ داده",
  reports: "گزارش‌های پژوهش",
  operations: "سلامت عملیات",
  roadmap: "مسیر و فازهای پروژه",
};
function navigate(view) {
  if (!viewTitles[view]) return;
  document.querySelectorAll(".view").forEach((n) => (n.hidden = n.id !== view));
  document
    .querySelectorAll("nav button")
    .forEach((n) => n.classList.toggle("active", n.dataset.view === view));
  $("view-title").textContent = viewTitles[view];
  history.replaceState(null, "", "#" + view);
  window.scrollTo({ top: 0 });
}
function seriesLabel(s) {
  const i = s.identity;
  const d = i.dimensions || {};
  let label = i.series
    ? title(i.series)
    : i.category
      ? title(i.category)
      : i.instrument || i.dataset;
  return (
    label +
    " · " +
    (i.kind === "positioning" ? "خالص قرارداد" : unitLabel(i)) +
    " · " +
    title(i.source) +
    (i.vintage ? " · vintage " + i.vintage : "") +
    (d.realtime_start && !i.vintage
      ? " · نسخهٔ منبع " + d.realtime_start
      : "") +
    (d.release_id
      ? " · سند " + d.release_id + " · " + title(d.period_role)
      : "") +
    (d.methodology ? " · " + title(d.methodology) : "") +
    (i.synthetic ? " · مصنوعی" : "")
  );
}
function svgNode(tag, attrs = {}, text) {
  const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v));
  if (text != null) n.textContent = text;
  return n;
}
function chart(
  container,
  points,
  identity,
  compact = false,
  inspect = null,
  domain = null,
) {
  clear(container);
  const values = points.filter(
    (p) => p.value != null && Number.isFinite(p.value),
  );
  if (!values.length) {
    container.append(
      el("div", "برای این سری و بازه مقدار قابل نمایش نداریم.", "chart-empty"),
    );
    return;
  }
  const w = 920,
    h = compact ? 290 : 370,
    pad = { l: 82, r: 20, t: 22, b: 42 };
  const times = points.map((p) => Date.parse(p.observed_at));
  const minT = Math.min(...times),
    maxT = Math.max(...times);
  let min = Math.min(...values.map((p) => p.value)),
    max = Math.max(...values.map((p) => p.value));
  let span = max - min || Math.max(Math.abs(max) * 0.1, 1);
  min -= span * 0.06;
  max += span * 0.06;
  if (domain) [min, max] = domain;
  const x = (t) =>
      pad.l + ((t - minT) / (maxT - minT || 1)) * (w - pad.l - pad.r),
    y = (v) => h - pad.b - ((v - min) / (max - min)) * (h - pad.t - pad.b);
  const shell = el("div", null, "chart-shell"),
    svg = svgNode("svg", {
      viewBox: `0 0 ${w} ${h}`,
      role: "img",
      "aria-label":
        seriesLabel({ identity }) +
        "؛ " +
        points[0].date +
        " تا " +
        points.at(-1).date,
    });
  for (let i = 0; i < 5; i++) {
    const value = min + ((max - min) * i) / 4,
      yy = y(value);
    svg.append(
      svgNode("line", {
        x1: pad.l,
        x2: w - pad.r,
        y1: yy,
        y2: yy,
        stroke: "#e9eef1",
        "stroke-dasharray": "3 4",
      }),
    );
    svg.append(
      svgNode(
        "text",
        {
          x: pad.l - 12,
          y: yy + 4,
          "text-anchor": "end",
          fill: "#83919a",
          "font-size": 11,
        },
        new Intl.NumberFormat("en", { maximumFractionDigits: 2 }).format(value),
      ),
    );
  }
  for (let i = 0; i < 5; i++) {
    const time = minT + ((maxT - minT) * i) / 4;
    svg.append(
      svgNode(
        "text",
        {
          x: x(time),
          y: h - 12,
          "text-anchor": i === 0 ? "start" : i === 4 ? "end" : "middle",
          fill: "#83919a",
          "font-size": 11,
        },
        new Date(time).toISOString().slice(0, 10),
      ),
    );
  }
  const gaps = times
    .slice(1)
    .map((t, i) => t - times[i])
    .filter((v) => v > 0)
    .sort((a, b) => a - b);
  const median = gaps[Math.floor(gaps.length / 2)] || 86400000;
  const maxGap =
    identity.kind === "price_close"
      ? 7 * 86400000
      : identity.kind === "positioning"
        ? 14 * 86400000
        : identity.source === "world_bank_pink_sheet"
          ? 45 * 86400000
          : median * 3;
  let segments = [],
    segment = [],
    previous = null;
  for (let i = 0; i < points.length; i++) {
    const p = points[i];
    if (p.value == null || !Number.isFinite(p.value)) {
      if (segment.length) segments.push(segment);
      segment = [];
      previous = null;
      continue;
    }
    if (previous != null && times[i] - previous > maxGap) {
      if (segment.length) segments.push(segment);
      segment = [];
    }
    segment.push([x(times[i]), y(p.value)]);
    previous = times[i];
  }
  if (segment.length) segments.push(segment);
  for (const part of segments) {
    if (part.length === 1)
      svg.append(
        svgNode("circle", {
          cx: part[0][0],
          cy: part[0][1],
          r: 2.5,
          fill: "#ad802f",
        }),
      );
    else
      svg.append(
        svgNode("path", {
          d: part
            .map(
              (p, i) =>
                (i ? "L" : "M") + p[0].toFixed(2) + " " + p[1].toFixed(2),
            )
            .join(" "),
          fill: "none",
          stroke: identity.kind === "positioning" ? "#387b89" : "#ad802f",
          "stroke-width": 2,
          "stroke-linejoin": "round",
        }),
      );
  }
  const cursor = svgNode("line", {
      y1: pad.t,
      y2: h - pad.b,
      stroke: "#c7d2da",
      "stroke-dasharray": "4 4",
      visibility: "hidden",
    }),
    dot = svgNode("circle", { r: 4, fill: "#142c37", visibility: "hidden" });
  svg.append(cursor, dot);
  const tip = el("div", null, "chart-tooltip");
  tip.hidden = true;
  shell.append(svg, tip);
  container.append(shell);
  function nearest(event) {
    const rect = svg.getBoundingClientRect(),
      xx = ((event.clientX - rect.left) / rect.width) * w;
    let best = null,
      dist = Infinity;
    for (const p of values) {
      const d = Math.abs(x(Date.parse(p.observed_at)) - xx);
      if (d < dist) {
        best = p;
        dist = d;
      }
    }
    return best;
  }
  svg.addEventListener("pointermove", (e) => {
    const p = nearest(e);
    if (!p) return;
    const px = x(Date.parse(p.observed_at));
    cursor.setAttribute("x1", px);
    cursor.setAttribute("x2", px);
    cursor.setAttribute("visibility", "visible");
    dot.setAttribute("cx", px);
    dot.setAttribute("cy", y(p.value));
    dot.setAttribute("visibility", "visible");
    tip.textContent =
      p.date +
      " · " +
      fmt(p.value) +
      " " +
      (identity.kind === "positioning" ? "قرارداد" : unitLabel(identity));
    tip.hidden = false;
    const rect = svg.getBoundingClientRect();
    tip.style.left =
      Math.max(0, Math.min(e.clientX - rect.left + 12, rect.width - 220)) +
      "px";
    tip.style.top = "12px";
  });
  svg.addEventListener("pointerleave", () => {
    tip.hidden = true;
    cursor.setAttribute("visibility", "hidden");
    dot.setAttribute("visibility", "hidden");
  });
  if (inspect) svg.addEventListener("click", (e) => inspect(nearest(e)));
  container.append(
    el(
      "p",
      `${fmt(points.length)} ${domain ? "پنجره" : "مشاهده"} · ${fmt(points.filter((p) => p.value == null).length)} مقدار ناموجود · ${unitLabel(identity)} · ${domain ? "محور عمودی ثابت −۱ تا +۱" : "محور عمودی متناسب با بازه"}؛ null و شکاف‌های بزرگ به هم وصل نمی‌شوند.`,
      "chart-note",
    ),
  );
}
function overview() {
  const last = data.sources.reduce(
    (v, s) => (s.last_retrieved > v ? s.last_retrieved : v),
    "",
  );
  $("overview-cards").append(
    kpi(
      "نسخه‌های رکورد ذخیره‌شده",
      fmt(data.records),
      "شامل اصلاحیه‌ها؛ شمار مشاهدهٔ یکتا نیست",
    ),
    kpi("فایل خام محفوظ", fmt(data.raw_blobs), "دادهٔ واقعی محلی؛ خارج از Git"),
    kpi(
      "گزارش پژوهش تأییدشده",
      fmt(data.reports.length),
      "بسته‌های دارای منشأ و هش معتبر",
    ),
    kpi(
      "آخرین زمان دریافت",
      day(last),
      "زمان دریافت؛ زمان مرجع هر سری متفاوت است",
    ),
  );
  $("overview-alert").textContent =
    "این نما از داده‌های ذخیره‌شده ساخته شده؛ خوراک لحظه‌ای نیست. " +
    (data.health.status === "attention"
      ? "سلامت عملیات نیاز به بررسی دارد؛ خطاها و شواهد قبلی در بخش سلامت عملیات دیده می‌شوند."
      : "تازگی بازار باید با تاریخ مرجع هر منبع بررسی شود.") +
    (data.invalid_report_bundles
      ? " " +
        fmt(data.invalid_report_bundles) +
        " بستهٔ نامعتبر از فهرست گزارش‌ها حذف شده و تأییدشده نمایش داده نمی‌شود."
      : "");
  const phase = data.roadmap.phases.find(
    (p) => p.id === data.roadmap.current_phase,
  );
  $("current-phase").append(
    el("h3", "فاز " + phase.id + " · " + phase.title),
    badge(phase.status),
    el("p", data.roadmap.next_step, "muted"),
  );
  for (const s of data.sources) {
    const card = el("div", null, "source");
    card.append(
      el("h3", title(s.id)),
      el("strong", fmt(s.versions) + " نسخه"),
      el(
        "p",
        (s.kinds.calendar_release ? "آخرین دوره / تقویم: " : "آخرین مرجع: ") +
          day(s.latest_observed),
      ),
      el("p", "آخرین دریافت: " + day(s.last_retrieved)),
    );
    $("source-cards").append(card);
  }
  const gold = data.series.find(
    (s) => s.identity.kind === "price_close" && !s.identity.synthetic,
  );
  if (gold) {
    const end = gold.end,
      start = +end.slice(0, 4) - 5 + end.slice(4);
    get("/api/series?id=" + gold.id + "&start=" + start)
      .then((s) => chart($("overview-chart"), s.points, s.identity, true))
      .catch((e) => error(e.message));
    $("open-gold").onclick = () => {
      navigate("explore");
      $("kind-filter").value = "price_close";
      fillSeries(gold.id);
    };
  } else {
    $("overview-chart").append(
      el("div", "قیمت مرجع واقعی موجود نیست.", "chart-empty"),
    );
    $("open-gold").disabled = true;
  }
}
function fillSeries(preferred) {
  ++requestNumber;
  const kind = $("kind-filter").value;
  const source = $("source-filter").value;
  const choices = data.series.filter(
    (s) =>
      (kind === "all" || s.identity.kind === kind) &&
      (source === "all" || s.identity.source === source),
  );
  clear($("series-select"));
  choices.forEach((s) => {
    const o = el("option", seriesLabel(s));
    o.value = s.id;
    $("series-select").append(o);
  });
  if (preferred && choices.some((s) => s.id === preferred))
    $("series-select").value = preferred;
  setSeriesRange();
}
function setSeriesRange() {
  const s = data.series.find((s) => s.id === $("series-select").value);
  if (!s) {
    clear($("series-meta"));
    clear($("series-records"));
    $("point-detail").hidden = true;
    $("export-series").disabled = true;
    clear($("series-chart"));
    $("series-chart").append(el("p", "سری در این نوع داده موجود نیست."));
    selectedSeries = null;
    return;
  }
  const year = +s.end.slice(0, 4) - 5;
  $("date-start").value =
    s.start > year + s.end.slice(4) ? s.start : year + s.end.slice(4);
  $("date-end").value = s.end;
  showSeries();
}
async function showSeries() {
  selectedSeries = null;
  $("export-series").disabled = true;
  const ticket = ++requestNumber,
    key = $("series-select").value;
  if (!key) return;
  try {
    const query = new URLSearchParams({
        id: key,
        start: $("date-start").value,
        end: $("date-end").value,
      }),
      s = await get("/api/series?" + query);
    if (ticket !== requestNumber) return;
    selectedSeries = s;
    $("export-series").disabled = false;
    $("error").hidden = true;
    $("point-detail").hidden = true;
    meta($("series-meta"), [
      seriesLabel(s),
      "نسخه‌های این سری: " + fmt(s.versions),
      "واحد: " + unitLabel(s.identity),
      ...(s.identity.unit_basis === "instrument_convention"
        ? ["واحد از نام ابزار استنباط شده؛ روش قیمت نیاز به تأیید دارد"]
        : []),
      "مبنای دسترسی: " +
        s.availability_basis
          .map((x) =>
            x === "retrieval_time"
              ? "زمان دریافت؛ انتشار تاریخی تأیید نشده"
              : x === "verified_release"
                ? "سند انتشار تأییدشده"
                : "مصنوعی",
          )
          .join(" / "),
    ]);
    chart($("series-chart"), s.points, s.identity, false, (p) => {
      if (!p) return;
      $("point-detail").hidden = false;
      $("point-detail").textContent =
        "مرجع: " +
        stamp(p.observed_at) +
        " | مقدار: " +
        fmt(p.value) +
        " | دسترسی: " +
        stamp(p.available_at) +
        " | دریافت: " +
        stamp(p.retrieved_at) +
        " | شناسه: " +
        p.record_id +
        " | خام: " +
        p.raw_sha256;
    });
    table(
      $("series-records"),
      ["مرجع", "مقدار", "زمان دسترسی", "زمان دریافت", "شناسهٔ رکورد"],
      s.points
        .slice(-200)
        .reverse()
        .map((p) => [
          p.date,
          fmt(p.value),
          stamp(p.available_at),
          stamp(p.retrieved_at),
          p.record_id,
        ]),
    );
    $("series-records").append(
      el(
        "p",
        "جدول: حداکثر ۲۰۰ مشاهدهٔ آخر بازه؛ CSV شامل همهٔ مشاهدات همین بازه است.",
        "muted",
      ),
    );
  } catch (e) {
    error(e.message);
  }
}
function exportSeries() {
  if (!selectedSeries) return;
  const keys = [
    "date",
    "value",
    "observed_at",
    "available_at",
    "retrieved_at",
    "availability_basis",
    "record_id",
    "raw_sha256",
  ];
  if (selectedSeries.identity.kind === "positioning")
    keys.push("long", "short", "open_interest");
  const rows = [
    keys.join(","),
    ...selectedSeries.points.map((p) =>
      keys.map((k) => (p[k] == null ? "" : String(p[k]))).join(","),
    ),
  ];
  download(
    "gold-series-" + selectedSeries.id + ".csv",
    "\ufeff" + rows.join("\r\n"),
    "text/csv;charset=utf-8",
  );
}
async function showReport() {
  selectedReport = null;
  $("download-report").disabled = true;
  $("download-synthesis").disabled = true;
  clear($("synthesis-findings"));
  clear($("daily-readiness"));
  clear($("event-study-plan"));
  $("synthesis-note").textContent = "";
  const key = $("report-select").value;
  if (!key) {
    $("report-text").textContent = "بستهٔ پژوهش تأییدشده موجود نیست.";
    return;
  }
  try {
    const r = await get("/api/report?id=" + key);
    if ($("report-select").value !== key) return;
    selectedReport = r;
    $("download-synthesis").disabled = false;
    renderSynthesis();
    renderDailyReadiness();
    renderEventStudyPlan(r.event_study_plan);
    $("download-report").disabled = false;
    meta($("report-meta"), [
      "وضعیت: " + title(r.status),
      "برش اطلاعات: " + stamp(r.as_of),
      "ساخته‌شده: " + stamp(r.generated_at),
      "نسخه: " + r.software_version,
      r.computation
        ? "محاسبه: Python " +
          r.computation.python_version +
          " · " +
          r.computation.operating_system +
          " · " +
          stamp(r.computation.started_at) +
          " تا " +
          stamp(r.computation.finished_at)
        : "محیط محاسبهٔ خارجی یا تاریخی: ثبت نشده",
      r.runtime
        ? (r.computation
            ? "محیط محاسبه ثبت شده؛ محیط ساخت بسته: "
            : "محیط محاسبه ثبت نشده؛ محیط ساخت بسته: ") +
          r.runtime.python_implementation +
          " " +
          r.runtime.python_version +
          " · " +
          r.runtime.operating_system
        : "محیط تاریخی ساخت بسته: ثبت نشده",
      "هش: " + r.fingerprint.slice(0, 16) + "…",
    ]);
    clear($("report-sections"));
    r.report.sections.forEach((s) => {
      const card = el("div", null, "section-card");
      card.append(el("h3", title(s.key)), badge(s.status));
      $("report-sections").append(card);
    });
    renderMarkdown($("report-text"), r.text);
    clear($("report-relations"));
    const associations = (r.report.monthly?.associations || []).filter(
      (a) => a.population === "common",
    );
    if (associations.length) {
      $("report-relations").append(
        el("h2", "روابط توصیفی ماهانهٔ طلا و کلان"),
        el(
          "p",
          "ضریب Pearson بین تغییرات ماهانه، روی نمونهٔ مشترک؛ همبستگی پیش‌بینی یا علیت نیست. بازه و روش کامل در متن گزارش آمده است.",
          "muted",
        ),
      );
      const grid = el("div", null, "relation-bars");
      for (const a of associations) {
        const card = el("div", null, "relation");
        card.append(
          el("h3", title(a.series_id)),
          el(
            "span",
            "Pearson: " +
              fmt(a.pearson) +
              " · Spearman: " +
              fmt(a.spearman) +
              " · n=" +
              fmt(a.n),
            "muted",
          ),
        );
        const track = el("div", null, "relation-track");
        if (a.pearson != null) {
          const fill = el("div", null, "relation-fill");
          fill.style.left = (a.pearson < 0 ? 50 + a.pearson * 50 : 50) + "%";
          fill.style.width = Math.abs(a.pearson) * 50 + "%";
          track.append(fill);
        }
        card.append(
          el(
            "p",
            title(a.method) +
              " | " +
              (a.months[0] || "") +
              " .. " +
              (a.months.at(-1) || "") +
              " | " +
              title(a.status),
            "muted",
          ),
          track,
        );
        grid.append(card);
      }
      $("report-relations").append(grid);
    }
    const stability = r.monthly_stability;
    if (stability) {
      $("report-relations").append(el("h2", "ثبات روابط در دوره‌های جدا"));
      $("report-relations").append(
        el(
          "p",
          "بازه‌های تقویمی ثابت و بدون هم‌پوشانی، نمونهٔ مشترک و روش‌های قیمت جدا؛ دورهٔ آخر ناقص است. تغییر ضریب، آزمون پیش‌بینی یا علیت نیست. حداقل نمونه: " +
            fmt(stability.minimum_pairs) +
            " ماه.",
          "muted",
        ),
      );
      const node = el("div", null, "table-wrap");
      table(
        node,
        [
          "دوره",
          "روش قیمت",
          "متغیر",
          "ماه معتبر / حذف",
          "Pearson",
          "Spearman",
          "وضعیت",
        ],
        stability.rows.map((a) => [
          a.calendar_window,
          title(a.method),
          title(a.series_id),
          fmt(a.n) + " / " + fmt(a.excluded_months),
          fmt(a.pearson),
          fmt(a.spearman),
          title(a.status),
        ]),
      );
      $("report-relations").append(node);
      const audit = el("details");
      audit.append(el("summary", "ماه‌های کنارگذاشته‌شده و علت حذف"));
      audit.append(
        el(
          "p",
          "هر ماه یک‌بار شمرده می‌شود، حتی اگر چند متغیر ناقص باشد. علت از گزارش مبنا نقل می‌شود؛ دلیل ثبت‌نشده حدس زده نمی‌شود.",
          "muted",
        ),
      );
      const reasons = {
        methodology_break: "تغییر روش قیمت",
        current_missing: "مقدار ماه جاری مفقود",
        previous_missing: "مقدار ماه قبل مفقود",
        current_insufficient_daily_coverage: "پوشش روزانهٔ ماه جاری ناکافی",
        previous_insufficient_daily_coverage: "پوشش روزانهٔ ماه قبل ناکافی",
        reason_not_recorded: "علت در گزارش ثبت نشده",
      };
      const auditRows = (stability.sample_audit || []).flatMap((a) =>
        a.excluded.map((b) => [
          b.month.slice(0, 7),
          a.calendar_window,
          title(a.method),
          Object.entries(b.missing_series)
            .map(([s, why]) => title(s) + ": " + (reasons[why] || why))
            .join("؛ "),
        ]),
      );
      if (auditRows.length) {
        const auditTable = el("div", null, "table-wrap");
        table(
          auditTable,
          ["ماه", "دوره", "روش قیمت", "متغیر ناقص و علت"],
          auditRows,
        );
        audit.append(auditTable);
      } else
        audit.append(
          el(
            "p",
            "در دامنهٔ این دوره‌ها ماه ناقص کنارگذاشته‌شده‌ای وجود ندارد.",
          ),
        );
      $("report-relations").append(audit);
    }
    if (r.monthly_robustness) renderMonthlyRobustness(r.monthly_robustness);
    if (r.report?.monthly) renderMonthlyScatter(r.report);
  } catch (e) {
    error(e.message);
  }
}
function renderEventStudyPlan(plan) {
  const box = $("event-study-plan");
  clear(box);
  if (!plan) return;
  box.append(el("h2", "طرح پیشنهادی مطالعهٔ رویدادها"));
  box.append(
    el(
      "p",
      "طرح نسخه‌دار برای CPI و گزارش اشتغال؛ مطالعه اجرا نشده و پژوهش روزانه آماده نیست. این پیش‌نویس، ثبت پیشاپیش یا آزمون پیش‌بینی محسوب نمی‌شود.",
      "notice neutral",
    ),
  );
  const exportButton = el("button", "دریافت JSON طرح مطالعه", "secondary");
  exportButton.onclick = () =>
    download(
      "event-study-plan-" + plan.report_fingerprint.slice(0, 8) + ".json",
      JSON.stringify(plan, null, 2),
      "application/json",
    );
  box.append(exportButton);
  const detail = el("details");
  detail.append(el("summary", "تعریف پاسخ قیمت و قواعد مطالعه"));
  const definitions = el("div", null, "table-wrap");
  table(
    definitions,
    ["بخش", "قاعدهٔ پیشنهادی"],
    [
      [
        "پرسش",
        "توصیف تغییر قیمت طلا پیرامون رویداد؛ بدون ادعای اثر علّی یا غافلگیری بازار",
      ],
      [
        "زمان رویداد",
        "زمان دسترسی واقعی به اولین انتشار با UTC و شاهد؛ ساعت ثابت فرض نمی‌شود",
      ],
      [
        "پاسخ اصلی",
        "۱۰۰ × (اولین قیمت بسته‌شدن جلسه پس از رویداد ÷ آخرین بسته‌شدن پیش از رویداد − ۱)",
      ],
      ["پاسخ فرعی", "همان مبنا تا دومین بسته‌شدن تأییدشده پس از رویداد"],
      [
        "قیمت و تقویم",
        "یک جریان با روش/ابزار/واحد/مجوز روشن و تقویم تاریخی معتبر؛ بدون ادغام منابع",
      ],
      [
        "رویداد هم‌پوشان",
        "پنجرهٔ دارای رویداد دیگر از همین دو خانواده حذف و شناسه/علت ثبت می‌شود",
      ],
      [
        "نمونه",
        "حداقل " +
          fmt(plan.protocol.minimum_eligible_events_per_family) +
          " رویداد واجد شرایط برای هر خانواده؛ تضمین توان آماری نیست",
      ],
      [
        "تفکیک زمانی پیشنهادی",
        "توسعه: ۲۰۱۲–۲۰۱۸؛ ارزیابی جدا: ۲۰۱۹–۲۰۲۴. پس از توسعه قواعد تثبیت می‌شوند؛ نتیجه‌ای محاسبه نشده",
      ],
      [
        "خروجی توصیفی",
        "دفتر رویدادها/حذف‌ها، میانگین، میانه و چارک پاسخ؛ چارک فاصلهٔ اطمینان نیست",
      ],
      [
        "پیش‌بینی",
        "این طرح هدف/مدل پیش‌بینی تعیین نمی‌کند؛ به پروتکل جدا با ویژگی‌های قابل دسترس در زمان تصمیم نیاز دارد",
      ],
    ],
  );
  detail.append(definitions);
  detail.append(
    el(
      "p",
      "قیمت روزانه، واکنش درون‌روزی اعلان را جدا نمی‌کند. زمان جلسه، اولین انتشار و دریافت باید مستقل ثبت شوند. شناسهٔ نسخه: " +
        plan.protocol.version +
        " · هش طرح: " +
        plan.protocol_sha256,
      "muted",
    ),
  );
  box.append(detail);
  const steps = el("details");
  steps.append(el("summary", "ترتیب اجرای کار پس از رفع پیش‌نیازها"));
  const list = el("ol");
  for (const step of [
    "تأیید روش منبع، حقوق ذخیره و تقویم تاریخی جلسه‌ها",
    "بررسی آرشیو مقدار اولین انتشار و زمان دسترسی واقعی",
    "ساخت دفتر کاندیدها، پنجرهٔ قیمت، حذف‌ها و رویدادهای هم‌پوشان",
    "بازبینی نمونهٔ توسعه، تثبیت نسخهٔ طرح و ارزیابی جداگانه",
    "بازحساب مستقل زمان‌ها، پنجره‌ها و مقادیر پیش از انتشار نتیجهٔ توصیفی",
  ])
    list.append(el("li", step));
  steps.append(list);
  box.append(steps);
}
function renderMonthlyScatter(report) {
  const study = report.monthly,
    box = $("report-relations");
  box.append(el("h2", "کاوش ماه‌های نمونهٔ مشترک"));
  box.append(
    el(
      "p",
      "هر نقطه یک ماه با تغییر معتبر در هر پنج سری است. طلا درصد تغییر میانگین ماهانه است؛ نرخ‌های بهره تغییر به واحد درصد هستند. روش‌های قیمت جدا می‌مانند. انتخاب نقطه با کلیک یا انتخاب ماه، مقادیر و شناسه‌های شواهد را نشان می‌دهد؛ همبستگی علیت یا پیش‌بینی نیست.",
      "muted",
    ),
  );
  const controls = el("div", null, "controls");
  function selectControl(name, id, options) {
    const group = el("div"),
      label = el("label", name),
      select = el("select");
    select.id = id;
    label.htmlFor = id;
    for (const [value, text] of options) {
      const option = el("option", text);
      option.value = value;
      select.append(option);
    }
    group.append(label, select);
    controls.append(group);
    return select;
  }
  const driver = selectControl(
    "متغیر نمودار پراکندگی",
    "scatter-driver",
    ["DTWEXBGS", "DFII10", "DGS10", "CPIAUCSL"].map((s) => [s, title(s)]),
  );
  const method = selectControl(
    "روش قیمت نمودار پراکندگی",
    "scatter-method",
    ["london_afternoon_fixing_average", "spot_daily_average"].map((s) => [
      s,
      title(s),
    ]),
  );
  const month = selectControl("ماه برای بررسی شواهد", "scatter-month", []);
  box.append(controls);
  const info = el("p", null, "muted"),
    exportButton = el("button", "دریافت CSV نمونهٔ نمودار", "secondary"),
    plot = el("div"),
    detail = el("div"),
    ledger = el("details");
  detail.setAttribute("aria-live", "polite");
  ledger.append(el("summary", "جدول ماه‌های همین نمونه"));
  const ledgerTable = el("div", null, "table-wrap");
  ledger.append(ledgerTable);
  box.append(info, exportButton, plot, detail, ledger);
  let rows = [];
  const series = ["WB_GOLD_MONTHLY", "DTWEXBGS", "DFII10", "DGS10", "CPIAUCSL"];
  function inspect(selected) {
    clear(detail);
    if (!selected) return;
    plot.querySelectorAll("circle[data-month]").forEach((point) => {
      const active = point.dataset.month === selected.month;
      point.setAttribute("r", active ? 7 : 4);
      point.setAttribute("fill", active ? "#142c37" : "#ac7c25");
      point.setAttribute("opacity", active ? 1 : 0.7);
    });
    detail.append(el("h3", "شواهد ماه " + selected.month.slice(0, 7)));
    const previous = new Date(selected.month + "T00:00:00Z");
    previous.setUTCMonth(previous.getUTCMonth() - 1);
    const prior = previous.toISOString().slice(0, 10);
    const values = el("div", null, "table-wrap");
    table(
      values,
      ["متغیر", "تغییر ماهانه", "واحد تغییر", "شناسه‌های ورودی ماه جاری / قبل"],
      series.map((s) => {
        const current = study.levels.find(
          (a) => a.series_id === s && a.month === selected.month,
        );
        const before = study.levels.find(
          (a) => a.series_id === s && a.month === prior,
        );
        return [
          title(s),
          fmt(selected.values[s]),
          ["DFII10", "DGS10"].includes(s) ? "واحد درصد" : "درصد",
          fmt(current?.record_ids.length) +
            " / " +
            fmt(before?.record_ids.length),
        ];
      }),
    );
    detail.append(values);
    const evidence = el("details");
    evidence.append(el("summary", "شناسه‌های کامل شواهد این تغییرها"));
    evidence.append(
      el(
        "p",
        "شناسهٔ گزارش: " +
          report.fingerprint +
          " · شناسهٔ مطالعه: " +
          study.fingerprint,
        "muted",
      ),
    );
    const ids = el("pre");
    ids.style.whiteSpace = "pre-wrap";
    ids.style.overflowWrap = "anywhere";
    ids.dir = "ltr";
    ids.textContent = JSON.stringify(
      study.levels
        .filter(
          (a) =>
            series.includes(a.series_id) &&
            [selected.month, prior].includes(a.month),
        )
        .map((a) => ({
          series_id: a.series_id,
          month: a.month,
          status: a.status,
          record_ids: a.record_ids,
        })),
      null,
      2,
    );
    evidence.append(ids);
    detail.append(evidence);
  }
  function draw() {
    rows = study.changes.filter(
      (a) =>
        a.method === method.value &&
        series.every(
          (s) => a.values[s] != null && Number.isFinite(a.values[s]),
        ),
    );
    clear(plot);
    clear(month);
    clear(ledgerTable);
    for (const row of rows) {
      const option = el("option", row.month.slice(0, 7));
      option.value = row.month;
      month.append(option);
    }
    month.disabled = exportButton.disabled = !rows.length;
    const association = study.associations.find(
      (a) =>
        a.method === method.value &&
        a.series_id === driver.value &&
        a.population === "common",
    );
    info.textContent =
      "نمونهٔ مشترک: " +
      fmt(rows.length) +
      " ماه · Pearson: " +
      fmt(association?.pearson) +
      " · Spearman: " +
      fmt(association?.spearman) +
      " · حداقل گزارش ضریب: " +
      fmt(study.plan.minimum_pairs) +
      " ماه. CSV فقط همین روش و متغیر را، با دقت اصلی مقادیر، صادر می‌کند.";
    table(
      ledgerTable,
      ["ماه", "تغییر میانگین طلا، درصد", study.definitions[driver.value]],
      rows.map((a) => [
        a.month.slice(0, 7),
        fmt(a.values.WB_GOLD_MONTHLY),
        fmt(a.values[driver.value]),
      ]),
    );
    if (rows.length < study.plan.minimum_pairs) {
      plot.append(
        el(
          "p",
          "برای این روش نمونهٔ کافی نداریم؛ نمودار پراکندگی نمایش داده نمی‌شود. ماه‌های موجود در جدول و CSV حفظ شده‌اند.",
          "notice neutral",
        ),
      );
      inspect(rows[0]);
      return;
    }
    const w = 920,
      h = 390,
      pad = { l: 82, r: 24, t: 24, b: 60 };
    const xs = rows.map((a) => a.values[driver.value]),
      ys = rows.map((a) => a.values.WB_GOLD_MONTHLY);
    function bounds(values) {
      let low = Math.min(0, ...values),
        high = Math.max(0, ...values);
      const span = high - low || 1;
      return [low - span * 0.07, high + span * 0.07];
    }
    const [minX, maxX] = bounds(xs),
      [minY, maxY] = bounds(ys);
    const x = (v) => pad.l + ((v - minX) / (maxX - minX)) * (w - pad.l - pad.r),
      y = (v) => h - pad.b - ((v - minY) / (maxY - minY)) * (h - pad.t - pad.b);
    const svg = svgNode("svg", {
      viewBox: `0 0 ${w} ${h}`,
      role: "img",
      "aria-label":
        "نمودار پراکندگی تغییر میانگین طلا در برابر " +
        study.definitions[driver.value] +
        "؛ " +
        title(method.value) +
        "؛ " +
        rows.length +
        " ماه",
    });
    for (let i = 0; i < 5; i++) {
      const xx = minX + ((maxX - minX) * i) / 4,
        yy = minY + ((maxY - minY) * i) / 4;
      svg.append(
        svgNode("line", {
          x1: pad.l,
          x2: w - pad.r,
          y1: y(yy),
          y2: y(yy),
          stroke: "#e9eef1",
        }),
      );
      svg.append(
        svgNode(
          "text",
          {
            x: pad.l - 10,
            y: y(yy) + 4,
            "text-anchor": "end",
            fill: "#647680",
            "font-size": 12,
          },
          new Intl.NumberFormat("en", { maximumFractionDigits: 2 }).format(yy),
        ),
      );
      svg.append(
        svgNode(
          "text",
          {
            x: x(xx),
            y: h - pad.b + 24,
            "text-anchor": "middle",
            fill: "#647680",
            "font-size": 12,
          },
          new Intl.NumberFormat("en", { maximumFractionDigits: 2 }).format(xx),
        ),
      );
    }
    svg.append(
      svgNode("line", {
        x1: x(0),
        x2: x(0),
        y1: pad.t,
        y2: h - pad.b,
        stroke: "#83919a",
        "stroke-dasharray": "4 4",
      }),
      svgNode("line", {
        x1: pad.l,
        x2: w - pad.r,
        y1: y(0),
        y2: y(0),
        stroke: "#83919a",
        "stroke-dasharray": "4 4",
      }),
    );
    svg.append(
      svgNode(
        "text",
        { x: pad.l, y: 16, fill: "#506675", "font-size": 12 },
        "Gold monthly average change (%)",
      ),
    );
    const xUnit = ["DFII10", "DGS10"].includes(driver.value)
      ? "percentage points"
      : "percent";
    svg.append(
      svgNode(
        "text",
        {
          x: w / 2,
          y: h - 8,
          "text-anchor": "middle",
          fill: "#506675",
          "font-size": 12,
        },
        driver.value + " change (" + xUnit + ")",
      ),
    );
    for (const row of rows) {
      const point = svgNode("circle", {
        "data-month": row.month,
        cx: x(row.values[driver.value]),
        cy: y(row.values.WB_GOLD_MONTHLY),
        r: 4,
        fill: "#ac7c25",
        opacity: 0.7,
      });
      point.append(
        svgNode(
          "title",
          {},
          row.month.slice(0, 7) +
            " · " +
            driver.value +
            ": " +
            fmt(row.values[driver.value]) +
            " · Gold: " +
            fmt(row.values.WB_GOLD_MONTHLY),
        ),
      );
      point.addEventListener("click", () => {
        month.value = row.month;
        inspect(row);
      });
      svg.append(point);
    }
    const shell = el("div", null, "chart-shell");
    shell.append(svg);
    plot.append(shell);
    plot.append(
      el(
        "p",
        "محورها متناسب با همین نمونه‌اند و صفر را شامل می‌شوند؛ نقطه‌ها به هم وصل نشده‌اند. برای بررسی با صفحه‌کلید از انتخاب ماه و جدول استفاده کنید.",
        "chart-note",
      ),
    );
    inspect(rows[0]);
  }
  month.onchange = () => inspect(rows.find((a) => a.month === month.value));
  driver.onchange = method.onchange = draw;
  exportButton.onclick = () => {
    const header = [
      "report_fingerprint",
      "monthly_fingerprint",
      "as_of",
      "method",
      "month",
      "gold_change_percent",
      "driver",
      "driver_change",
      "driver_change_unit",
    ];
    const unit = ["DFII10", "DGS10"].includes(driver.value)
      ? "percentage_points"
      : "percent";
    const csv = [
      header,
      ...rows.map((a) => [
        report.fingerprint,
        study.fingerprint,
        report.as_of,
        a.method,
        a.month,
        a.values.WB_GOLD_MONTHLY,
        driver.value,
        a.values[driver.value],
        unit,
      ]),
    ]
      .map((a) =>
        a.map((v) => '"' + String(v).replaceAll('"', '""') + '"').join(","),
      )
      .join("\r\n");
    download(
      "monthly-sample-" + driver.value + "-" + method.value + ".csv",
      csv,
      "text/csv;charset=utf-8",
    );
  };
  draw();
}
function renderMonthlyRobustness(data) {
  const box = $("report-relations");
  box.append(el("h2", "استحکام تحلیل ماهانه"));
  box.append(
    el(
      "p",
      "داده‌های اصلاح‌شدهٔ موجود؛ تحلیل توصیفی، بدون آزمون پیش‌بینی. روش‌های قیمت جدا هستند.",
      "muted",
    ),
  );
  const exportButton = el(
    "button",
    "دریافت JSON استحکام و نمونه‌ها",
    "secondary",
  );
  exportButton.onclick = () =>
    download(
      "monthly-robustness-" + data.report_fingerprint.slice(0, 8) + ".json",
      JSON.stringify(data, null, 2),
      "application/json",
    );
  box.append(exportButton);
  const populations = el("details");
  populations.append(el("summary", "مقایسهٔ نمونهٔ مشترک و دوتایی"));
  populations.append(
    el(
      "p",
      "نمونهٔ دوتایی فقط طلا و همان متغیر را لازم دارد؛ نمونهٔ مشترک هر پنج سری را. اختلاف ضریب، اثر خالص حذف ماه یا رابطهٔ علّی نیست.",
      "muted",
    ),
  );
  const popTable = el("div", null, "table-wrap");
  table(
    popTable,
    [
      "روش",
      "متغیر",
      "n مشترک / دوتایی",
      "Pearson مشترک / دوتایی",
      "Spearman مشترک / دوتایی",
      "ماه‌های اضافهٔ دوتایی",
    ],
    data.sample_comparisons.map((a) => [
      title(a.method),
      title(a.series_id),
      fmt(a.common_n) + " / " + fmt(a.pairwise_n),
      fmt(a.common_pearson) + " / " + fmt(a.pairwise_pearson),
      fmt(a.common_spearman) + " / " + fmt(a.pairwise_spearman),
      a.additional_pairwise_months.map((m) => m.slice(0, 7)).join("، ") ||
        "ندارد",
    ]),
  );
  populations.append(popTable);
  box.append(populations);
  const influence = el("details");
  influence.append(el("summary", "حساسیت به کنارگذاشتن یک ماه"));
  influence.append(
    el(
      "p",
      "هر بار تنها یک ماه از نمونهٔ مشترک کنار گذاشته و ضریب دوباره محاسبه می‌شود؛ حداقل نمونه بعد از حذف نیز رعایت می‌شود. بازهٔ کمینه/بیشینه، فاصلهٔ اطمینان نیست. ماه با بیشترین تغییر، خطا یا علت بازار محسوب نمی‌شود.",
      "muted",
    ),
  );
  const infTable = el("div", null, "table-wrap");
  table(
    infTable,
    [
      "روش",
      "متغیر",
      "n مبنا",
      "Pearson مبنا",
      "کمینه / بیشینه پس از حذف",
      "بیشترین تغییر مطلق",
      "ماه مربوط",
      "حذف‌های تعریف‌نشده",
      "وضعیت",
    ],
    data.influence.map((a) => [
      title(a.method),
      title(a.series_id),
      fmt(a.n),
      fmt(a.baseline_pearson),
      fmt(a.pearson_min) + " / " + fmt(a.pearson_max),
      fmt(a.largest_absolute_change),
      a.largest_change_month?.slice(0, 7) || "ناموجود",
      fmt(a.undefined_removals),
      title(a.status),
    ]),
  );
  influence.append(infTable);
  box.append(influence);
  box.append(el("h3", "روند ضرایب در پنجره‌های متحرک"));
  box.append(
    el(
      "p",
      "پنجرهٔ کامل " +
        fmt(data.rolling_months) +
        "ماهه و نمونهٔ مشترک؛ محور ثابت −۱ تا +۱. تاریخ نمودار، پایان پنجره است. پنجره‌های ناقص یا عبورکننده از تغییر روش خالی می‌مانند. پنجره‌های هم‌پوشان مستقل نیستند.",
      "muted",
    ),
  );
  const controls = el("div", null, "controls");
  const driverLabel = el("label", "متغیر نمودار"),
    driver = el("select");
  driver.id = "robustness-driver";
  driverLabel.htmlFor = driver.id;
  for (const s of ["DTWEXBGS", "DFII10", "DGS10", "CPIAUCSL"]) {
    const o = el("option", title(s));
    o.value = s;
    driver.append(o);
  }
  const metricLabel = el("label", "نوع ضریب"),
    metric = el("select");
  metric.id = "robustness-metric";
  metricLabel.htmlFor = metric.id;
  for (const s of ["pearson", "spearman"]) {
    const o = el("option", s === "pearson" ? "Pearson" : "Spearman");
    o.value = s;
    metric.append(o);
  }
  const driverGroup = el("div"),
    metricGroup = el("div");
  driverGroup.append(driverLabel, driver);
  metricGroup.append(metricLabel, metric);
  controls.append(driverGroup, metricGroup);
  box.append(controls);
  const plots = el("div");
  box.append(plots);
  function draw() {
    clear(plots);
    for (const method of [
      "london_afternoon_fixing_average",
      "spot_daily_average",
    ]) {
      const selected = data.rolling.filter(
        (a) => a.series_id === driver.value && a.method === method,
      );
      plots.append(el("h4", title(method)));
      const points = selected.map((a) => ({
        value: a[metric.value],
        observed_at: a.last_month + "T00:00:00Z",
        date: a.first_month.slice(0, 7) + " تا " + a.last_month.slice(0, 7),
      }));
      const graph = el("div");
      plots.append(graph);
      chart(
        graph,
        points,
        {
          kind: "monthly_association",
          series: driver.value,
          source: "monthly_research",
          unit: metric.value,
        },
        true,
        null,
        [-1, 1],
      );
    }
    const all = data.rolling.filter((a) => a.series_id === driver.value);
    const ledger = el("details");
    ledger.append(el("summary", "جدول تمام پنجره‌ها و موارد ناموجود"));
    const ledgerTable = el("div", null, "table-wrap");
    const why = {
      methodology_break: "عبور از تغییر روش",
      noncontiguous: "ماه‌های ناپیوسته",
      missing_common_changes: "تغییر ماهانهٔ ناقص در نمونهٔ مشترک",
    };
    table(
      ledgerTable,
      ["آغاز", "پایان", "روش", "Pearson", "Spearman", "وضعیت / علت"],
      all.map((a) => [
        a.first_month.slice(0, 7),
        a.last_month.slice(0, 7),
        title(a.method),
        fmt(a.pearson),
        fmt(a.spearman),
        a.reasons.map((s) => why[s] || s).join("؛ ") || title(a.status),
      ]),
    );
    ledger.append(ledgerTable);
    plots.append(ledger);
  }
  driver.onchange = metric.onchange = draw;
  draw();
}
function renderDailyReadiness() {
  const box = $("daily-readiness");
  clear(box);
  const readiness = selectedReport?.daily_readiness;
  if (!readiness) return;
  box.append(
    el(
      "p",
      "پژوهش روزانه آماده نیست؛ رفع هشدار به‌تنهایی مجوز بک‌تست نمی‌دهد.",
      "notice neutral",
    ),
  );
  for (const check of readiness.requirements) {
    const item = el("details", null, "synthesis-finding");
    item.append(
      el(
        "summary",
        check.title +
          " — " +
          (check.status === "needs_evidence"
            ? "شاهد لازم است"
            : "تأیید نشده است"),
      ),
    );
    item.append(el("p", "مدرک لازم: " + check.required_evidence));
    item.append(el("p", check.limitation));
    item.append(
      el("p", "شاهد در JSON گزارش: " + check.pointers.join("، "), "muted"),
    );
    item.append(el("pre", JSON.stringify(check.facts, null, 2)));
    box.append(item);
  }
}

function synthesisFindings(synthesis, filter) {
  const conflicts = ["vintage_disagreement", "method_disagreement"];
  const agreements = ["matches_display", "method_concordance"];
  return synthesis.findings.filter(
    (f) =>
      filter === "all" ||
      (filter === "conflicts" && conflicts.includes(f.outcome)) ||
      (filter === "revisions" && f.outcome === "revision_difference") ||
      (filter === "agreements" && agreements.includes(f.outcome)) ||
      (filter === "limits" &&
        ![...conflicts, ...agreements, "revision_difference"].includes(
          f.outcome,
        )),
  );
}
function renderSynthesis() {
  clear($("synthesis-findings"));
  const synthesis = selectedReport?.synthesis;
  if (!synthesis) return;
  const outcomes = {
    matches_display: "سازگار در دقت نمایش",
    vintage_disagreement: "اختلاف با نسخهٔ هم‌تاریخ",
    revision_difference: "اختلاف با نسخهٔ اصلاح‌شدهٔ جاری",
    rounding_boundary: "مرز گردکردن؛ نامعین",
    missing_period: "دورهٔ قابل مقایسه موجود نیست",
    missing_value: "مقدار قابل مقایسه موجود نیست",
    method_concordance: "جهت دو ضریب سازگار است",
    method_disagreement: "جهت دو روش متفاوت است",
    insufficient_sample: "شاهد آماری کافی نیست",
    not_comparable: "تعریف یا دوره متفاوت؛ ادغام نمی‌شود",
    coverage_limited: "پژوهش روزانه نیازمند شاهد بیشتر است",
    no_evidence: "شاهد موجود نیست",
  };
  const filter = $("synthesis-filter").value;
  const findings = synthesisFindings(synthesis, filter);
  const counts = synthesis.outcome_counts;
  $("synthesis-note").textContent =
    "بازحساب از همین گزارش با قواعد نسخهٔ " +
    synthesis.rule_version +
    " · اختلاف نیازمند بررسی: " +
    fmt(
      (counts.vintage_disagreement || 0) + (counts.method_disagreement || 0),
    ) +
    " · اختلاف اصلاحیهٔ جاری: " +
    fmt(counts.revision_difference || 0) +
    " · یافته‌های این نما: " +
    fmt(findings.length) +
    " · تعداد یافته، شمار منابع مستقل یا احتمال اطمینان نیست؛ جهت بازار استنتاج نشده است.";
  if (!findings.length) {
    $("synthesis-findings").append(
      el(
        "p",
        "در این گزارش برای این فیلتر یافته‌ای ثبت نشده است؛ نبود اختلاف، تأیید همهٔ داده‌ها نیست.",
      ),
    );
  }
  for (const finding of findings) {
    const item = el("details", null, "synthesis-finding");
    const f = finding.facts;
    const identity =
      finding.category === "release"
        ? (f.metric === "cpi_all_items_sa_mom"
            ? "تورم ماهانهٔ CPI"
            : "نرخ بیکاری") +
          " · " +
          f.period +
          " · سند " +
          f.announced_at.slice(0, 10) +
          " · " +
          (f.period_role === "headline" ? "دورهٔ اصلی" : "دورهٔ قبلی") +
          " · " +
          (f.comparison === "release_date_vintage"
            ? "نسخهٔ هم‌تاریخ"
            : "نسخهٔ جاری")
        : finding.category === "monthly"
          ? title(f.series_id) + " · " + title(f.method) + " · n=" + fmt(f.n)
          : finding.id === "comparability:gold"
            ? "قیمت مرجع روزانه و میانگین ماهانه"
            : finding.id === "comparability:periods"
              ? "دوره‌های مرجع کلان و COT"
              : "دروازهٔ پژوهش روزانه";
    item.append(el("summary", identity + " — " + outcomes[finding.outcome]));
    item.append(
      el(
        "p",
        "منابع: " + (finding.sources.map(title).join("، ") || "دروازهٔ گزارش"),
      ),
    );
    item.append(el("p", finding.limitation));
    if (finding.category === "release") {
      item.append(
        el(
          "p",
          "مقدار سند: " +
            fmt(f.document_value) +
            " · FRED (≈): " +
            fmt(f.compared_value) +
            " · واحد: " +
            title(f.unit) +
            " · اختلاف با سند (≈): " +
            fmt(f.difference),
        ),
      );
    } else if (finding.category === "monthly") {
      item.append(
        el(
          "p",
          "Pearson (≈): " +
            fmt(f.pearson) +
            " · Spearman (≈): " +
            fmt(f.spearman) +
            " · ماه‌های نمونه: " +
            (f.months[0] || "ناموجود") +
            " تا " +
            (f.months[f.months.length - 1] || "ناموجود"),
        ),
      );
    } else if (finding.id === "comparability:periods") {
      item.append(el("p", "دورهٔ COT: " + (f.cot_reference || "ناموجود")));
      for (const reference of f.macro_references)
        item.append(
          el(
            "p",
            title(reference.series_id) +
              ": " +
              (reference.reference_at?.slice(0, 10) || "ناموجود") +
              " · " +
              title(reference.status),
          ),
        );
    }
    if (f.source_url) {
      const sourceUrl = new URL(f.source_url);
      if (
        sourceUrl.protocol === "https:" &&
        sourceUrl.hostname === "www.bls.gov" &&
        sourceUrl.pathname.startsWith("/news.release/archives/")
      ) {
        const sourceLink = el("a", "مشاهدهٔ سند BLS");
        sourceLink.href = sourceUrl.href;
        sourceLink.target = "_blank";
        sourceLink.rel = "noopener noreferrer";
        item.append(sourceLink);
      }
    }
    item.append(
      el("p", "شاهد در JSON گزارش: " + finding.pointers.join("، "), "muted"),
    );
    item.append(el("pre", JSON.stringify(finding.facts, null, 2)));
    $("synthesis-findings").append(item);
  }
}
function operations() {
  const states = data.run_states;
  $("operations-cards").append(
    kpi(
      "دریافت‌های ثبت‌شده",
      fmt(data.runs.length),
      "تعداد دریافت؛ تعداد درخواست HTTP نیست",
    ),
    kpi(
      "دریافت موفق",
      fmt(states.succeeded || 0),
      "همهٔ سابقه؛ تضمین تازگی نیست",
    ),
    kpi(
      "دریافت ناموفق",
      fmt(states.failed || 0),
      "خطاهای گذشته نیز در شمارش هستند",
    ),
    kpi("دریافت ناتمام", fmt(states.running || 0), "نیازمند بررسی شواهد"),
  );
  $("health-alert").textContent =
    "وضعیت: " +
    title(data.health.status) +
    " · سهمیهٔ منابع اندازه‌گیری نشده است. " +
    (data.health.refresh_status
      ? "گردش متصل: " +
        title(data.health.refresh_status) +
        "؛ انتقال مسیر تاریخی صریح ثبت شده."
      : "علت دقیق HTTP فقط با گردش دریافتِ تطبیق‌یافته نمایش داده می‌شود.");
  $("runtime-note").textContent =
    "runtime نمای سلامت: Python " +
    (data.health.python_version || "نامعلوم") +
    " · runtime تاریخی دریافت‌ها ثبت نشده؛ audit کامل خام در این پنل اجرا نمی‌شود.";
  renderRuns();
}
function renderRuns() {
  const health = new Map((data.health.runs || []).map((r) => [r.run_id, r]));
  const filter = $("run-filter").value;
  table(
    $("run-table"),
    [
      "عملیات",
      "وضعیت",
      "آخرین جریان",
      "شکست متوالی",
      "شروع UTC",
      "رکورد درج‌شده",
      "خطای امن",
      "تلاش HTTP ثبت‌شده",
      "اقدام",
      "شناسهٔ اجرا",
    ],
    data.runs
      .filter((r) => filter === "all" || r.status === filter)
      .map((r) => {
        const h = health.get(r.id);
        return [
          r.operation,
          badge(r.status),
          h ? (h.is_latest ? "بله" : "خیر") : "نامعلوم",
          h ? fmt(h.consecutive_failures) : "نامعلوم",
          stamp(r.started_at),
          fmt(r.inserted),
          h?.failure_reason ||
            (r.status === "failed" ? "علت دقیق ثبت نشده" : "—"),
          r.transport
            ? r.transport.attempts
                .map(
                  (a) =>
                    title(a.outcome) +
                    (a.status_code ? " " + a.status_code : ""),
                )
                .join("؛ ") || "۰؛ فقط مسیر fetch_bytes ثبت می‌شود"
            : "سابقه ثبت نشده",
          h ? title(h.retry_action) : "—",
          r.id,
        ];
      }),
  );
}
function roadmap() {
  $("roadmap-notice").textContent =
    "اکنون فاز " +
    data.roadmap.current_phase +
    " · " +
    data.roadmap.next_step +
    " — تکمیل یک تحویل به معنی تکمیل همهٔ فاز نیست.";
  for (const p of data.roadmap.phases) {
    const card = el(
        "article",
        null,
        "phase" + (p.id === data.roadmap.current_phase ? " current" : ""),
      ),
      head = el("div", null, "phase-head"),
      label = el("h2");
    label.append(
      el("span", p.id, "phase-number"),
      document.createTextNode(p.title),
    );
    head.append(label, badge(p.status));
    card.append(head, el("p", "معیار پایان: " + p.criterion, "criterion"));
    const body = el("div", null, "phase-body");
    for (const [label, items] of [
      ["تحویل‌شده", p.delivered],
      ["باقی‌مانده / پیش‌نیاز", p.remaining],
    ]) {
      const part = el("div");
      part.append(el("h3", label));
      const list = el("ul");
      if (!items.length)
        list.append(
          el(
            "li",
            label === "تحویل‌شده"
              ? "هنوز تحویلی ندارد"
              : "در دامنهٔ این فاز مورد باز ندارد",
          ),
        );
      else items.forEach((text) => list.append(el("li", text)));
      part.append(list);
      body.append(part);
    }
    card.append(body, el("small", "نسخه‌ها: " + p.releases, "muted"));
    for (const d of p.deliveries || []) {
      const n = el(
        "span",
        d.version + " · " + d.title + " · " + title(d.status),
        "delivery",
      );
      card.append(n);
    }
    $("phase-list").append(card);
  }
}
async function start() {
  try {
    data = await get("/api/summary");
    data.sources.forEach((source) => {
      const option = el("option", title(source.id));
      option.value = source.id;
      $("source-filter").append(option);
    });
    $("version").textContent = "نسخهٔ " + data.version;
    $("snapshot-time").textContent = "snapshot: " + stamp(data.generated_at);
    overview();
    operations();
    roadmap();
    setupComparisons();
    fillSeries(
      data.series.find(
        (s) => s.identity.kind === "price_close" && !s.identity.synthetic,
      )?.id,
    );
    data.reports.forEach((r) => {
      const o = el(
        "option",
        day(r.as_of) +
          " · " +
          r.software_version +
          " · " +
          title(r.status) +
          " · " +
          r.fingerprint.slice(0, 8),
      );
      o.value = r.id;
      $("report-select").append(o);
    });
    showReport();
    $("loading").hidden = true;
    navigate(location.hash.slice(1) || "overview");
  } catch (e) {
    $("loading").hidden = true;
    error(e.message);
  }
}
document
  .querySelectorAll("nav button")
  .forEach((n) => (n.onclick = () => navigate(n.dataset.view)));
document
  .querySelectorAll("[data-jump]")
  .forEach((n) => (n.onclick = () => navigate(n.dataset.jump)));
$("kind-filter").onchange = () => fillSeries();
$("series-select").onchange = setSeriesRange;
$("source-filter").onchange = () => fillSeries();
$("apply-range").onclick = showSeries;
$("all-range").onclick = () => {
  const s = data.series.find((s) => s.id === $("series-select").value);
  if (s) {
    $("date-start").value = s.start;
    $("date-end").value = s.end;
    showSeries();
  }
};
$("export-series").onclick = exportSeries;
$("report-select").onchange = showReport;
$("synthesis-filter").onchange = renderSynthesis;
$("download-synthesis").onclick = () => {
  if (selectedReport?.synthesis) {
    const synthesis = selectedReport.synthesis;
    const filter = $("synthesis-filter").value;
    const view = {
      export_type: "filtered_synthesis_view",
      rule_version: synthesis.rule_version,
      as_of: synthesis.as_of,
      source_report_fingerprint: synthesis.report_fingerprint,
      synthesis_fingerprint: synthesis.fingerprint,
      input_sha256: synthesis.input_sha256,
      filter,
      total_findings: synthesis.findings.length,
      findings: synthesisFindings(synthesis, filter),
    };
    download(
      "gold-synthesis-" + selectedReport.id + "-" + filter + ".json",
      JSON.stringify(view, null, 2),
      "application/json",
    );
  }
};
$("download-report").onclick = () => {
  if (selectedReport)
    download(
      "gold-report-" + selectedReport.id + ".json",
      JSON.stringify(selectedReport.report, null, 2),
      "application/json",
    );
};
$("run-filter").onchange = renderRuns;
start();
