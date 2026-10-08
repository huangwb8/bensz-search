import { t, site } from "./i18n.js";
/** Small, dependency-free components. Interpolated strings are always escaped. */
class Markup {
  constructor(value) { this.value = value; }
  toString() { return this.value; }
}
export const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));
export function html(parts, ...values) {
  const render = value => value instanceof Markup ? value.value : Array.isArray(value) ? value.map(render).join('') : escape(value);
  return new Markup(parts.reduce((output, part, index) => output + part + (index < values.length ? render(values[index]) : ''), ''));
}
export const fmt = value => new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(Number(value) || 0);
export const money = value => '$' + new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 5 }).format(Number(value) || 0);
export function date(value, fallback = t("copy.9bd11dda28")) {
  if (!value) return fallback;
  const time = new Date(typeof value === 'number' ? value * 1000 : value);
  if (!Number.isFinite(time.getTime())) return t("copy.c3b1c55df6");
  return time.toLocaleString('zh-CN', { hour12: false, timeZoneName: 'short' });
}
export function time(value) {
  if (!value) return html`<span class="muted">${t("copy.c3b1c55df6")}</span>`;
  const timestamp = new Date(typeof value === 'number' ? value * 1000 : value).getTime();
  if (!Number.isFinite(timestamp)) return html`<span class="muted">${t('copy.c3b1c55df6')}</span>`;
  const minutes = Math.floor((Date.now() - timestamp) / 60000);
  const relative = minutes < 0 ? date(value) : minutes < 1 ? t("copy.de6785d99e") : minutes < 60 ? `${minutes} ${t("copy.6c078d9cf0")}` : minutes < 1440 ? `${Math.floor(minutes / 60)} ${t("copy.595c9daa17")}` : `${Math.floor(minutes / 1440)} ${t("copy.ad841f709d")}`;
  return html`<time title="${date(value)}" datetime="${new Date(timestamp).toISOString()}">${relative}<span class="cell-sub">${date(value)}</span></time>`;
}
export const messages = {
  success: t("copy.053461ce86"), timeout: t("copy.8b7f52f0db"), quota: t("copy.b02c21369b"), auth: t("copy.4fa9e445ed"), authentication: t("copy.4fa9e445ed"),
  rate_limit: t("copy.21467cb030"), rate_limited: t("copy.21467cb030"), empty: t("copy.3852c2a226"), error: t("copy.1f93ee4945"),
  network: t("copy.156c4a73d3"), unavailable: t("copy.7f361b6e89"), invalid_request: t("copy.9a1b792b7e"), skipped: t("copy.71e95b289a"), cancelled: t("copy.a37778f17c"),
  bad_request: t("copy.628bc0e708"),
  invalid_response: t("copy.aacc741e58"), provider_error: t("copy.1f93ee4945"), server: t("copy.7f361b6e89"), disabled: t("copy.a8c3698b5b"), open: t("copy.ce5e455dd0"), half_open: t("copy.eedad15a77"), healthy: t("copy.296de0e31f"), degraded: t("copy.9f22b41cf5"), unknown: t("copy.2b949f6191"),
  explicit: t('intent.explicit'), protocol: t('intent.protocol'),
  failed: t('status.failed'), partial_success: t('status.partialSuccess'), no_results: t('status.noResults'),
  circuit_open: t('status.circuitOpen'), budget_exceeded: t('status.budgetExceeded'), call_budget_exceeded: t('status.callBudgetExceeded'),
  health_open: t('status.circuitOpen'), protocol_error: t('status.protocolError'), policy_blocked: t('status.policyBlocked'), transport_error: t('copy.156c4a73d3'),
  revoked: t("copy.fef96e34f7"), expired: t("copy.2fe0e3339a"), active: t("copy.11afd2a534"), admin: t("copy.e19796712f"), member: t("copy.6e6d6ddbb7"), single: t("copy.b8d2617ce7"), parallel: t("copy.6817847ef2"), none: t("copy.450fd723bf"),
  rrf: t("copy.9be0b4e526"), weighted_rrf: t("copy.b2ab8c6ee0"), auto: t("copy.7eb336e42c"), general: t("copy.835b700e02"), news: t("copy.d39567b2b9"), academic: t("copy.a5f99439a6"), deep: t("copy.d1b31cf84b"), coding: t("copy.e6f04ffbaa"), people: t("copy.8d7aff5a59"),
};
export const label = value => messages[value] || t("copy.ec0d9bdb00");
export function badge(value, text = label(value)) {
  const tone = ['success', 'healthy', 'active'].includes(value) ? 'good' : ['open', 'circuit_open', 'failed', 'error', 'auth', 'quota', 'expired'].includes(value) ? 'bad' : ['degraded', 'half_open', 'timeout', 'partial_success'].includes(value) ? 'warning' : '';
  return html`<span class="tag ${tone}"><span class="dot" aria-hidden="true"></span>${text}</span>`;
}
export const button = (text, action, value = '', tone = '') => html`<button class="btn ${tone}" type="button" data-action="${action}" data-value="${value}">${text}</button>`;
export const empty = (title, description) => html`<div class="empty"><h3>${title}</h3><p>${description}</p></div>`;
export function panel(title, body, actions = html``, description = '') {
  return html`<section class="panel"><div class="panel-head"><div><h2>${title}</h2>${description ? html`<p>${description}</p>` : ''}</div>${actions}</div>${body}</section>`;
}
export const body = content => html`<div class="panel-body">${content}</div>`;
export function table(caption, headers, rows) {
  return html`<div class="table-wrap"><table><caption class="sr-only">${caption}</caption><thead><tr>${headers.map(h => html`<th scope="col">${h}</th>`)}</tr></thead>
    <tbody>${rows.map(cells => html`<tr>${cells.map((cell, index) => html`<td data-label="${headers[index]}">${cell}</td>`)}</tr>`)}</tbody></table></div>`;
}
export function field(name, title, value = '', options = {}) {
  const id = options.id || name.replaceAll('_', '-');
  const attrs = html`${options.required ? html` required` : ''}${options.disabled ? html` disabled` : ''}
    ${options.min !== undefined ? html` min="${options.min}"` : ''}${options.max !== undefined ? html` max="${options.max}"` : ''}
    ${options.maxlength ? html` maxlength="${options.maxlength}"` : ''}${options.minlength ? html` minlength="${options.minlength}"` : ''}
    ${options.step ? html` step="${options.step}"` : ''}${options.pattern ? html` pattern="${options.pattern}"` : ''}`;
  const input = options.choices ? html`<select id="${id}" name="${name}" ${attrs}>${options.choices.map(([v, l]) => html`<option value="${v}" ${String(v) === String(value) ? html`selected` : ''}>${l}</option>`)}</select>`
    : options.multiline ? html`<textarea id="${id}" name="${name}" ${attrs} placeholder="${options.placeholder || ''}">${value}</textarea>`
      : html`<input id="${id}" name="${name}" type="${options.type || 'text'}" value="${value}" ${attrs}
        placeholder="${options.placeholder || ''}" autocomplete="${options.autocomplete || 'off'}">`;
  return html`<div class="field"><label for="${id}">${title}</label>${input}<small id="${id}-hint">${options.hint || ''}</small><span class="field-error" data-error-for="${name}"></span></div>`;
}
export const formError = () => html`<div class="form-error" role="alert"></div>`;
export const check = (name, title, checked = false) => html`<label class="checkbox"><input type="checkbox" name="${name}" ${checked ? html`checked` : ''}>${title}</label>`;
export const options = values => values.map(value => [value, label(value)]);
export function more(actions) {
  return html`<details class="more"><summary class="btn" aria-label="${t("copy.9f07d2ce41")}">${t("copy.38844b135c")}</summary><div class="more-menu">${actions}</div></details>`;
}
export function results(results) {
  return html`${results.map((result, index) => {
    let url = '';
    try { const parsed = new URL(result.url); if (['http:', 'https:'].includes(parsed.protocol)) url = parsed.href; } catch { /* Invalid URLs are rendered as text. */ }
    const snippet = result.snippet || result.content || result.description || '';
    return html`<article class="result"><span class="result-url">${result.url}</span>
      ${url ? html`<a class="result-title" href="${url}" target="_blank" rel="noopener noreferrer">${index + 1}. ${result.title || result.url}</a>` : html`<strong>${result.title || t("copy.8c974da9d8")}</strong>`}
      <p class="result-snippet">${snippet}</p>${snippet.length > 240 ? button(t("copy.60d4cbf2ff"), 'snippet', '', 'ghost') : ''}
      ${result.snippet_kind === 'generated_summary' ? badge('unknown', t("copy.d1953e2ba4")) : ''}${result.provider ? badge('unknown', result.provider) : ''}</article>`;
  })}`;
}
export function timeline(data = {}) {
  const debug = data.debug || data;
  const plan = debug.plan || {};
  const reasons = debug.routing_reason || plan.routing_reason || [];
  const attempts = debug.attempts || [];
  const contributions = debug.fusion_contribution?.providers || {};
  const marginal = debug.marginal_gain || {};
  return html`<ol class="timeline"><li><h3>${t("copy.b9670c85a4")}${plan.strategy ? html` · ${label(plan.strategy)}` : ''}</h3>
    <p>${reasons.length ? reasons.join('；') : t("copy.e7a76bfb79")}</p><p>${(debug.providers || plan.providers?.map(p => p.name) || []).join(' → ')}</p></li>
    ${attempts.map(attempt => html`<li><h3>${attempt.provider || attempt.name} ${badge(attempt.status || attempt.category)}</h3>
      <p>${t("copy.18045b8c40")} ${fmt(attempt.latency_ms)} ${t("copy.d81eb6b7ed")} ${fmt(attempt.result_count)} ${t("copy.f004f1d84c")}${attempt.category && attempt.category !== 'success' ? html` · ${label(attempt.category)}` : ''}</p></li>`)}
    <li><h3>${t("copy.70e1ebe94a")}</h3><p>${label(plan.fusion || (typeof debug.fusion === 'string' ? debug.fusion : 'weighted_rrf'))} · ${fmt(data.results?.length ?? debug.result_count)} ${t("copy.c04f20a090")} ${money(debug.estimated_cost_usd)}</p>
      ${Object.keys(contributions).map(name => html`<p>${name}${t("copy.285ea4f7bd")} ${fmt(contributions[name])} ${t("copy.21ab103af9")} ${fmt(marginal[name])}</p>`)}</li></ol>
    <details class="debug"><summary>${t("copy.ffc67cc3c0")}</summary><pre class="code">${JSON.stringify(debug, null, 2)}</pre></details>`;
}
export function brand(workspace = false) {
  return html`<span class="brand-mark" aria-hidden="true"><svg viewBox="0 0 32 32" fill="none">
    <path d="M25 7H12a5 5 0 0 0 0 10h8a4 4 0 0 1 0 8H7" stroke="currentColor" stroke-width="5" stroke-linecap="square"/><circle cx="25" cy="25" r="3" fill="currentColor"/>
    </svg></span><span class="brand-copy">${workspace ? html`<strong data-site-name>${site.site_name}</strong><span class="app-version" id="app-version">${t("copy.a39ee4f07e")}</span>` : html`<span data-site-name>${site.site_name}</span>`}</span>`;
}
