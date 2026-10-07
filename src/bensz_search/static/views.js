import { t } from "./i18n.js";
import { html, fmt, money, date, time, label, badge, button, empty, panel, body, table, field, formError, options, more, results, timeline, brand } from './ui.js';
export const adminPages = {
  overview: [t("copy.17826325a8"), t("copy.e453d0e532")], providers: ['Search API', t("copy.fad1bb4a41")],
  search: [t("copy.7bc3f12944"), t("copy.3c64829b3a")], keys: [t("copy.d497c15b0c"), t("copy.a5ed694c84")],
  users: [t("copy.fbf413d429"), t("copy.b25cfe77f2")], audit: [t("copy.a0f79e91f1"), t("copy.99c5f7bf43")],
};
export const userPages = {
  overview: [t("copy.af807bc3f5"), t("copy.47079f22ef")], search: [t("copy.44ce7ae909"), t("copy.1f224bfc43")],
  keys: [t("copy.871d639f51"), t("copy.806832503e")], settings: [t("copy.5ce662ac8d"), t("copy.1f5bc94035")],
  integration: [t("copy.c99aba06fb"), t("copy.236b07ee48")], help: [t("copy.ff0d31688b"), t("copy.91877764ac")],
};
export const pageInfo = state => (state.area === 'admin' ? adminPages : userPages)[state.page] || userPages.help;
export function head(state, actions = html``) {
  const [title, description] = pageInfo(state);
  return html`<div class="page-head"><div><h1 tabindex="-1" data-testid="page-title">${title}</h1><p>${description}</p></div><div class="actions">${actions}</div></div>`;
}
export function loginView() {
  return html`<div class="login-layout"><header class="login-header"><div class="login-nav"><a class="brand" href="/" aria-label="${t("copy.b32942325e")}">${brand()}</a>
    <nav class="login-nav-links" aria-label="${t("copy.7ed35d05a8")}"><a href="#search-capabilities">${t("copy.b4f6e30d0a")}</a><a href="/api/docs" target="_blank" rel="noopener noreferrer">${t("copy.0c21997c24")}</a><a href="#login-form">${t("copy.b62e6e9a26")}</a></nav></div></header>
    <main class="login-content" id="main" tabindex="-1"><section class="login-intro" aria-labelledby="home-title"><p class="eyebrow">SEARCH INFRASTRUCTURE, SIMPLIFIED</p>
    <h1 id="home-title">${t("copy.ad3ae03b71")}<br><span>${t("copy.16531fe4fa")}</span></h1><p class="lead">${t("copy.0b8329716e")}<br>${t("copy.1bb1b3169d")}</p>
    <a class="home-action" href="#login-form">${t("copy.eb625f2142")}</a>
    <div class="search-flow" aria-label="${t("copy.9e9791de22")}"><span>${t("copy.531e8593b5")}</span><span aria-hidden="true">→</span><span>${t("copy.5ce6704c0c")}</span><span aria-hidden="true">→</span><span>${t("copy.d77d6bac20")}</span></div>
    <p class="flow-caption">${t("copy.d908b26348")}</p></section><section class="login-main" aria-labelledby="login-title">
    <form id="login-form" class="login-form" data-testid="login-form">
      <p class="eyebrow">YOUR SEARCH WORKSPACE</p><h2 id="login-title">${t("copy.e64e5ddd50")}</h2><p class="intro">${t("copy.9ed060845e")}</p>
    ${formError()}${field('username', t("account.username"), '', { required: true, maxlength: 64, autocomplete: 'username' })}
    ${field('password', t("account.password"), '', { type: 'password', required: true, autocomplete: 'current-password' })}<button class="btn primary" type="submit">${t("copy.e129ac5387")}</button>
    <p class="login-footer">${t("copy.8f7937fed7")}<br>${t("copy.c8fd10f00b")}</p></form><p class="login-help">${t("copy.80276ff350")}</p></section></main>
    <section class="home-capabilities" id="search-capabilities" aria-label="${t("copy.b4f6e30d0a")}">${[
      ['01 / CONNECT', t("copy.85dd9795a4"), t("copy.a9b11cae7a")], ['02 / SEARCH', t("copy.840154c82f"), t("copy.f016875267")],
      ['03 / INTEGRATE', t("copy.b3f3b88611"), t("copy.5607c134be")],
    ].map(([number, title, description]) => html`<div class="capability"><span class="capability-number">${number}</span><h2>${title}</h2><p>${description}</p></div>`)}</section>
    <footer class="home-footer"><span>${t("copy.fecec8e8ae")}</span><span>${t("copy.3c0b24a180")}</span></footer></div>`;
}
export function shell(state) {
  const groups = state.user.role === 'admin' ? [['admin', t("copy.e19796712f"), adminPages], ['user', t("copy.0d0e1a86b3"), userPages]] : [['user', t("copy.0d0e1a86b3"), userPages]];
  return html`<div class="layout"><button class="nav-backdrop" data-action="menu-close" aria-label="${t("copy.baf9f5c82a")}" hidden></button><aside class="sidebar">
    <div class="sidebar-header"><a class="brand" href="/" aria-label="${t("copy.b32942325e")}">${brand(true)}</a>${button(t("copy.4ce4cafdd0"), 'menu', '', 'menu-toggle')}</div>
    <div class="nav" id="navigation">${groups.map(([area, title, pages]) => html`<section class="workspace-nav-group">
      <button class="workspace-nav-group-toggle" data-action="nav-group" data-value="${area}" aria-expanded="true" aria-controls="nav-${area}">${title}<span aria-hidden="true">⌄</span></button>
      <nav id="nav-${area}" aria-label="${title}${t("copy.88b7692bf5")}">${Object.entries(pages).map(([page, info]) => html`<a class="workspace-nav-link" href="${area === 'admin' ? '/admin/' : '/app/'}#${page}"
        data-action="navigate" data-page="${page}" data-area="${area}" data-testid="nav-${area}-${page}"><span>${info[0]}</span><span class="nav-chevron" aria-hidden="true">›</span></a>`)}</nav></section>`)}</div>
    <div class="sidebar-foot"><span>${t("copy.17dae5c572")}</span><a href="/app/#help" data-action="navigate" data-page="help" data-area="user">${t("copy.cde22723fd")}</a></div></aside>
    <div class="workspace"><header class="topbar"><div class="topbar-title"><a href="#overview" data-action="navigate" data-page="overview" data-area="${state.area}">
    ${state.area === 'admin' ? t("copy.ed498fef60") : t("copy.45de2b4b5d")}</a><span class="breadcrumb-divider" aria-hidden="true">/</span><span id="breadcrumb"></span></div>
    <div class="account"><span class="user-name">${state.user.username}</span><span class="role">${label(state.user.role)}</span>${button(t("copy.3ab8cc1593"), 'logout', '', 'ghost')}</div></header>
    <main id="main" class="content" tabindex="-1" data-testid="workspace"></main></div></div>`;
}
function toolbar(state, placeholder = t("copy.aa68ada095")) {
  const filter = state.filters[state.page] || { query: '', sort: 'name', status: 'all' };
  return html`<div class="table-toolbar">${field('filter-query', t("copy.b5f15473fd"), filter.query, { placeholder })}
    ${field('filter-status', t("copy.6320b4a872"), filter.status, { choices: [['all', t("copy.5c55a67935")], ['active', t("copy.fd30f39c85")], ['inactive', t("copy.1a4a794baf")]] })}
    ${field('filter-sort', t("copy.a96c9a8541"), filter.sort, { choices: [['name', t("copy.5b3a23f0de")], ['name-desc', t("copy.7a7e3e5968")], ['newest', t("copy.ee34c74d32")]] })}</div>`;
}
function filtered(state, records) {
  const filter = state.filters[state.page] || {};
  const rows = records.filter(row => {
    const active = !row.revoked && row.enabled !== false && (!row.expires_at || row.expires_at > Date.now() / 1000);
    return (!filter.query || `${row.name || row.username || ''} ${row.provider || ''} ${row.username || ''}`.toLowerCase().includes(filter.query.toLowerCase()))
      && (!filter.status || filter.status === 'all' || active === (filter.status === 'active'));
  });
  return rows.sort((a, b) => filter.sort === 'newest' ? (b.created_at || 0) - (a.created_at || 0)
    : String(a.name || a.username).localeCompare(String(b.name || b.username), 'zh-CN') * (filter.sort === 'name-desc' ? -1 : 1));
}
export function providerTable(state, editable = true) {
  const records = filtered(state, state.providers);
  return records.length ? table(t("copy.952e65b75b"), [t("copy.5df7bfb4b7"), t("copy.1f27353320"), t("copy.e38ab48681"), ...(editable ? [t("copy.ed31fbb483")] : [])], records.map(provider => [
    html`<strong>${provider.name}</strong><span class="cell-sub">${provider.provider}</span>`,
    html`${badge(provider.enabled ? 'active' : 'disabled', provider.enabled ? t("copy.dfb802238b") : t("copy.a8c3698b5b"))}${badge(provider.health?.state || 'unknown')}
      ${provider.health?.cooldown_remaining_s ? html`<span class="cell-sub">${t("copy.5e6b1ee740")} ${fmt(provider.health.cooldown_remaining_s)} ${t("copy.9dcdc2b289")}</span>` : ''}`,
    html`<span class="endpoint">${provider.api_base || t("copy.98212975dd")}</span><span class="cell-sub">${provider.has_api_key ? t("copy.8f1fb304f0") : t("copy.df14a63098")} ${t("copy.61e1f7d452")} ${fmt(provider.timeout_ms)} ms</span>
      ${provider.health?.last_error ? html`<span class="cell-sub">${t("copy.ccd249b39e")}${label(provider.health.last_error)}</span>` : ''}`,
    ...(editable ? [html`<div class="actions">${button(t("copy.0518365699"), 'provider-edit', provider.name)}${button(t("copy.6aa8f49cc9"), 'provider-test', provider.name)}${more(html`
      ${provider.provider === 'searxng' ? button(t("copy.3339ffdfa0"), 'provider-sync', provider.name) : ''}${button(provider.enabled ? t("copy.4e6fd0e28c") : t("copy.f4f0ead111"), 'provider-toggle', provider.name)}
      ${button(t("copy.2f9daa8289"), 'provider-delete', provider.name, 'danger')}`)}</div>`] : []),
  ])) : empty(t("copy.cbb4f900a0"), t("copy.e4627db9fd"));
}
function trend(data) {
  const values = data.map(row => Number(row.requests) || 0);
  if (!values.length) return html`<p class="muted">${t("copy.68e87e2726")}</p>`;
  const max = Math.max(...values, 1);
  const width = Math.max(data.length * 48, 240);
  const step = width / data.length;
  return html`<div class="trend"><svg class="trend-svg" viewBox="0 0 ${width} 160" role="img" aria-label="${t('copy.7b3c22fb10')}">
    ${data.map((row, index) => {
      const height = Math.max(values[index] / max * 100, 2);
      const center = step * index + step / 2;
      return html`<g><title>${row.day || row.date} · ${fmt(values[index])}</title>
        <rect class="trend-bar" x="${center - 12}" y="${125 - height}" width="24" height="${height}" rx="2"/>
        <text x="${center}" y="${115 - height}" text-anchor="middle">${fmt(values[index])}</text>
        <text x="${center}" y="148" text-anchor="middle">${String(row.day || row.date || '').slice(5)}</text></g>`;
    })}</svg></div>`;
}
export function overview(state) {
  const data = state.overview || {};
  if (state.area !== 'admin') return userOverview(state);
  const metrics = data.metrics || {};
  const summary = metrics.summary || {};
  const scope = state.window === 'process' ? t("copy.0376d47bc1") : `${t("copy.03aeb7c768")} ${state.window === '7d' ? '7' : '30'} ${t("copy.0abb126ae6")}`;
  const recent = [...(metrics.recent || [])].reverse().slice(0, 20);
  const percentile = value => value == null ? t('copy.b336a174cd') : fmt(value);
  const stats = [ [t("copy.855754c132"), fmt(summary.requests ?? metrics.counters?.requests)], [t("copy.47d2ca1352"), summary.success_rate == null ? t("copy.b336a174cd") : `${fmt(summary.success_rate * 100)}%`],
    [t("copy.08a60e40fe"), `${percentile(summary.p50_ms)} / ${percentile(summary.p95_ms)} ms`], [t("copy.dd4e402aba"), money(summary.estimated_cost_usd)], [t("copy.f44a57bc6b"), fmt(summary.fallbacks)],
    [t("copy.c5b8203200"), `${(data.health || state.providers.map(p => p.health)).filter(h => h?.state === 'healthy').length} / ${fmt(data.enabled_count)}`] ];
  return html`${head(state, html`${field('metrics-window', t("copy.1888476e9c"), state.window, { choices: [['process', t("copy.09e161129a")], ['7d', t("copy.2261b06712")], ['30d', t("copy.f729bb3d3f")]] })}${button(t("copy.0468ee76ee"), 'refresh')}`)}
    <p class="section-foot" data-testid="metric-scope">${t("copy.1d9f798f57")}${scope}${t("copy.973237a7e9")}</p>
    <div class="stats">${stats.map(([name, value]) => html`<div class="stat"><div class="stat-label">${name}</div><div class="stat-value">${value}</div><div class="stat-note">${scope}</div></div>`)}</div>
    ${panel(t("copy.7b3c22fb10"), body(trend(metrics.trend || [])))}
    ${panel(t("copy.ac263d5b8d"), (metrics.by_provider || []).length ? table(t("copy.18fbba0bfc"), [t("copy.ec309ab207"), t("copy.393e124155"), t("copy.47d2ca1352"), 'p50 / p95', t("copy.dd4e402aba"), t('copy.6320b4a872')], metrics.by_provider.map(row => [
      row.name || row.provider, fmt(row.requests), `${fmt((row.success_rate || 0) * 100)}%`, `${percentile(row.p50_ms)} / ${percentile(row.p95_ms)} ms`, money(row.estimated_cost_usd),
      html`${Object.entries(row.statuses || {}).map(([status, count]) => badge(status, `${label(status)} · ${fmt(count)}`))}`,
    ])) : empty(t("copy.a3a0d4790f"), t("copy.3139e36fe0")))}
    ${panel(t("copy.9eb591385b"), providerTable(state, false), button(t("copy.2a3c31eec8"), 'go', 'providers'))}
    ${data.enabled_count ? html`<details class="setup-summary"><summary>${t("copy.8ef82190ff")}</summary><p>${t("copy.6fb5599e5b")}</p></details>`
      : panel(t("copy.715ee9dc84"), body(html`<ol class="steps"><li>${t("copy.6b06f489fc")}</li><li>${t("copy.affc127607")}</li><li>${t("copy.2990af3788")}</li></ol>`), button(t("copy.6f760cbd09"), 'go', 'providers'))}
    ${panel(t("copy.90c70831c0"), recent.length ? table(t("copy.b2bb2616bc"), [t("copy.12da486580"), t("copy.8b6ff49851"), t("copy.f974f65262"), t("copy.bb7ef73495"), t("copy.6320b4a872")], recent.map(row => [
      html`<button class="request-link" data-action="request-detail" data-value="${row.request_id}">${row.request_id}</button>`, time(row.timestamp),
      html`${label(row.intent)}<span class="cell-sub">${(row.providers || []).join(' / ')}</span>`, fmt(row.result_count), html`${(row.attempts || []).map(a => badge(a.status))}`,
    ])) : empty(t("copy.a380125a40"), t("copy.62231dad05")), badge('unknown', t("copy.6a5b25b58e")))}`;
}
function userOverview(state) {
  const providers = state.providers.filter(p => p.enabled);
  return html`${head(state, button(t("copy.0468ee76ee"), 'refresh'))}<section class="personal-welcome"><div><h2>${t("copy.707f709afb")}${state.user.username}。</h2><p>${t("copy.5c988cba47")}</p></div>
    <div class="personal-actions">${button(t("copy.bdceb7de57"), 'go', 'search', 'primary')}${button(t("copy.871d639f51"), 'go', 'keys')}</div></section>
    <div class="stats personal-stats">${[[t("copy.f44b6983bb"), providers.length], [t("copy.46638f6bd7"), (state.data.keys || []).filter(k => !k.revoked && (!k.expires_at || k.expires_at > Date.now() / 1000)).length]]
      .map(([name, value]) => html`<div class="stat"><span class="stat-label">${name}</span><div class="stat-value">${fmt(value)}</div></div>`)}</div>
    ${panel(t("copy.a7385cfb13"), providers.length ? table(t("copy.36e873f5f1"), [t("copy.d44e9b3d3b"), t("copy.ba40014ff4")], providers.map(p => [p.name, p.provider])) : empty(t("copy.9c82245255"), t("copy.4d1b8188b0")))}
    ${panel(t("copy.b3f3b88611"), body(html`<p>${t("copy.eebbf79268")}</p>`), button(t("copy.ab9d79a79e"), 'go', 'integration'))}`;
}
export function providers(state) {
  return html`${head(state, html`${button(t("copy.429ea3af44"), 'provider-export')}${button(t("copy.b48b651829"), 'provider-import')}${button(t("copy.175a4ae81f"), 'provider-add', '', 'primary')}`)}
    ${panel(t("copy.93d583ccb4"), html`${body(toolbar(state))}<div id="table-results" data-testid="providers-table">${providerTable(state)}</div>`, badge('unknown', `${state.providers.length} ${t("copy.af9a620ed1")}`))}
    <div class="note">${t("copy.96aa2de9d5")}</div>`;
}
const levels = [['auto', t("copy.7eb336e42c")], ['low', t("copy.aa9e366f68")], ['medium', t("copy.a567bdaa11")], ['high', t("copy.b1c27820fe")]];
export function search(state) {
  const draft = state.searchDraft || {};
  const advanced = [ ['authority', t("copy.0751e1fa72")], ['recall', t("copy.3e493076b1")], ['precision', t("copy.408ce7a76a")], ['semantic', t("copy.08a0087cdb")], ['source_diversity', t("copy.8faa9a617c")], ['latency', t("copy.fe62c19f4d")], ['cost', t("copy.04966f7fa4")] ];
  return html`${head(state, html`${button(t("copy.7ef9c46b79"), 'search-share')}${button(t("copy.84d5c41717"), 'search-curl')}`)}
    ${panel(t("copy.8e355d0549"), body(html`<form id="search-form" data-testid="search-form"><div class="search-bar">
      ${field('query', t("copy.b445ac0cb7"), draft.query || '', { id: 'search-query', required: true, maxlength: 10000, placeholder: t("copy.68af8e8c79") })}<button class="btn primary" type="submit">${t("search.run")}</button></div>
      <div class="search-options">${field('search_tool_name', t("copy.9eb591385b"), draft.search_tool_name || 'auto', { choices: [['auto', t("copy.05275ff656")], ...state.providers.filter(p => p.enabled).map(p => [p.name, p.name])] })}
      ${field('intent', t("copy.9b7bf5a67a"), draft.intent || 'auto', { choices: options([
        'auto', 'general', 'news', 'academic', 'deep', 'coding', 'people']) })}
      ${field('freshness', t("copy.cea526c674"), draft.freshness || 'auto', { choices: [['auto', t("copy.7eb336e42c")], ['any', t("copy.f203d577d1")], ['day', t("copy.5448481f38")], ['week', t("copy.d94daba316")], ['month', t("copy.364a4dfc2d")], ['year', t("copy.3226061bb8")]] })}
      ${field('max_results', t("copy.fe884dfbf2"), draft.max_results || 10, { type: 'number', min: 1, max: 20, required: true })}</div>
      <details><summary>${t("copy.584298f178")}</summary><div class="search-options">${advanced.map(([name, title]) => field(name, title, draft[name] || 'auto', { choices: levels }))}
      ${field('latency_budget_ms', t("copy.8456d8fde6"), draft.latency_budget_ms || '', { type: 'number', min: 100, max: 60000 })}
      ${field('cost_budget_usd', t("copy.8c89e7fa35"), draft.cost_budget_usd || '', { type: 'number', min: 0, max: 10, step: '0.001' })}
      ${field('fusion', t("copy.70e1ebe94a"), draft.fusion || 'weighted_rrf', { choices: options(['weighted_rrf', 'rrf', 'none']) })}</div>
      ${field('search_domain_filter', t("copy.c1ba8890e2"), draft.search_domain_filter || '', { placeholder: 'python.org, -example.com', hint: t("copy.b2fcf6934b") })}</details>${formError()}</form>`))}
    ${panel(t("copy.88d72ece7c"),
      body(html`<div id="search-results" data-testid="search-results" aria-live="polite">${searchResults(state)}</div>`),
      html`<span class="results-meta" id="results-meta">${state.searchResult ? `${fmt(state.searchResult.results?.length)} ${t("copy.bd0bedc6f4")}` : t("copy.5698518d9c")}</span>`)}`;
}
export function searchResults(state) {
  const data = state.searchResult;
  return data ? html`${data.results?.length ? results(data.results) : empty(t("copy.f602294630"), t("copy.9f6cf4b683"))}
    ${panel(t("copy.1f424578b7"), body(timeline(data)))}` : empty(t("copy.ff10104dcd"), t("copy.eda4b442bc"));
}
export function keyTable(state) {
  const records = filtered(state, state.data.keys || []);
  return records.length ? table(t("copy.72b4ff83ec"), [t("copy.59a646f681"), ...(state.area === 'admin' ? [t("copy.43a7f4b4c5")] : []), t("copy.6320b4a872"), t("copy.7f5b4fde7b"), t("copy.8b6ff49851"), t("copy.ed31fbb483")], records.map(key => {
    const status = key.revoked ? 'revoked' : key.expires_at && key.expires_at <= Date.now() / 1000 ? 'expired' : 'active';
    return [html`<strong>${key.name}</strong><span class="cell-sub mono">${key.prefix}…</span>`, ...(state.area === 'admin' ? [key.username || key.user_id] : []), badge(status),
      html`${(key.scopes || ['search', 'protocol']).map(scope => scope === 'search' ? 'Search API' : t("copy.e2da29bdcb")).join(' · ')}<span class="cell-sub">${fmt(key.usage_count)} ${t("copy.d8762c5105")}</span>`,
      html`<span class="cell-sub">${t("copy.cde2cd071d")} ${date(key.created_at)}</span><span class="cell-sub">${t("copy.97399bd882")} ${date(key.expires_at, t("copy.2c60316d5e"))}</span><span class="cell-sub">${t("copy.cdfd0b34e4")} ${date(key.last_used_at)}</span>`,
      key.revoked ? html`<span class="muted">${t("copy.fef96e34f7")}</span>` : more(button(t("copy.9585b9a120"), 'key-revoke', key.id, 'danger'))];
  })) : empty(t("copy.3c765c8279"), t("copy.97bf50f6e1"));
}
export function keys(state) {
  return html`${head(state, button(t("copy.f0b89fb051"), 'key-create', '', 'primary'))}<div class="note">${t("copy.82e528110f")}</div>
    ${panel(state.area === 'admin' ? t("copy.2d690759a9") : t("copy.967653efa4"), html`${body(toolbar(state, t("copy.3282a6fbab")))}<div id="table-results" data-testid="keys-table">${keyTable(state)}</div>`)}`;
}
export function userTable(state) {
  const users = filtered(state, state.data.users || []);
  return users.length ? table(t("copy.2b28326c70"), [t("account.username"), t("copy.527d442dc0"), t("copy.07ec86e0f1"), t("copy.ed31fbb483")], users.map(user => [
    html`<strong>${user.username}</strong>${user.id === state.user.id ? badge('unknown', t("copy.1bb1e785ad")) : ''}`,
    html`${label(user.role)} ${badge(user.enabled === false ? 'disabled' : 'active', user.enabled === false ? t("copy.a8c3698b5b") : t("copy.296de0e31f"))}`, time(user.created_at),
    html`<div class="actions">${button(t("copy.0518365699"), 'user-edit', user.id)}${user.id !== state.user.id ? more(button(t("copy.b75872bba6"), 'user-delete', user.id, 'danger')) : ''}</div>`,
  ])) : empty(t("copy.656a2b2ccb"), t("copy.425b50f842"));
}
export function users(state) {
  return html`${head(state, button(t("copy.664a80843b"), 'user-create', '', 'primary'))}${panel(t("copy.59fa9c9382"), html`${body(toolbar(state))}<div id="table-results" data-testid="users-table">${userTable(state)}</div>`)}
    <div class="note">${t("copy.5a85716094")}</div>`;
}
export function audit(state) {
  const filters = state.auditFilters || {};
  const events = state.data.events || [];
  return html`${head(state)}${panel(t("copy.b2db0d03bb"), body(html`<form id="audit-form"><div class="search-options">
    ${field('actor_id', t("copy.40ac707bea"), filters.actor_id || '')}${field('object_type', t("copy.53f92c0639"), filters.object_type || '', {
       choices: [['', t("copy.5c55a67935")], ['provider', t("copy.9eb591385b")], ['key', t("copy.81123c56d5")], ['user', t("copy.0d0e1a86b3")], ['session', t("copy.a63280253f")]] })}
    
    ${field('since', t("copy.6a9906c79f"), filters.since || '', { type: 'datetime-local' })}
    ${field('until', t("copy.f502764499"), filters.until || '', { type: 'datetime-local' })}</div>${formError()}
    <button class="btn" type="submit">${t("copy.a024d90a92")}</button></form>`))}
    ${panel(t("copy.a0f79e91f1"), events.length ? table(t("copy.9e82c530e2"), [t("copy.8b6ff49851"), t("copy.e18e3f8ab2"), t("copy.be37d84119"), t("copy.53f92c0639")], events.map(event => [time(event.timestamp), event.actor_id || t("copy.5b50d7c4b5"),
      auditAction(event.action), html`${auditObject(event.object_type)}<span class="cell-sub mono">${event.object_id || '—'}</span>`])) : empty(t("copy.42a4c94685"), t("copy.9a33907c47")), badge('unknown', `${fmt(state.data.total)} ${t("copy.f004f1d84c")}`))}
    <div class="actions">${button(t("copy.c9b9ae7a61"), 'audit-prev')}${button(t("copy.8a8542f696"), 'audit-next')}<span>${t("copy.af50a0fe2a")} ${Math.floor(state.auditOffset / 50) + 1} ${t("copy.d24d3c9946")}</span></div>`;
}
const auditAction = action => ({
  change_password: t("audit.changePassword"),
  create: t("copy.cde2cd071d"), update: t("copy.3055a035f0"), delete: t("copy.2f9daa8289"), revoke: t("copy.926a50b98e"), 
  login: t("copy.1e2df9c307"), logout: t("copy.498e1d59b4"), import: t("copy.576d81bb06"), sync_engines: t("copy.3339ffdfa0"), revoke_others: t("copy.54a43c4b0e") }[action] || action);
const auditObject = object => ({ provider: t("copy.9eb591385b"), key: t("copy.81123c56d5"), user: t("copy.0d0e1a86b3"), session: t("copy.a63280253f") }[object] || object);
export function settings(state) {
  return html`${head(state)}<div class="grid-two">${panel(t("copy.81ecab649f"), body(html`<form id="password-form">${formError()}
    ${field('current_password', t("copy.a114cfb687"), '', { type: 'password', required: true, autocomplete: 'current-password' })}
    ${field('new_password', t("copy.515e9c7cf7"), '', { type: 'password', required: true, minlength: 12, maxlength: 256, autocomplete: 'new-password' })}
    ${field('confirm_password', t("copy.6fde05a916"), '', { type: 'password', required: true, minlength: 12, maxlength: 256, autocomplete: 'new-password' })}
    <button class="btn primary" type="submit">${t("copy.8281708430")}</button><p class="section-foot">${t("copy.e0781c74f1")}</p></form>`))}
    ${panel(t("copy.c0629ce122"), body(html`<p>${state.user.username} · ${label(state.user.role)}</p>${field('theme', t("copy.0c3421deb8"), state.theme, { choices: [['system', t("copy.217cfe7db1")], ['light', t("copy.aa0819dfc4")], ['dark', t("copy.a6b75d0680")]] })}`))}</div>
    <div id="sessions-panel">${sessionPanel(state)}</div>`;
}

export function sessionPanel(state) {
  const sessions = state.data.sessions || [];
  return panel(t("copy.cd438f5d0c"), sessions.length ? table(t("copy.acc0406918"), [t("copy.a63280253f"), t("copy.07ec86e0f1"), t("copy.a8e5f17166")], sessions.map(session => [
      session.current ? badge('active', t("copy.c68978537c")) : html`<span class="mono">${String(session.id).slice(0, 12)}…</span>`, time(session.created_at), date(session.expires_at),
    ])) : empty(t("copy.01030c7ae7"), t("copy.cac4f125f6")), button(t("copy.54a43c4b0e"), 'sessions-revoke'));
}
export function integration(state) {
  const base = location.origin;
  const payload = '{"query":"Python official documentation","search_tool_name":"auto","max_results":10}';
  const snippets = {
    curl: `curl '${base}/search' \\\n  -H 'Authorization: Bearer YOUR_API_KEY' \\\n  -H 'Content-Type: application/json' \\\n  -d '${payload}'`,
    python: `import os\nimport requests\n\nresponse = requests.post(\n    "${base}/search",\n    headers={"Authorization": f"Bearer {os.environ['SEARCH_API_KEY']}"},\n    json=${payload}, timeout=65,\n)\nresponse.raise_for_status()\nprint(response.json()["results"])`,
    javascript: `const response = await fetch('${base}/search', {\n  method: 'POST',\n  headers: { Authorization: 'Bearer YOUR_API_KEY', 'Content-Type': 'application/json' },\n  body: JSON.stringify(${payload}),\n});` +
      `\nif (!response.ok) throw new Error('Search failed');\nconsole.log(await response.json());`,
    protocol: `curl '${base}/bensz-search/v1/search' \\\n  -H 'Authorization: Bearer YOUR_API_KEY' \\\n  -H 'Content-Type: application/json' \\\n  -d '{"query":"Python official documentation"}'`,
    mcp: JSON.stringify({ mcpServers: { 'bensz-search': { url: `${base}/bensz-search/mcp`, headers: { Authorization: 'Bearer YOUR_API_KEY' } } } }, null, 2),
  };
  state.snippets = snippets;
  return html`${head(state, button(t("copy.6e258aa27a"), 'go', 'keys'))}<div class="note">${t("copy.2e98389ed9")}</div>
    ${Object.entries(snippets).map(([name, content]) => panel({ curl: 'cURL', python: 'Python', javascript: 'JavaScript', protocol: t("copy.51e5109618"), mcp: 'MCP · Streamable HTTP' }[name],
      body(html`<pre class="code">${content}</pre>`), button(t("copy.2b8e47feaf"), 'copy-snippet', name)))}
    ${panel(t("copy.9541ee3d4b"), table(t("copy.498ea201b5"), [t("copy.9634fb0832"), t("copy.4262c45dc7")], [ ['query', t("copy.c2edefffc6")], ['search_tool_name', t("copy.d1e14840d1")],
      ['max_results', t("copy.351a84f97d")], ['profile.intent', t("copy.5c27be5044")], ['constraints', t("copy.71f4928557")],
      ['search_domain_filter', t("copy.5ed96bea0a")], ['debug', t("copy.3dc7e93ff2")], ]), html`<a class="btn" href="/api/docs" target="_blank" rel="noopener noreferrer">${t("copy.0c21997c24")}</a>`)}`;
}
export function help(state) {
  const releases = state.data;
  return html`${head(state)}${panel(t("copy.00c94cf632"), body(html`<p>${t("copy.435bd0f89d")}<strong>v${releases.version || state.overview?.version || t("copy.756762e293")}</strong></p>
    <p>${t("copy.65c96cbd07")}</p><div class="actions">
    <a class="btn" href="/api/docs" target="_blank" rel="noopener noreferrer">${t("copy.0c21997c24")}</a>
    <a class="btn" href="${safeLink(releases.documentation_url, 'https://github.com/huangwb8/bensz-search#readme')}" target="_blank" rel="noopener noreferrer">${t("copy.ad308c52e6")}</a>
    <a class="btn" href="${safeLink(releases.changelog_url, 'https://github.com/huangwb8/bensz-search/blob/main/CHANGELOG.md')}" target="_blank" rel="noopener noreferrer">${t("copy.ba27e12286")}</a></div>
    ${releases.update_check === 'unavailable' ? html`<p class="muted">${t('release.unavailable')}</p>` : ''}
    ${releases.update_available === true && releases.latest_version ? html`<div class="note">${t("copy.47ceaf502c")} ${releases.latest_version} ${t("copy.ca3b6aa3ff")}</div>` : ''}`))}`;
}
function safeLink(url, fallback) {
  try { const parsed = new URL(url, location.origin); return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : fallback; } catch { return fallback; }
}
export const views = { overview, providers, search, keys, users, audit, settings, integration, help };
