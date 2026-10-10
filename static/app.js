"use strict";

const Kind = Object.freeze({ SKILL: "skill", PLUGIN: "plugin", MCP: "mcp" });
const Value = Object.freeze({
  ON: "on",
  NAME_ONLY: "name-only",
  USER_INVOCABLE_ONLY: "user-invocable-only",
  OFF: "off",
});
const Source = Object.freeze({
  GLOBAL: "global",
  OVERRIDE: "override",
  SETTINGS_JSON: "settings_json",
  PROJECT_FILE: "project_file",
});
const Panel = Object.freeze({ GLOBAL: "global", PROJECT: "project" });
const Sort = Object.freeze({ ALPHA: "alpha", STATUS: "status", OVERRIDE: "override" });

const KIND_LABELS = { [Kind.SKILL]: "Скиллы", [Kind.PLUGIN]: "Плагины", [Kind.MCP]: "MCP" };
const POOL_KEYS = { [Kind.SKILL]: "skills", [Kind.PLUGIN]: "plugins", [Kind.MCP]: "mcp" };
const KIND_SINGULAR = { [Kind.SKILL]: "Скилл", [Kind.PLUGIN]: "Плагин", [Kind.MCP]: "MCP" };
const OVERRIDE_WORD_FORMS = ["переопределение", "переопределения", "переопределений"];
const SOURCE_HINTS = {
  [Source.SETTINGS_JSON]: "задано в .claude/settings.json проекта",
  [Source.PROJECT_FILE]: "определено в самом проекте",
};
const SORT_LABELS = { [Sort.ALPHA]: "А→Я", [Sort.STATUS]: "Статус", [Sort.OVERRIDE]: "Переопр." };
const SORT_TITLES = {
  [Sort.ALPHA]: "По алфавиту",
  [Sort.STATUS]: "По включённости: on → name-only → user-invocable-only → off",
  [Sort.OVERRIDE]: "Сначала переопределённые в проекте",
};
const PANEL_SORTS = {
  [Panel.GLOBAL]: [Sort.ALPHA, Sort.STATUS],
  [Panel.PROJECT]: [Sort.ALPHA, Sort.STATUS, Sort.OVERRIDE],
};
const VALUE_RANKS = { [Value.ON]: 0, [Value.NAME_ONLY]: 1, [Value.USER_INVOCABLE_ONLY]: 2, [Value.OFF]: 3 };
const SORT_RANKS = {
  [Sort.ALPHA]: () => 0,
  [Sort.STATUS]: (item) => VALUE_RANKS[item.value],
  [Sort.OVERRIDE]: (item) => Number(item.source !== Source.OVERRIDE),
};

const SKILL_WORD_FORMS = ["скилл", "скилла", "скиллов"];
const COPY_TITLE = "Скопировать путь";
const ICON_ATTRS = 'viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
const COPY_ICON = `<svg ${ICON_ATTRS}><rect x="9" y="9" width="12" height="12" rx="2"></rect><path d="M5 15V5a2 2 0 0 1 2-2h10"></path></svg>`;
const CHECK_ICON = `<svg ${ICON_ATTRS}><path d="M5 12.5l4.5 4.5L19 7"></path></svg>`;
const PENCIL_ICON = `<svg ${ICON_ATTRS}><path d="M4 20h4L19 9l-4-4L4 16v4z"></path><path d="M13.5 6.5l4 4"></path></svg>`;
const TRASH_ICON = `<svg ${ICON_ATTRS}><path d="M4 7h16"></path><path d="M10 11v6M14 11v6"></path><path d="M6 7l1 13h10l1-13"></path><path d="M9 7V4h6v3"></path></svg>`;

const ROW_CONTROLS_SELECTOR ="input, select, button:not(.row-name)";
const LOCKED_TITLE = "Заблокировано автором (disable-model-invocation): вызывается только вручную через /имя";
const RESET_TITLE = "Значение переопределено в проекте. Нажмите, чтобы сбросить и наследовать глобальное";

const state = {
  pool: null,
  project: null,
  projectPath: "",
  tabs: { [Panel.GLOBAL]: Kind.SKILL, [Panel.PROJECT]: Kind.SKILL },
  filters: { [Panel.GLOBAL]: "", [Panel.PROJECT]: "" },
  sorts: { [Panel.GLOBAL]: Sort.ALPHA, [Panel.PROJECT]: Sort.ALPHA },
  selecting: { [Panel.GLOBAL]: false, [Panel.PROJECT]: false },
  selected: { [Panel.GLOBAL]: new Set(), [Panel.PROJECT]: new Set() },
  presets: [],
  draft: null,
};

const els = {
  serverError: document.getElementById("server-error"),
  currentName: document.getElementById("current-project-name"),
  chooseButton: document.getElementById("choose-project"),
  shutdownButton: document.getElementById("shutdown"),
  openPresetsButton: document.getElementById("open-presets"),
  picker: document.getElementById("picker"),
  projectForm: document.getElementById("project-form"),
  pathInput: document.getElementById("project-path"),
  pickerError: document.getElementById("picker-error"),
  recentList: document.getElementById("recent-list"),
  presetsDialog: document.getElementById("presets"),
  presetCreate: document.getElementById("preset-create"),
  presetEditTitle: document.getElementById("preset-edit-title"),
  presetsError: document.getElementById("presets-error"),
  presetList: document.getElementById("preset-list"),
  presetEditDialog: document.getElementById("preset-edit"),
  presetEditForm: document.getElementById("preset-edit-form"),
  presetEditName: document.getElementById("preset-edit-name"),
  presetEditOverrides: document.getElementById("preset-edit-overrides"),
  presetEditError: document.getElementById("preset-edit-error"),
  presetEditCancel: document.getElementById("preset-edit-cancel"),
  dialog: document.getElementById("detail"),
  dialogBody: document.querySelector("#detail .detail-body"),
  panels: {
    [Panel.GLOBAL]: panelElements("global-panel"),
    [Panel.PROJECT]: panelElements("project-panel"),
  },
};

function panelElements(id) {
  const root = document.getElementById(id);
  return {
    root,
    selectToggle: root.querySelector(".select-toggle"),
    filter: root.querySelector(".filter"),
    sort: root.querySelector(".segmented"),
    tabs: root.querySelector(".tabs"),
    bulk: root.querySelector(".bulk"),
    error: root.querySelector(".error"),
    notice: root.querySelector(".notice"),
    list: root.querySelector(".list"),
  };
}

const PANEL_VIEWS = {
  [Panel.GLOBAL]: {
    isLoaded: () => state.pool !== null,
    notLoadedText: "Загрузка…",
    emptyText: "Ничего не найдено",
    secondary: (item) => item.description,
    cells: (item) => [valueSelect(item, (value) => setValue(Panel.GLOBAL, item, value))],
  },
  [Panel.PROJECT]: {
    isLoaded: () => state.project !== null,
    notLoadedText: "Нажмите «Выбрать проект» в хедере.",
    emptyText: "Ничего нет",
    secondary: (item) => SOURCE_HINTS[item.source] || "",
    cells: (item) => [valueSelect(item, (value) => setValue(Panel.PROJECT, item, value)), resetCell(item)],
  },
};

class ApiError extends Error {}
class ServerUnavailableError extends ApiError {}

async function api(method, url, body) {
  const options = { method, headers: { "X-Claude-Tools-Config": "1" } };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    els.serverError.hidden = false;
    throw new ServerUnavailableError("Сервер недоступен.");
  }
  els.serverError.hidden = true;
  if (response.status === 204) {
    return null;
  }
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    let message = `Ошибка ${response.status}`;
    if (payload && payload.message) {
      message = payload.message;
    }
    throw new ApiError(message);
  }
  return payload;
}

function projectQuery(path = state.projectPath) {
  return `?path=${encodeURIComponent(path)}`;
}

function panelUrl(panelName, path) {
  const url = `/api/${panelName}/${path}`;
  if (panelName === Panel.GLOBAL) {
    return url;
  }
  return url + projectQuery();
}

function setMessage(box, message) {
  box.textContent = message;
  box.hidden = !message;
}

async function busy(container, messageBox, task) {
  const progress = container.querySelector(":scope > .progress");
  container.inert = true;
  container.setAttribute("aria-busy", "true");
  if (progress) {
    progress.hidden = false;
  }
  setMessage(messageBox, "");
  try {
    await task();
    return true;
  } catch (error) {
    const bannerShowsIt = error instanceof ServerUnavailableError && container.tagName !== "DIALOG";
    if (!bannerShowsIt) {
      setMessage(messageBox, error.message);
    }
    return false;
  } finally {
    container.inert = false;
    container.removeAttribute("aria-busy");
    if (progress) {
      progress.hidden = true;
    }
  }
}

async function withPanel(panelName, task) {
  const panel = els.panels[panelName];
  setMessage(panel.notice, "");
  if (!(await busy(panel.root, panel.error, task))) {
    render();
  }
}

async function loadPool() {
  state.pool = await api("GET", "/api/global");
}

async function loadProject(path = state.projectPath) {
  if (!path) {
    state.project = null;
    return;
  }
  state.project = await api("GET", `/api/project${projectQuery(path)}`);
  state.projectPath = state.project.path;
}

async function reloadAfterChange(panelName, items) {
  const tasks = [loadProject()];
  if (panelName === Panel.GLOBAL || items.some((item) => item.kind === Kind.MCP)) {
    tasks.push(loadPool());
  }
  await Promise.all(tasks);
  render();
}

async function setValue(panelName, item, value) {
  await withPanel(panelName, async () => {
    await api("PUT", panelUrl(panelName, `${item.kind}/${encodeURIComponent(item.id)}`), { value });
    await reloadAfterChange(panelName, [item]);
  });
}

async function runBatch(panelName, items, value) {
  await withPanel(panelName, async () => {
    const result = await api("PUT", panelUrl(panelName, "batch"), { items: toRefs(items), value });
    await reloadAfterChange(panelName, items);
    showBatchErrors(panelName, result);
  });
}

function showBatchErrors(panelName, result) {
  if (result.errors.length === 0) {
    return;
  }
  const details = result.errors.map((error) => `${error.id}: ${error.message}`).join("; ");
  setMessage(els.panels[panelName].error, `Изменено: ${result.applied}. Не удалось: ${result.errors.length} — ${details}`);
}

function itemKey(item) {
  return `${item.kind}:${item.id}`;
}

function toRefs(items) {
  return items.map((item) => ({ kind: item.kind, id: item.id }));
}

function isEnabled(item) {
  return item.value !== Value.OFF;
}

function allItems(panelName) {
  if (panelName === Panel.GLOBAL) {
    if (!state.pool) {
      return [];
    }
    return Object.values(POOL_KEYS).flatMap((key) => state.pool[key]);
  }
  if (!state.project) {
    return [];
  }
  return state.project.items;
}

function filteredItems(panelName, kind) {
  const text = state.filters[panelName].toLowerCase();
  return allItems(panelName).filter((item) => item.kind === kind && item.id.toLowerCase().includes(text));
}

function visibleItems(panelName) {
  const rank = SORT_RANKS[state.sorts[panelName]];
  return filteredItems(panelName, state.tabs[panelName]).sort((a, b) => rank(a) - rank(b) || a.id.localeCompare(b.id));
}

function selectedItems(panelName) {
  const selected = state.selected[panelName];
  return allItems(panelName).filter((item) => selected.has(itemKey(item)));
}

function commonValues(items) {
  if (items.length === 0) {
    return [];
  }
  return items.reduce((values, item) => values.filter((value) => item.allowed_values.includes(value)), items[0].allowed_values);
}

function toggleSelection(panelName, items, select) {
  const selected = state.selected[panelName];
  items.forEach((item) => {
    if (select) {
      selected.add(itemKey(item));
    } else {
      selected.delete(itemKey(item));
    }
  });
}

function toggleSelectMode(panelName) {
  state.selecting[panelName] = !state.selecting[panelName];
  if (!state.selecting[panelName]) {
    state.selected[panelName].clear();
    setMessage(els.panels[panelName].notice, "");
  }
  renderPanel(panelName);
}

function render() {
  Object.values(Panel).forEach((panelName) => {
    const existing = new Set(allItems(panelName).map(itemKey));
    state.selected[panelName] = new Set([...state.selected[panelName]].filter((key) => existing.has(key)));
    renderPanel(panelName);
  });
  els.currentName.textContent = state.project ? state.project.name : "Проект не выбран";
  els.currentName.title = state.projectPath;
  els.openPresetsButton.disabled = !state.project;
}

function renderPanel(panelName) {
  const panel = els.panels[panelName];
  const selecting = state.selecting[panelName];
  panel.root.classList.toggle("selecting", selecting);
  if (selecting) {
    panel.selectToggle.textContent = "Отмена";
    panel.selectToggle.title = "Снять выбор и выйти из режима выбора";
  } else {
    panel.selectToggle.textContent = "Выбор";
    panel.selectToggle.title = "Режим выбора: отметить несколько элементов";
  }
  renderSort(panelName);
  renderTabs(panelName);
  renderList(panelName);
  renderBulk(panelName);
}

function renderTabs(panelName) {
  const selected = selectedItems(panelName);
  els.panels[panelName].tabs.replaceChildren(
    ...Object.values(Kind).map((kind) => {
      const tabProps = { role: "tab", ariaSelected: String(state.tabs[panelName] === kind) };
      const tab = button(tabProps, `${KIND_LABELS[kind]} ${tabCount(panelName, kind)}`, () => {
        state.tabs[panelName] = kind;
        renderPanel(panelName);
      });
      const selectedCount = selected.filter((item) => item.kind === kind).length;
      if (selectedCount > 0) {
        tab.append(el("span", { className: "tab-selected", title: "Выбрано" }, String(selectedCount)));
      }
      return tab;
    }),
  );
}

function tabCount(panelName, kind) {
  if (allItems(panelName).length === 0) {
    return "";
  }
  const items = filteredItems(panelName, kind);
  if (panelName === Panel.GLOBAL) {
    return items.length;
  }
  return `${items.filter(isEnabled).length}/${items.length}`;
}

function renderList(panelName) {
  const view = PANEL_VIEWS[panelName];
  const list = els.panels[panelName].list;
  if (!view.isLoaded()) {
    list.replaceChildren(el("li", { className: "empty" }, view.notLoadedText));
    return;
  }
  const items = visibleItems(panelName);
  if (items.length === 0) {
    list.replaceChildren(el("li", { className: "empty" }, view.emptyText));
    return;
  }
  list.replaceChildren(...items.map((item) => row(panelName, item, view.secondary(item), view.cells(item))));
}

function resetCell(item) {
  if (item.source !== Source.OVERRIDE) {
    return el("span");
  }
  return button({ className: "icon", title: RESET_TITLE }, "↺", () => setValue(Panel.PROJECT, item, null));
}

function row(panelName, item, secondary, cells) {
  const title = el("div", { className: "row-title" }, button({ className: "row-name", title: item.id }, item.id));
  if (item.locked) {
    title.append(el("span", { className: "lock", title: LOCKED_TITLE }, "🔒"));
  }
  if (item.note) {
    title.append(el("span", { className: "badge note" }, item.note));
  }
  const contents = contentsLabel(item.contents);
  if (contents) {
    title.append(el("span", { className: "contents", title: "Состав плагина: подробности по клику на строку" }, contents));
  }
  const main = el("div", { className: "row-main" }, title);
  if (secondary) {
    main.append(el("div", { className: "row-desc", title: secondary }, secondary));
  }
  const line = el("li", { className: `row grid-${panelName}` }, main, ...cells);
  line.classList.toggle("is-off", !isEnabled(item));
  const check = el("input", { type: "checkbox", title: "Выбрать", checked: state.selected[panelName].has(itemKey(item)) });
  const applySelection = () => {
    toggleSelection(panelName, [item], check.checked);
    line.classList.toggle("is-selected", check.checked);
    renderTabs(panelName);
    renderBulk(panelName);
  };
  check.addEventListener("change", applySelection);
  line.addEventListener("click", (event) => {
    if (event.target.closest(ROW_CONTROLS_SELECTOR)) {
      return;
    }
    if (state.selecting[panelName]) {
      check.checked = !check.checked;
      applySelection();
    } else {
      openDetail(item.kind, item.id);
    }
  });
  if (state.selecting[panelName]) {
    line.classList.toggle("is-selected", check.checked);
    line.prepend(check);
  }
  return line;
}

function contentsLabel(contents) {
  if (!contents) {
    return "";
  }
  const parts = [];
  if (contents.skills > 0) {
    parts.push(`${contents.skills} ${plural(contents.skills, SKILL_WORD_FORMS)}`);
  }
  if (contents.mcp > 0) {
    parts.push(`${contents.mcp} MCP`);
  }
  return parts.join(" · ");
}

function plural(count, [one, few, many]) {
  const lastDigit = count % 10;
  const lastTwo = count % 100;
  if (lastDigit === 1 && lastTwo !== 11) {
    return one;
  }
  if (lastDigit >= 2 && lastDigit <= 4 && (lastTwo < 12 || lastTwo > 14)) {
    return few;
  }
  return many;
}

function valueSelect(item, onChange) {
  const select = el("select", { className: `badge v-${item.value}`, title: "Значение", disabled: Boolean(item.locked) });
  if (item.locked) {
    select.title = LOCKED_TITLE;
  }
  item.allowed_values.forEach((value) => select.append(el("option", { value, selected: value === item.value }, value)));
  select.addEventListener("change", () => onChange(select.value));
  return select;
}

function renderBulk(panelName) {
  const bar = els.panels[panelName].bulk;
  bar.hidden = !state.selecting[panelName] || allItems(panelName).length === 0;
  if (bar.hidden) {
    bar.replaceChildren();
    return;
  }
  const visible = visibleItems(panelName);
  const chosen = selectedItems(panelName);
  const visibleChosen = visible.filter((item) => state.selected[panelName].has(itemKey(item)));

  const all = el("input", { type: "checkbox", title: "Выбрать все видимые или снять выбор", disabled: visible.length === 0 });
  all.checked = visible.length > 0 && visibleChosen.length === visible.length;
  all.indeterminate = visibleChosen.length > 0 && visibleChosen.length < visible.length;
  all.addEventListener("change", () => {
    toggleSelection(panelName, visible, visibleChosen.length === 0);
    renderPanel(panelName);
  });

  const editable = chosen.filter((item) => !item.locked);
  const values = el("select", { className: "bulk-value", title: "Задать значение выбранным (кроме заблокированных автором)", disabled: editable.length === 0 });
  values.append(el("option", { value: "" }, "Значение…"));
  commonValues(editable).forEach((value) => values.append(el("option", { value }, value)));
  values.addEventListener("change", () => {
    if (values.value) {
      runBatch(panelName, editable, values.value);
    }
  });

  const cells = [all, el("div", { className: "bulk-main" }, `Выбрано: ${chosen.length}`), values];
  if (panelName === Panel.PROJECT) {
    const resetProps = { className: "icon", title: "Сбросить переопределения у выбранных", disabled: editable.length === 0 };
    cells.push(button(resetProps, "↺", () => runBatch(panelName, editable, null)));
  }
  bar.replaceChildren(...cells);
}

function renderSort(panelName) {
  els.panels[panelName].sort.replaceChildren(
    ...PANEL_SORTS[panelName].map((sort) => {
      const optionProps = { role: "radio", title: SORT_TITLES[sort], ariaChecked: String(state.sorts[panelName] === sort) };
      return button(optionProps, SORT_LABELS[sort], () => {
        state.sorts[panelName] = sort;
        renderPanel(panelName);
      });
    }),
  );
}

async function loadRecent() {
  const projects = await api("GET", "/api/projects");
  renderRecent(projects.recent);
  return projects.recent;
}

async function openProject(path) {
  await loadProject(path.trim());
  render();
}

async function openFromPicker(path) {
  if (await busy(els.picker, els.pickerError, () => openProject(path))) {
    els.picker.close();
  }
}

async function showPicker() {
  els.pathInput.value = state.projectPath;
  els.picker.showModal();
  await busy(els.picker, els.pickerError, loadRecent);
  els.pathInput.focus();
}

function renderRecent(projects) {
  if (projects.length === 0) {
    els.recentList.replaceChildren(el("li", { className: "empty" }, "История пуста"));
    return;
  }
  els.recentList.replaceChildren(
    ...projects.map((project) => {
      const item = button({ className: "recent-item", title: project.path, disabled: !project.exists }, "", () =>
        openFromPicker(project.path),
      );
      item.replaceChildren(el("span", { className: "recent-name" }, project.name), el("span", { className: "recent-path" }, project.path));
      if (!project.exists) {
        item.title = `Папка не найдена: ${project.path}`;
      }
      item.classList.toggle("current", project.path === state.projectPath);
      return el("li", {}, item);
    }),
  );
}

async function loadPresets() {
  const data = await api("GET", "/api/presets");
  state.presets = data.presets;
}

async function openPresets() {
  renderPresets();
  els.presetsDialog.showModal();
  await withPresets(loadPresets);
}

async function withPresets(task) {
  await busy(els.presetsDialog, els.presetsError, task);
  renderPresets();
}

function projectOverrides() {
  return allItems(Panel.PROJECT)
    .filter((item) => item.source === Source.OVERRIDE && !item.locked)
    .map((item) => ({ kind: item.kind, id: item.id, value: item.value }));
}

function renderPresets() {
  if (state.presets.length === 0) {
    els.presetList.replaceChildren(el("li", { className: "empty" }, "Пресетов пока нет. Нажмите «Создать пресет»."));
    return;
  }
  els.presetList.replaceChildren(...state.presets.map(presetRow));
}

function presetRow(preset) {
  const edit = button({ className: "icon-button", title: "Изменить пресет", ariaLabel: "Изменить пресет" }, "", () => openPresetEditor(preset));
  edit.innerHTML = PENCIL_ICON;
  const remove = button({ className: "icon-button danger-icon", title: "Удалить пресет", ariaLabel: "Удалить пресет" }, "", () => deletePreset(preset));
  remove.innerHTML = TRASH_ICON;
  return el(
    "li",
    { className: "preset-row" },
    el("span", { className: "preset-title", title: preset.name }, preset.name),
    el("span", { className: "meta" }, `${preset.overrides.length} ${plural(preset.overrides.length, OVERRIDE_WORD_FORMS)}`),
    button({ className: "small", title: "Записать переопределения пресета в проект" }, "Применить", () => applyPreset(preset)),
    edit,
    remove,
  );
}

function projectItemsByKey() {
  return new Map(allItems(Panel.PROJECT).map((item) => [itemKey(item), item]));
}

function openPresetEditor(preset) {
  state.draft = { id: preset.id, overrides: preset.overrides.map((override) => ({ ...override })) };
  els.presetEditTitle.textContent = "Изменение пресета";
  els.presetEditName.value = preset.name;
  showDraftEditor();
}

function openNewPreset() {
  state.draft = { id: null, overrides: [] };
  els.presetEditTitle.textContent = "Новый пресет";
  els.presetEditName.value = "";
  showDraftEditor();
}

function showDraftEditor() {
  setMessage(els.presetEditError, "");
  renderDraft();
  els.presetEditDialog.showModal();
  els.presetEditName.focus();
}

function renderDraft() {
  const draft = state.draft;
  const items = projectItemsByKey();
  const rows = draft.overrides.map((override, index) => {
    const item = items.get(itemKey(override));
    const values = item ? item.allowed_values : [override.value];
    const select = el("select", { className: `badge v-${override.value}`, title: "Значение в пресете" });
    values.forEach((value) => select.append(el("option", { value, selected: value === override.value }, value)));
    select.addEventListener("change", () => {
      override.value = select.value;
      renderDraft();
    });
    const title = el("div", { className: "row-title" }, el("span", {}, override.id));
    if (!item) {
      title.append(el("span", { className: "badge note" }, "нет на устройстве"));
    }
    const remove = button({ className: "icon", title: "Убрать из пресета" }, "✕", () => {
      draft.overrides.splice(index, 1);
      renderDraft();
    });
    return el("div", { className: "override-row" }, el("span", { className: "meta" }, KIND_SINGULAR[override.kind]), title, select, remove);
  });
  if (rows.length === 0) {
    rows.push(el("p", { className: "meta" }, "Переопределений нет."));
  }
  const fromProject = projectOverrides();
  const addFromProject = button(
    { className: "small", title: "Добавить переопределения открытого проекта; для уже добавленных элементов взять значение из проекта", disabled: fromProject.length === 0 },
    `Добавить настройки из проекта (${fromProject.length})`,
    () => {
      const merged = new Map(draft.overrides.map((override) => [itemKey(override), override]));
      fromProject.forEach((override) => merged.set(itemKey(override), override));
      draft.overrides = [...merged.values()];
      renderDraft();
    },
  );
  els.presetEditOverrides.replaceChildren(el("div", { className: "draft-toolbar" }, addFromProject), ...rows, addOverrideRow(draft, items));
}

function addOverrideRow(draft, items) {
  const used = new Set(draft.overrides.map(itemKey));
  const kindSelect = el("select", { className: "bulk-value", title: "Тип" });
  Object.values(Kind).forEach((kind) => kindSelect.append(el("option", { value: kind }, KIND_SINGULAR[kind])));
  const itemSelect = el("select", { className: "bulk-value", title: "Элемент" });
  const valueSelect = el("select", { className: "bulk-value", title: "Значение" });
  const add = button({ className: "small", title: "Добавить переопределение в пресет" }, "Добавить", () => {
    draft.overrides.push({ kind: kindSelect.value, id: itemSelect.value, value: valueSelect.value });
    renderDraft();
  });

  const fillValues = () => {
    const item = items.get(`${kindSelect.value}:${itemSelect.value}`);
    valueSelect.replaceChildren(...(item ? item.allowed_values : []).map((value) => el("option", { value }, value)));
    add.disabled = !item;
  };
  const fillItems = () => {
    const candidates = [...items.values()].filter((item) => item.kind === kindSelect.value && !item.locked && !used.has(itemKey(item)));
    candidates.sort((a, b) => a.id.localeCompare(b.id));
    itemSelect.replaceChildren(...candidates.map((item) => el("option", { value: item.id }, item.id)));
    fillValues();
  };
  kindSelect.addEventListener("change", fillItems);
  itemSelect.addEventListener("change", fillValues);
  fillItems();
  return el("div", { className: "override-add" }, kindSelect, itemSelect, valueSelect, add);
}

async function saveDraft() {
  const draft = state.draft;
  const body = { name: els.presetEditName.value, overrides: draft.overrides };
  const saved = await busy(els.presetEditDialog, els.presetEditError, async () => {
    if (draft.id) {
      await api("PUT", `/api/presets/${draft.id}`, body);
    } else {
      await api("POST", "/api/presets", body);
    }
  });
  if (saved) {
    els.presetEditDialog.close();
    await withPresets(loadPresets);
  }
}

function describeChanges(preset) {
  const items = projectItemsByKey();
  return preset.overrides.map((override) => {
    const item = items.get(itemKey(override));
    if (!item) {
      return `• ${override.id}: нет на устройстве, будет пропущен`;
    }
    if (item.value === override.value) {
      return `• ${override.id}: ${override.value} (без изменений)`;
    }
    return `• ${override.id}: ${item.value} → ${override.value}`;
  });
}

async function deletePreset(preset) {
  if (!window.confirm(`Удалить пресет «${preset.name}»?`)) {
    return;
  }
  await withPresets(async () => {
    await api("DELETE", `/api/presets/${preset.id}`);
    await loadPresets();
  });
}

async function applyPreset(preset) {
  const question = `Применить пресет «${preset.name}» к проекту «${state.project.name}»?\n\n${describeChanges(preset).join("\n")}`;
  if (!window.confirm(question)) {
    return;
  }
  els.presetsDialog.close();
  await withPanel(Panel.PROJECT, async () => {
    const result = await api("POST", `/api/presets/${preset.id}/apply${projectQuery()}`);
    await reloadAfterChange(Panel.PROJECT, preset.overrides);
    setMessage(els.panels[Panel.PROJECT].notice, `Пресет «${preset.name}» применён: ${result.applied} из ${preset.overrides.length}.`);
    showBatchErrors(Panel.PROJECT, result);
  });
}

async function openDetail(kind, id) {
  els.dialogBody.replaceChildren(el("p", { className: "meta" }, "Загрузка…"));
  els.dialog.showModal();
  let url = `/api/items/${kind}/${encodeURIComponent(id)}`;
  if (state.projectPath) {
    url += projectQuery();
  }
  try {
    renderDetail(await api("GET", url));
  } catch (error) {
    els.dialogBody.replaceChildren(el("h3", {}, id), el("p", { className: "error" }, error.message));
  }
}

async function copyText(text, trigger) {
  try {
    await navigator.clipboard.writeText(text);
    trigger.innerHTML = CHECK_ICON;
    trigger.classList.add("copied");
    trigger.title = "Скопировано";
  } catch {
    trigger.title = "Не удалось скопировать";
  }
  setTimeout(() => {
    trigger.innerHTML = COPY_ICON;
    trigger.classList.remove("copied");
    trigger.title = COPY_TITLE;
  }, 1500);
}

async function shutdown() {
  if (!window.confirm("Остановить Claude Tools Config?")) {
    return;
  }
  try {
    await api("POST", "/api/shutdown");
  } catch (error) {
    if (!(error instanceof ServerUnavailableError)) {
      window.alert(error.message);
      return;
    }
  }
  window.close();
  document.title = "Claude Tools Config — остановлен";
  document.body.replaceChildren(
    el(
      "main",
      { className: "stopped" },
      el("h2", {}, "Claude Tools Config остановлен"),
      el("p", { className: "meta" }, "Вкладку можно закрыть. Запустить снова: python3 app.py"),
    ),
  );
}

function renderDetail(detail) {
  const parts = [el("h3", {}, detail.id), el("div", { className: "meta" }, KIND_LABELS[detail.kind])];
  if (detail.path) {
    const copy = button({ className: "icon-button", title: COPY_TITLE, ariaLabel: COPY_TITLE }, "", () => copyText(detail.path, copy));
    copy.innerHTML = COPY_ICON;
    parts.push(el("div", { className: "meta path-row" }, el("code", {}, detail.path), copy));
  }
  parts.push(el("p", { className: "text" }, detail.description || "Описания нет."));
  const skills = detail.children.filter((child) => child.kind === Kind.SKILL);
  const servers = detail.children.filter((child) => child.kind === Kind.MCP);
  if (skills.length > 0) {
    parts.push(el("h4", {}, `Скиллы плагина (${skills.length})`), childList(skills));
  }
  if (servers.length > 0) {
    parts.push(el("h4", {}, `MCP-серверы плагина (${servers.length})`), childList(servers));
  }
  if (detail.config.length > 0) {
    const rows = detail.config.map((entry) => el("tr", {}, el("td", {}, entry.key), el("td", {}, el("code", {}, entry.value))));
    parts.push(el("h4", {}, "Конфигурация"), el("table", {}, el("tbody", {}, ...rows)));
  }
  els.dialogBody.replaceChildren(...parts);
}

function childList(children) {
  return el(
    "ul",
    {},
    ...children.map((child) => {
      const item = el("li", {}, el("strong", {}, child.name));
      if (child.description) {
        item.append(` — ${child.description}`);
      }
      return item;
    }),
  );
}

function el(tag, props, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  node.append(...children);
  return node;
}

function button(props, label, onClick) {
  const node = el("button", { type: "button", ...props }, label);
  if (onClick) {
    node.addEventListener("click", onClick);
  }
  return node;
}

els.chooseButton.addEventListener("click", showPicker);
els.shutdownButton.addEventListener("click", shutdown);
els.openPresetsButton.addEventListener("click", openPresets);

els.projectForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (els.pathInput.value.trim()) {
    openFromPicker(els.pathInput.value);
  }
});

els.presetCreate.addEventListener("click", openNewPreset);

els.presetEditForm.addEventListener("submit", (event) => {
  event.preventDefault();
  saveDraft();
});

els.presetEditCancel.addEventListener("click", () => els.presetEditDialog.close());

Object.values(Panel).forEach((panelName) => {
  const panel = els.panels[panelName];
  panel.selectToggle.addEventListener("click", () => toggleSelectMode(panelName));
  panel.filter.addEventListener("input", () => {
    state.filters[panelName] = panel.filter.value;
    renderPanel(panelName);
  });
});

[els.picker, els.presetsDialog, els.dialog].forEach((dialog) => {
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) {
      dialog.close();
    }
  });
});

async function start() {
  render();
  const loadGlobal = withPanel(Panel.GLOBAL, async () => {
    await loadPool();
    render();
  });
  const loadLast = withPanel(Panel.PROJECT, async () => {
    const last = (await loadRecent()).find((project) => project.exists);
    if (last) {
      await openProject(last.path);
    }
  });
  await Promise.all([loadGlobal, loadLast]);
}

start();
