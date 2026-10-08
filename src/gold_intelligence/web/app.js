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
  estimated: "ضریب قابل گزارش",
  too_short: "کمتر از حداقل نمونه",
  currency_per_troy_ounce: "دلار/اونس تروا",
  percent: "درصد",
  contracts: "قرارداد",
  percent_sa: "درصد؛ تعدیل فصلی",
  percent_change_mom_sa: "تغییر ماهانهٔ درصدی؛ تعدیل فصلی",
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
  cftc_disaggregated: "موقعیت معامله‌گران · CFTC",
  DFF: "نرخ وجوه فدرال",
  DGS10: "بازده اوراق ده‌ساله",
  DFII10: "بازده واقعی ده‌ساله",
  DTWEXBGS: "شاخص گستردهٔ دلار",
  CPIAUCSL: "شاخص قیمت مصرف‌کننده",
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
function chart(container, points, identity, compact = false, inspect = null) {
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
      `${fmt(points.length)} مشاهده · ${fmt(points.filter((p) => p.value == null).length)} مقدار ناموجود · ${unitLabel(identity)} · محور عمودی متناسب با بازه؛ null و شکاف‌های بزرگ به هم وصل نمی‌شوند.`,
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
  const key = $("report-select").value;
  if (!key) {
    $("report-text").textContent = "بستهٔ پژوهش تأییدشده موجود نیست.";
    return;
  }
  try {
    const r = await get("/api/report?id=" + key);
    if ($("report-select").value !== key) return;
    selectedReport = r;
    $("download-report").disabled = false;
    meta($("report-meta"), [
      "وضعیت: " + title(r.status),
      "برش اطلاعات: " + stamp(r.as_of),
      "ساخته‌شده: " + stamp(r.generated_at),
      "نسخه: " + r.software_version,
      r.runtime
        ? "محیط ساخت بسته: " +
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
  } catch (e) {
    error(e.message);
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
