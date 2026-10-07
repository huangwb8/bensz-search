import { t } from "./i18n.js";
import { html, fmt, label, button, empty, formError, field, timeline } from './ui.js';
import { adminPages, userPages, pageInfo, shell, loginView, head, views, providerTable, keyTable, userTable, searchResults, sessionPanel } from './views.js';
import { providerForm, updateProviderFields, providerPayload, testForm, testResults, keyForm, userForm, importForm, reauthForm } from './forms.js';
const app = document.getElementById('app');
const dialog = document.getElementById('dialog');
const state = { user: null, csrf: '', expiresAt: null, expiryWarned: false, area: 'user', page: 'overview', providers: [], catalog: [], overview: null, data: {},
  revision: 0, authGeneration: 0, loadRevision: 0, currentURL: '', filters: {}, window: 'process', searchDraft: {}, searchResult: null, tests: {}, auditFilters: {}, auditOffset: 0,
  theme: localStorage.getItem('bensz-search-theme') || 'system', menuOpen: false, dialogDirty: false, dirtyForms: new Set(), secret: null, editor: null };
let opener = null;
let reauthPending = null;
const get = selector => document.querySelector(selector);
const setContent = (node, value) => { if (node) node.innerHTML = String(value); };
const busy = (button, value) => { if (button) { button.disabled = value; button.setAttribute('aria-busy', String(value)); } };
function applyTheme() {
  document.documentElement.dataset.theme = state.theme;
}
applyTheme();
function notify(message, error = false) {
  const container = document.getElementById('notice');
  const node = document.createElement('div');
  node.className = `toast${error ? ' error' : ''}`;
  node.setAttribute('role', error ? 'alert' : 'status');
  setContent(node, html`<span>${message}</span>${button(t("common.close"), 'notice-close', '', 'ghost')}`);
  container.append(node);
  if (!error) setTimeout(() => node.remove(), 6000);
  while (container.childElementCount > 5) container.firstElementChild.remove();
}
const errorMessages = {
  'Invalid credentials': t("copy.13fe36e577"), 'Invalid username or password': t("copy.13fe36e577"), 'Invalid current password': t("copy.f72ecf5321"),
  'Administrator required': t("copy.b8dbd20cee"), 'Invalid CSRF token': t("copy.56916f26f3"),
  'Cannot delete current user': t("copy.5d0f7f9974"), 'User already exists': t("copy.483d1c8d9f"),
  'Provider already exists': t("copy.59628b9f4c"), 'auto is reserved': t("copy.39036c1aa5"),
};
function friendlyError(data, status) {
  const detail = typeof data.detail === 'string' ? data.detail : '';
  if (errorMessages[detail]) return errorMessages[detail];
  const category = detail.match(/^搜索失败[:：]\s*([a-z_]+)$/);
  if (category) return t('error.searchFailure') + label(category[1]);
  if (/[\u3400-\u9fff]/.test(detail)) return detail;
  return ({ 400: t("copy.f055223322"), 401: t("copy.ac5a3fdfa3"), 403: t("copy.9381f7dcc2"),
    404: t("copy.2638f6f1a5"), 409: t("copy.7b95c4a340"), 422: t("copy.47f3645414"),
    429: t("copy.55b9f76375"), 502: t("copy.0499cdcbb4"), 503: t("copy.9b975432f8") })[status] || t("copy.8977b79aa8");
}
async function api(path, method = 'GET', payload, retry = true) {
  const generation = state.authGeneration;
  const headers = { Accept: 'application/json' };
  if (payload !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET') headers['X-CSRF-Token'] = state.csrf;
  let response;
  try {
    response = await fetch(`/admin/api${path}`, { method, credentials: 'same-origin', headers,
      body: payload === undefined ? undefined : JSON.stringify(payload), signal: AbortSignal.timeout(75000) });
  } catch (error) {
    throw new Error(error.name === 'TimeoutError' ? t("copy.bb2fa53a1a") : t("copy.e7b068fd04"));
  }
  const data = response.status === 204 ? {} : await response.json().catch(() => ({}));
  if (response.status === 401 && retry && generation === state.authGeneration && state.user && !['/login', '/session'].includes(path)) {
    await reauthenticate();
    return api(path, method, payload, false);
  }
  if (!response.ok) {
    const error = new Error(friendlyError(data, response.status));
    error.status = response.status;
    error.fields = data.errors || (Array.isArray(data.detail) ? data.detail.map(item => ({ field: item.loc?.at(-1), message: t("copy.d05af7799c") })) : []);
    throw error;
  }
  return data;
}
function errorBox(form, error) {
  if (!form?.isConnected) { notify(error.message, true); return; }
  form.querySelectorAll('.field-error').forEach(node => { node.textContent = ''; });
  form.querySelectorAll('[aria-invalid]').forEach(node => { node.removeAttribute('aria-invalid'); });
  const box = form.querySelector('.form-error');
  if (box) box.textContent = error.message;
  for (const item of error.fields || []) {
    const name = String(item.field || '').split('.').at(-1);
    const input = form.elements.namedItem(name);
    if (!input?.setAttribute) continue;
    input.setAttribute('aria-invalid', 'true');
    const marker = [...form.querySelectorAll('[data-error-for]')].find(node => node.dataset.errorFor === name);
    if (marker) { marker.textContent = /[\u3400-\u9fff]/.test(item.message) ? item.message : t("copy.3c2e6ec3dd"); marker.id = `${input.id}-error`; input.setAttribute('aria-describedby', marker.id); }
  }
  form.querySelector('[aria-invalid="true"]')?.focus();
}
function rememberSession(data) {
  if (state.user?.id !== data.user.id) state.authGeneration++;
  state.user = data.user;
  state.csrf = data.csrf_token;
  state.expiresAt = data.expires_at || data.session?.expires_at || null;
  state.expiryWarned = false;
}
async function reauthenticate() {
  if (reauthPending) return reauthPending;
  const restoreFocus = document.activeElement;
  const node = document.createElement('dialog');
  node.id = 'reauth-dialog';
  node.setAttribute('aria-labelledby', 'reauth-title');
  setContent(node, reauthForm(state));
  document.body.append(node);
  node.addEventListener('cancel', event => event.preventDefault());
  node.showModal();
  get('#reauth-password').focus();
  reauthPending = new Promise((resolve, reject) => { node._resolve = resolve; node._reject = reject; });
  await reauthPending;
  node.close(); node.remove(); reauthPending = null;
  restoreFocus?.focus();
}
function clearPrivateState() {
  state.user = null; state.csrf = ''; state.secret = null; state.overview = null; state.searchResult = null;
  state.searchDraft = {}; state.tests = {}; state.data = {}; state.providers = []; state.catalog = []; state.snippets = {}; state.filters = {};
  state.auditFilters = {}; state.auditOffset = 0; state.window = 'process'; state.expiresAt = null; state.expiryWarned = false; state.confirmAction = null; state.currentURL = '';
  state.menuOpen = false; document.body.classList.remove('menu-open'); state.dirtyForms.clear(); state.dialogDirty = false; state.editor = null;
  state.authGeneration++; state.revision++; closeDialog(true);
  opener = null; setContent(document.getElementById('notice'), html``);
}
function login() { setContent(app, loginView()); document.title = t("copy.fecec8e8ae"); get('#username')?.focus(); }
function locationState() {
  const [page, query = ''] = location.hash.slice(1).split('?');
  const params = new URLSearchParams(query);
  return { area: state.user?.role === 'admin' && !/^\/app(?:\/|$)/.test(location.pathname) ? 'admin' : 'user', page: page || 'overview', params };
}
async function enterWorkspace() {
  const route = locationState();
  if (state.user.role !== 'admin' && route.area === 'admin') route.area = 'user';
  state.area = route.area;
  setContent(app, shell(state));
  await navigate(route.page, { area: route.area, replace: true, params: route.params, force: true });
}
function hasUnsaved() { return state.dialogDirty || state.dirtyForms.size > 0; }
function confirmLeave() { return !hasUnsaved() || window.confirm(t("copy.35b71b16d8")); }
function markClean(form) { state.dirtyForms.delete(form?.id); if (form?.closest('#dialog')) state.dialogDirty = false; }
async function navigate(page, { area = state.area, replace = false, params = new URLSearchParams(), force = false, history = true } = {}) {
  if (!state.user) return;
  if (!force && !confirmLeave()) { restoreLocation(); return; }
  if (state.secret && !window.confirm(t("copy.fd3c79cd8b"))) { restoreLocation(); return; }
  const targetArea = area === 'admin' && state.user.role === 'admin' ? 'admin' : 'user';
  const pages = targetArea === 'admin' ? adminPages : userPages;
  if (!Object.hasOwn(pages, page)) page = 'overview';
  captureSearchDraft();
  state.dirtyForms.clear(); state.dialogDirty = false;
  closeDialog(true);
  const changeArea = state.area !== targetArea;
  state.area = targetArea; state.page = page;
  if (targetArea === 'user') state.window = 'process';
  const url = `${targetArea === 'admin' ? '/admin/' : '/app/'}#${page}${params.size ? '?' + params.toString() : ''}`;
  if (history && (replace || state.currentURL !== url)) window.history[replace ? 'replaceState' : 'pushState'](null, '', url);
  state.currentURL = url;
  if (changeArea) setContent(app, shell(state));
  if (page === 'search' && params.size) state.searchDraft = { ...state.searchDraft, ...Object.fromEntries(params) };
  updateNav(); setMenu(false);
  const revision = ++state.revision;
  const main = get('#main');
  setContent(main, html`${head(state)}<div class="skeleton" role="status" aria-label="${t("copy.f020e4630a")}"><div></div><div></div><div></div></div>`);
  try {
    const loaded = await loadPage();
    if (!loaded || state.revision !== revision) return;
    renderPage(); get('[data-testid="page-title"]')?.focus({ preventScroll: true });
    window.scrollTo({ top: 0 });
    if (page === 'providers' && params.get('provider')) openProvider(state.providers.find(p => p.name === params.get('provider')));
    if (page === 'overview' && params.get('request')) showRequest(params.get('request'));
  } catch (error) {
    if (state.revision !== revision) return;
    setContent(main, html`${head(state)}<section class="panel">${empty(t("copy.f3f42080d8"), error.message)}<div class="panel-body">${button(t("copy.7bdd5ce1e2"), 'refresh')}</div></section>`);
    notify(error.message, true);
  }
}
function updateNav() {
  updateVersion();
  document.querySelectorAll('.workspace-nav-link').forEach(node => {
    const active = node.dataset.area === state.area && node.dataset.page === state.page;
    node.classList.toggle('active', active);
    if (active) node.setAttribute('aria-current', 'page'); else node.removeAttribute('aria-current');
  });
  const info = pageInfo(state);
  get('#breadcrumb').textContent = info[0]; document.title = `${info[0]} · bensz-search`;
}
function updateVersion() {
  const node = get('#app-version');
  if (!node) return;
  const version = state.overview?.version;
  node.textContent = version ? `v${version}` : t("copy.ba21f3bbaa");
  node.title = version ? `${t("copy.6b727b3b96")} ${version}` : t("copy.1ed59e0dde");
  node.setAttribute('aria-label', node.title);
}
async function loadPage() {
  const page = state.page;
  const area = state.area;
  const window = state.window;
  const revision = state.revision;
  const loadRevision = ++state.loadRevision;
  const needsOverview = ['overview', 'search'].includes(page) || !state.overview;
  const overviewPromise = needsOverview ? api(`/overview?window=${window}`) : Promise.resolve(null);
  let path = null;
  if (page === 'providers') path = '/providers';
  if (page === 'keys') path = '/keys' + (area === 'admin' ? '?scope=all' : '');
  if (page === 'overview' && area === 'user') path = '/keys';
  if (page === 'users') path = '/users';
  if (page === 'settings') path = '/sessions';
  if (page === 'help') path = '/releases';
  if (page === 'audit') {
    const params = new URLSearchParams({ limit: '50', offset: String(state.auditOffset) });
    for (const [key, value] of Object.entries(state.auditFilters)) {
      if (!value) continue;
      params.set(key, ['since', 'until'].includes(key) ? String(new Date(value).getTime() / 1000) : value);
    }
    path = '/audit?' + params;
  }
  const [overview, data] = await Promise.all([overviewPromise, path ? api(path) : Promise.resolve({})]);
  if (revision !== state.revision || loadRevision !== state.loadRevision) return false;
  if (overview) { state.overview = overview; state.providers = overview.providers || []; updateVersion(); }
  state.data = data;
  if (page === 'providers') { state.providers = data.providers || []; state.catalog = data.catalog || []; }
  if (state.overview?.health) state.providers.forEach(provider => { provider.health ||= state.overview.health.find(row => row.name === provider.name); });
  return true;
}
function renderPage() { setContent(get('#main'), views[state.page](state)); }
async function refresh({ local = true } = {}) {
  const revision = state.revision;
  const focus = document.activeElement;
  const action = focus?.dataset.action;
  const value = focus?.dataset.value;
  const scroll = window.scrollY;
  get('#main')?.setAttribute('aria-busy', 'true');
  try {
    const loaded = await loadPage();
    if (!loaded || revision !== state.revision) return;
    const renderTable = { providers: providerTable, keys: keyTable, users: userTable }[state.page];
    if (local && state.page === 'settings' && get('#sessions-panel')) setContent(get('#sessions-panel'), sessionPanel(state));
    else if (local && renderTable && get('#table-results')) setContent(get('#table-results'), renderTable(state)); else renderPage();
    window.scrollTo({ top: scroll });
    const matching = [...document.querySelectorAll('[data-action]')].find(node => node.dataset.action === action && node.dataset.value === value);
    if (matching) matching.focus({ preventScroll: true }); else if (focus?.isConnected) focus.focus({ preventScroll: true });
  } finally { get('#main')?.removeAttribute('aria-busy'); }
}
function setMenu(value) {
  state.menuOpen = value; get('.sidebar')?.classList.toggle('nav-open', value);
  const button = get('[data-action="menu"]');
  button?.setAttribute('aria-expanded', String(value)); button?.setAttribute('aria-controls', 'navigation');
  const overlay = get('.nav-backdrop'); if (overlay) overlay.hidden = !value;
  document.body.classList.toggle('menu-open', value);
  if (get('.workspace')) get('.workspace').inert = value;
  if (value) get('.sidebar .workspace-nav-link')?.focus();
}
function openDialog(title, content, { drawer = true, dirty = false } = {}) {
  if (dialog.open && !closeDialog()) return false;
  opener = document.activeElement;
  state.dialogDirty = dirty;
  dialog.className = drawer ? 'drawer' : '';
  setContent(dialog, html`<div class="dialog-head"><h2 id="dialog-title">${title}</h2>${button(t("common.close"), 'dialog-close', '', 'dialog-close')}</div><div class="dialog-body">${content}</div>`);
  dialog.showModal(); dialog.querySelector('input:not(:disabled),button')?.focus();
  return true;
}
function closeDialog(force = false) {
  if (!force && state.secret && !window.confirm(t("copy.73f30a5e2d"))) return false;
  if (!force && state.dialogDirty && !window.confirm(t("copy.7069e02be8"))) return false;
  state.secret = null; state.dialogDirty = false;
  dialog.querySelectorAll('form').forEach(form => state.dirtyForms.delete(form.id));
  dialog.close(); setContent(dialog, html``);
  if (opener?.isConnected) opener.focus({ preventScroll: true });
  return true;
}
dialog.addEventListener('cancel', event => { event.preventDefault(); closeDialog(); });
function confirmAction(title, description, action, confirmText) {
  if (!openDialog(title, html`<form id="confirm-form"><p>${description}</p>${formError()}<div class="form-actions">
    ${button(t("common.cancel"), 'dialog-close')}<button class="btn danger" type="submit">${confirmText}</button></div></form>`, { drawer: false })) return;
  state.confirmAction = action;
}
async function openProvider(provider) {
  if (!state.catalog.length) {
    const data = await api('/providers'); state.catalog = data.catalog || [];
    if (!state.providers.length) state.providers = data.providers || [];
  }
  if (!openDialog(provider ? `${t("copy.0518365699")} ${provider.name}` : t("copy.01a1f239e9"), providerForm(state, provider))) return;
  state.editor = provider || null;
  updateProviderFields(state, Boolean(provider), !provider);
}
function openTest(name) { openDialog(`${t("copy.6aa8f49cc9")} ${name}`, testForm(state, name)); }
function showRequest(id) {
  const request = state.overview?.metrics?.recent?.find(row => row.request_id === id);
  if (request) openDialog(t("copy.0ec1e85b0c"), html`<p class="mono">${id}</p>${button(t("copy.b9431e8522"), 'request-share', id)}${timeline(request)}`);
  else notify(t("copy.10bb4ae8ff"), true);
}
function captureSearchDraft() {
  const form = get('#search-form');
  if (form) state.searchDraft = Object.fromEntries(new FormData(form));
}
function searchPayload() {
  captureSearchDraft(); const draft = state.searchDraft;
  const constraints = {};
  for (const key of ['freshness', 'authority', 'recall', 'precision', 'semantic', 'source_diversity', 'latency', 'cost']) constraints[key] = draft[key] || 'auto';
  for (const key of ['latency_budget_ms', 'cost_budget_usd']) if (draft[key] !== '' && draft[key] != null) constraints[key] = Number(draft[key]);
  return { query: draft.query || '', search_tool_name: draft.search_tool_name || 'auto', profile: { intent: draft.intent || 'auto' }, constraints,
    max_results: Number(draft.max_results || 10), fusion: draft.fusion || 'weighted_rrf', debug: true,
    search_domain_filter: String(draft.search_domain_filter || '').split(',').map(value => value.trim()).filter(Boolean) };
}
async function copy(value) {
  try { await navigator.clipboard.writeText(value); notify(t("copy.cce28dd1fc")); }
  catch {
    if (state.secret) { const range = document.createRange(); range.selectNodeContents(get('#new-key')); const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range); notify(t("copy.ef78a62e7a"), true); }
    else openDialog(t("copy.8f0b2d9549"), html`<p>${t("copy.f726d4409e")}</p><pre class="code key-value">${value}</pre>`, { drawer: false });
  }
}
function share(page, params) {
  const url = new URL(`${state.area === 'admin' ? '/admin/' : '/app/'}#${page}?${new URLSearchParams(params)}`, location.origin);
  return copy(url.href);
}
function enabledWarning(provider) {
  return provider?.enabled && state.providers.filter(p => p.enabled).length === 1 ? t("copy.2fe5648583") : '';
}
async function performProviderToggle(name) {
  const provider = state.providers.find(p => p.name === name);
  const warning = enabledWarning(provider);
  const save = async () => {
    const allowed = ['name', 'provider', 'api_base', 'engines', 'timeout_ms', 'search_model', 'search_context_size', 'max_output_tokens', 'source_family', 'estimated_cost_usd'];
    const payload = Object.fromEntries(allowed.filter(key => provider[key] !== undefined).map(key => [key, provider[key]]));
    payload.enabled = !provider.enabled;
    await api(`/providers/${encodeURIComponent(name)}`, 'PUT', payload); await refresh(); notify(t("copy.24ab1478b0"));
  };
  if (warning) confirmAction(t("copy.d836cb6c7f"), warning, save, t("copy.b6c82c2d56")); else await save();
}
const actions = {
  navigate: node => navigate(node.dataset.page, { area: node.dataset.area }), go: node => navigate(node.dataset.value), refresh: () => refresh(),
  menu: () => setMenu(!state.menuOpen), 'menu-close': () => { setMenu(false); get('[data-action="menu"]')?.focus(); },
  'nav-group': node => { const expanded = node.getAttribute('aria-expanded') !== 'true'; node.setAttribute('aria-expanded', String(expanded)); document.getElementById(node.getAttribute('aria-controls')).hidden = !expanded; },
  'dialog-close': () => closeDialog(), 'notice-close': node => node.closest('.toast').remove(),
  logout: () => {
    if (!confirmLeave()) return;
    if (state.secret && !window.confirm(t("copy.43250a3c3b"))) return;
    return api('/logout', 'POST', {}).then(() => { clearPrivateState(); login(); });
  },
  'provider-add': () => openProvider(), 'provider-edit': node => openProvider(state.providers.find(p => p.name === node.dataset.value)),
  'provider-share': node => share('providers', { provider: node.dataset.value }),
  'provider-test': node => openTest(node.dataset.value), 'provider-toggle': node => performProviderToggle(node.dataset.value),
  'provider-delete': node => confirmAction(t("copy.f19f78c822"), `${t("copy.9fad3beb44")}${node.dataset.value}${t("copy.8e44226292")}${enabledWarning(state.providers.find(p => p.name === node.dataset.value))}`,
    async () => { await api(`/providers/${encodeURIComponent(node.dataset.value)}`, 'DELETE'); await refresh(); notify(t("copy.69100b1b55")); }, t("copy.6a39f69d94")),
  'provider-common-engines': () => { get('#provider-engines').value = (state.catalog.find(p => p.provider === 'searxng')?.default_engines || []).join(', '); state.dialogDirty = true; },
  'provider-sync': async node => {
    const result = await api(`/providers/${encodeURIComponent(node.dataset.value)}/engines/sync`, 'POST', {});
    await refresh(); notify(`${t("copy.830cd93339")}${(result.verified_engines || []).join(', ') || t("copy.ad10fed6f9")}`);
    if (dialog.open) {
      const note = get('#searxng-options .note');
      if (note) setContent(note, html`<p>${t("copy.00097d89c4")}${(result.verified_engines || []).join(', ') || t("copy.484d556139")}</p><p>${t("copy.8124cd7ac2")}${result.evidence}</p>`);
    }
  },
  'provider-export': async () => {
    const data = await api('/providers/export'); const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'bensz-search-providers.json'; link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    notify(t("copy.06e5a1efe8"));
  },
  'provider-import': () => openDialog(t("copy.b3c8f4cba9"), importForm()),
  'request-detail': node => showRequest(node.dataset.value), 'request-share': node => share('overview', { request: node.dataset.value }),
  'search-curl': () => { const payload = searchPayload(); return copy(`curl '${location.origin}/search' \\\n  -H 'Authorization: Bearer YOUR_API_KEY' \\\n  -H 'Content-Type: application/json' \\\n  -d '${JSON.stringify(payload).replaceAll("'", "'\\''")}'`); },
  'search-share': () => { captureSearchDraft(); return share('search', state.searchDraft); },
  snippet: node => { const expanded = node.closest('.result').querySelector('.result-snippet').classList.toggle('expanded'); node.textContent = expanded ? t("copy.fcd57ae6f6") : t("copy.60d4cbf2ff"); node.setAttribute('aria-expanded', String(expanded)); },
  'key-create': () => openDialog(t("copy.4e800de275"), keyForm()),
  'key-revoke': node => confirmAction(t("copy.b115c361e1"), t("copy.4d7eb33ed9"),
    async () => { await api(`/keys/${encodeURIComponent(node.dataset.value)}${state.area === 'admin' ? '?scope=all' : ''}`, 'DELETE'); await refresh(); notify(t("copy.c45b2a26d9")); }, t("copy.29b78a203e")),
  'key-delete': node => confirmAction(t("key.deleteTitle"), t("key.deleteWarning"),
    async () => { await api(`/keys/${encodeURIComponent(node.dataset.value)}?permanent=true${state.area === 'admin' ? '&scope=all' : ''}`, 'DELETE'); await refresh(); notify(t("key.deleted")); }, t("key.deleteConfirm")),
  'copy-key': () => copy(state.secret), 'key-done': () => closeDialog(true),
  'user-create': () => { state.editor = null; openDialog(t("copy.7db1237290"), userForm()); },
  'user-edit': node => { state.editor = state.data.users.find(user => String(user.id) === node.dataset.value); openDialog(t("copy.7645d83833"), userForm(state.editor)); },
  'user-delete': node => confirmAction(t("copy.963d52729b"), t("copy.5ff609bfa0"),
    async () => { await api(`/users/${encodeURIComponent(node.dataset.value)}`, 'DELETE'); await refresh(); notify(t("copy.7ad39d9c27")); }, t("copy.ceae8cfecd")),
  'sessions-revoke': () => confirmAction(t("copy.54a43c4b0e"), t("copy.20a3b210b5"),
    async () => { await api('/sessions/revoke-others', 'POST', {}); await refresh(); notify(t("copy.d96d4f89d0")); }, t("copy.16f39991a0")),
  'copy-snippet': node => copy(state.snippets[node.dataset.value]),
  'audit-prev': async () => { if (state.auditOffset > 0) { state.auditOffset -= 50; await refresh({ local: false }); } },
  'audit-next': async () => { if (state.auditOffset + 50 < state.data.total) { state.auditOffset += 50; await refresh({ local: false }); } },
};
const submitters = {
  'login-form': async form => { const data = await api('/login', 'POST', Object.fromEntries(new FormData(form)), false); rememberSession(data); markClean(form); await enterWorkspace(); },
  'reauth-form': async form => {
    const node = form.closest('dialog');
    const data = await api('/login', 'POST', { username: state.user.username, password: form.elements.password.value }, false);
    const previousRole = state.user.role;
    rememberSession(data); form.elements.password.value = '';
    if (previousRole !== state.user.role) { node._resolve(); closeDialog(true); state.dirtyForms.clear(); await enterWorkspace(); } else node._resolve();
    notify(t("copy.b83ae0528e"));
  },
  'confirm-form': async form => { await state.confirmAction(); markClean(form); closeDialog(true); },
  'provider-form': async (form, submitter) => {
    const original = state.editor;
    const payload = providerPayload(form, original);
    if (original?.enabled && !payload.enabled && enabledWarning(original) && !window.confirm(enabledWarning(original) + t("copy.edbeace735"))) return;
    await api(original ? `/providers/${encodeURIComponent(original.name)}` : '/providers', original ? 'PUT' : 'POST', payload);
    markClean(form); closeDialog(true); await refresh(); notify(t("copy.bb22e9d840"));
    if (submitter.value === 'test') openTest(payload.name);
  },
  'test-form': async form => {
    const name = form.dataset.provider; const query = form.elements.query.value;
    const generation = state.authGeneration;
    const revision = state.revision; setContent(get('#test-results'), html`<p role="status">${t("copy.713fc343f0")}</p>`);
    const data = await api(`/providers/${encodeURIComponent(name)}/test`, 'POST', { query });
    if (generation !== state.authGeneration) return;
    state.tests[name] = { query, data };
    if (revision === state.revision && get('#test-form') === form) setContent(get('#test-results'), testResults(data));
  },
  'search-form': async form => {
    const payload = searchPayload(); const revision = state.revision; const generation = state.authGeneration;
    get('#results-meta').textContent = t("copy.2f94db33f8");
    setContent(get('#search-results'), html`<div class="skeleton" role="status" aria-label="${t("copy.71a7040350")}"><div></div><div></div></div>`);
    try {
      const data = await api('/search', 'POST', payload);
      if (generation !== state.authGeneration) return;
      state.searchResult = data;
      if (state.revision === revision && get('#search-results')) { setContent(get('#search-results'), searchResults(state)); get('#results-meta').textContent = `${fmt(data.results?.length)} ${t("copy.bd0bedc6f4")}`; }
    } catch (error) {
      if (state.revision === revision) { setContent(get('#search-results'), state.searchResult ? searchResults(state) : empty(t("copy.43034354a9"), t("copy.5ea28dbb5a"))); get('#results-meta').textContent = t("copy.126fbf59cf"); }
      throw error;
    }
  },
  'key-form': async form => {
    const fields = new FormData(form); const scopes = [];
    if (fields.has('scope_search')) scopes.push('search'); if (fields.has('scope_protocol')) scopes.push('protocol');
    if (!scopes.length) throw new Error(t("copy.6e44d4b4ad"));
    const payload = { name: fields.get('name'), scopes };
    if (fields.get('expires_at')) { payload.expires_at = new Date(fields.get('expires_at')).getTime() / 1000; if (payload.expires_at <= Date.now() / 1000) throw new Error(t("copy.852da0a8f0")); }
    const data = await api('/keys', 'POST', payload);
    markClean(form); closeDialog(true);
    openDialog(t("copy.bf298fae98"), html`<div class="note warning">${t("copy.58ea1565dd")}</div><div class="key-value" id="new-key" data-testid="new-key">${data.key}</div>
      <div class="form-actions">${button(t("copy.d22d5fd54c"), 'copy-key')}${button(t("copy.0e1df87d77"), 'key-done', '', 'primary')}</div>`, { drawer: false });
    state.secret = data.key; await refresh();
  },
  'user-form': async form => {
    const fields = new FormData(form); const original = state.editor;
    const payload = original ? { role: fields.get('role'), enabled: fields.has('enabled') } : Object.fromEntries(fields);
    if (original && fields.get('password')) payload.password = fields.get('password');
    await api(original ? `/users/${encodeURIComponent(original.id)}` : '/users', original ? 'PUT' : 'POST', payload);
    markClean(form); closeDialog(true); await refresh(); notify(t("copy.6d162be163"));
    if (original?.id === state.user.id && original.role !== payload.role) { state.user.role = payload.role; await enterWorkspace(); }
  },
  'password-form': async form => {
    const fields = new FormData(form);
    if (fields.get('new_password') !== fields.get('confirm_password')) throw new Error(t("copy.a2ba2545a6"));
    await api('/password', 'POST', { current_password: fields.get('current_password'), new_password: fields.get('new_password') });
    markClean(form); clearPrivateState(); login(); notify(t("copy.207dcb8e9b"));
  },
  'audit-form': async form => { state.auditFilters = Object.fromEntries(new FormData(form)); state.auditOffset = 0; await refresh({ local: false }); },
  'import-form': async form => {
    const file = form.elements.file.files[0]; if (!file || file.size > 1024 * 1024) throw new Error(t("copy.a54158bc43"));
    let data; try { data = JSON.parse(await file.text()); } catch { throw new Error(t("copy.f47fb5c131")); }
    if (data.version !== 1 || !Array.isArray(data.providers)) throw new Error(t("copy.7c713ea92f"));
    if (data.providers.some(p => p.api_key || p.has_api_key || p.verified_engines?.length || p.engine_evidence)) throw new Error(t("copy.51c575ec39"));
    await api('/providers/import', 'POST', data); markClean(form); closeDialog(true); await refresh(); notify(t("copy.e8b96eaa3d"));
  },
};
// A single event delegate handles all application buttons and forms.
document.addEventListener('click', async event => {
  const node = event.target.closest('[data-action]');
  if (!node || !actions[node.dataset.action]) return;
  if (node.tagName === 'A' && (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey)) return;
  event.preventDefault();
  if (node.disabled) return;
  const isButton = node.tagName === 'BUTTON'; if (isButton) busy(node, true);
  try { await actions[node.dataset.action](node); }
  catch (error) { notify(error.message, true); }
  finally { if (isButton) busy(node, false); }
});
document.addEventListener('submit', async event => {
  const form = event.target;
  if (!submitters[form.id]) return;
  event.preventDefault(); const button = event.submitter || form.querySelector('[type="submit"]');
  const buttons = [...form.querySelectorAll('[type="submit"]')]; if (buttons.some(node => node.disabled)) return;
  buttons.forEach(node => busy(node, true));
  if (form.querySelector('.form-error')) form.querySelector('.form-error').textContent = '';
  try { await submitters[form.id](form, button); }
  catch (error) { errorBox(form, error); }
  finally { buttons.forEach(node => busy(node, false)); }
});
document.addEventListener('input', event => {
  const form = event.target.closest('form');
  if (form && !['search-form', 'test-form', 'login-form', 'reauth-form', 'audit-form'].includes(form.id)) {
    state.dirtyForms.add(form.id); if (form.closest('#dialog')) state.dialogDirty = true;
  }
  if (form?.id === 'search-form') captureSearchDraft();
  if (event.target.name === 'filter-query') updateFilter(event.target);
});
function updateFilter(input) {
  state.filters[state.page] ||= { query: '', status: 'all', sort: 'name' };
  state.filters[state.page][{ 'filter-query': 'query', 'filter-status': 'status', 'filter-sort': 'sort' }[input.name]] = input.value;
  const render = { providers: providerTable, keys: keyTable, users: userTable }[state.page]; if (render) setContent(get('#table-results'), render(state));
}
document.addEventListener('change', async event => {
  const input = event.target;
  try {
    if (input.id === 'provider-type') updateProviderFields(state, Boolean(state.editor), true);
    if (['filter-status', 'filter-sort'].includes(input.name)) updateFilter(input);
    if (input.name === 'metrics-window') { state.window = input.value; await refresh({ local: false }); }
    if (input.name === 'theme') { state.theme = input.value; localStorage.setItem('bensz-search-theme', state.theme); applyTheme(); }
  } catch (error) { notify(error.message, true); }
});
document.addEventListener('keydown', event => {
  if (event.key === 'Tab' && state.menuOpen) {
    const nodes = [...get('.sidebar').querySelectorAll('a,button')].filter(node => node.getClientRects().length);
    if (event.shiftKey && document.activeElement === nodes[0]) { event.preventDefault(); nodes.at(-1).focus(); }
    if (!event.shiftKey && document.activeElement === nodes.at(-1)) { event.preventDefault(); nodes[0].focus(); }
  }
  if (event.key === 'Escape' && state.menuOpen) { event.preventDefault(); setMenu(false); get('[data-action="menu"]')?.focus(); } });
window.addEventListener('resize', () => { if (innerWidth > 720 && state.menuOpen) setMenu(false); });
window.addEventListener('beforeunload', event => { if (hasUnsaved() || state.secret) { event.preventDefault(); event.returnValue = ''; } });
function restoreLocation() { if (state.currentURL) history.replaceState(null, '', state.currentURL); }
function replayLocation() {
  if (!state.user || ['#main', '#login-form', '#search-capabilities'].includes(location.hash)) return;
  if (state.currentURL === `${location.pathname}${location.hash}`) return;
  const route = locationState(); navigate(route.page, { area: route.area, params: route.params, replace: true });
}
window.addEventListener('popstate', replayLocation);
window.addEventListener('hashchange', replayLocation);
document.querySelector('.skip-link').addEventListener('click', event => { const main = get('#main'); if (main) { event.preventDefault(); main.focus(); main.scrollIntoView({ block: 'start' }); } });
setInterval(() => {
  if (!state.user || !state.expiresAt || state.expiryWarned) return;
  if (state.expiresAt * 1000 - Date.now() < 300000) { state.expiryWarned = true; notify(t("copy.f15d0b371a")); }
}, 30000);
async function initialize() {
  try { rememberSession(await api('/session', 'GET', undefined, false)); await enterWorkspace(); }
  catch { login(); }
}
initialize();
