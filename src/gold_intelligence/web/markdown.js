// Restricted presentation of verified local Markdown: text and tables only, no HTML execution.
function cleanMarkdown(text) {
  return text
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/\*\*/g, "")
    .replace(/`/g, "");
}
function renderMarkdown(node, text) {
  clear(node);
  const lines = text.split("\n");
  let index = 0;
  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) {
      index++;
      continue;
    }
    if (
      line.startsWith("|") &&
      index + 1 < lines.length &&
      /^\|[\s:|\-]+\|$/.test(lines[index + 1].trim())
    ) {
      const headers = line
        .split("|")
        .slice(1, -1)
        .map((v) => cleanMarkdown(v.trim()));
      index += 2;
      const rows = [];
      while (index < lines.length && lines[index].trim().startsWith("|")) {
        rows.push(
          lines[index]
            .trim()
            .split("|")
            .slice(1, -1)
            .map((v) => cleanMarkdown(v.trim())),
        );
        index++;
      }
      const wrap = el("div", null, "table-wrap");
      table(wrap, headers, rows);
      node.append(wrap);
      continue;
    }
    if (/^#{1,6} /.test(line)) {
      node.append(
        el(
          "h" + Math.min(4, Math.max(2, line.match(/^#+/)[0].length)),
          cleanMarkdown(line.replace(/^#+ /, "")),
        ),
      );
      index++;
      continue;
    }
    if (line.startsWith("- ")) {
      const list = el("ul");
      while (index < lines.length && lines[index].trim().startsWith("- ")) {
        list.append(el("li", cleanMarkdown(lines[index].trim().slice(2))));
        index++;
      }
      node.append(list);
      continue;
    }
    node.append(el("p", cleanMarkdown(line)));
    index++;
  }
}
function setupComparisons() {
  const box = el("article", null, "panel"),
    controls = el("div", null, "controls"),
    label = el("label", "مقایسهٔ ذخیره‌شده و تأییدشده", "wide"),
    select = el("select");
  select.id = "comparison-select";
  label.append(select);
  controls.append(label);
  box.append(el("h2", "تغییرات بین گزارش‌ها"), controls);
  const metadata = el("div", null, "metadata"),
    body = el("div", null, "report-text");
  box.append(metadata, body);
  $("reports").append(box);
  for (const c of data.comparisons) {
    const option = el(
      "option",
      day(c.before) +
        " ← " +
        day(c.after) +
        " · " +
        title(c.status) +
        " · " +
        fmt(c.changes) +
        " مورد",
    );
    option.value = c.id;
    select.append(option);
  }
  async function show() {
    if (!select.value) {
      body.textContent = "مقایسهٔ تأییدشده موجود نیست.";
      return;
    }
    const key = select.value;
    try {
      const c = await get("/api/comparison?id=" + key);
      if (select.value !== key) return;
      meta(metadata, [
        "وضعیت: " + title(c.status),
        "برش قبل: " + stamp(c.before),
        "برش بعد: " + stamp(c.after),
        "تغییر موجودیت‌ها: " + fmt(c.changes),
      ]);
      renderMarkdown(body, c.text);
    } catch (e) {
      error(e.message);
    }
  }
  select.onchange = show;
  show();
}
